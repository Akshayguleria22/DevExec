import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.webhook import DeployWebhookRequest, DeployWebhookResponse
from app.services import task_service
from app.services.webhook_idempotency import register_delivery_id, unregister_delivery_id
from app.services.webhook_security import verify_github_signature
from app.services.webhook_service import (
    create_deployment_event,
    find_existing_task_for_deployment,
    generate_task_input,
    parse_github_webhook_payload,
)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/deploy", response_model=DeployWebhookResponse, status_code=status.HTTP_202_ACCEPTED)
async def handle_deploy_webhook(
    request: Request,
    db: Session = Depends(get_db),
    github_signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    delivery_id: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> DeployWebhookResponse:
    if not settings.webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook secret is not configured")

    raw_body = await request.body()
    if not verify_github_signature(settings.webhook_secret, raw_body, github_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    if not delivery_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing delivery id header")

    inserted = register_delivery_id(db, delivery_id)
    if not inserted:
        return DeployWebhookResponse(
            duplicate_delivery=True,
            message="Duplicate delivery already processed",
        )

    try:
        parsed_body = json.loads(raw_body.decode("utf-8"))
        github_context: dict = {}

        try:
            payload = DeployWebhookRequest.model_validate(parsed_body)
        except ValidationError:
            github_payload, github_context = parse_github_webhook_payload(
                payload=parsed_body,
                github_event=github_event,
                default_api_base_url=settings.default_api_base_url,
            )
            payload = DeployWebhookRequest.model_validate(github_payload)

        if github_event:
            github_context["event"] = github_event
        github_context["delivery_id"] = delivery_id
    except (json.JSONDecodeError, ValidationError) as exc:
        unregister_delivery_id(db, delivery_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload") from exc
    except ValueError as exc:
        unregister_delivery_id(db, delivery_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        existing_task_id = find_existing_task_for_deployment(
            db=db,
            repo_name=payload.repo_name,
            commit_sha=payload.commit_sha,
            api_base_url=payload.api_base_url,
        )

        if existing_task_id is not None:
            task_input, generated_task, endpoints, warnings = generate_task_input(
                repo_name=payload.repo_name,
                branch=payload.branch,
                api_base_url=payload.api_base_url,
                commit_sha=payload.commit_sha,
                github_context=github_context,
                expand_endpoints=payload.expand_endpoints,
            )

            deployment_event = create_deployment_event(
                db=db,
                repo_name=payload.repo_name,
                branch=payload.branch,
                api_base_url=payload.api_base_url,
                commit_sha=payload.commit_sha,
                task_id=existing_task_id,
                generated_task_input=task_input,
                endpoints=endpoints,
            )

            return DeployWebhookResponse(
                deployment_event_id=deployment_event.id,
                task_id=existing_task_id,
                generated_task=generated_task,
                endpoints=endpoints,
                warnings=warnings,
                task_input=task_input,
                reused_task=True,
                message="Reused existing task for identical repo+commit+api_base_url",
            )

        task_input, generated_task, endpoints, warnings = generate_task_input(
            repo_name=payload.repo_name,
            branch=payload.branch,
            api_base_url=payload.api_base_url,
            commit_sha=payload.commit_sha,
            github_context=github_context,
            expand_endpoints=payload.expand_endpoints,
        )

        task = task_service.create_task(db, task_input)
        task_service.enqueue_task(db, task)

        deployment_event = create_deployment_event(
            db=db,
            repo_name=payload.repo_name,
            branch=payload.branch,
            api_base_url=payload.api_base_url,
            commit_sha=payload.commit_sha,
            task_id=task.id,
            generated_task_input=task_input,
            endpoints=endpoints,
        )

        return DeployWebhookResponse(
            deployment_event_id=deployment_event.id,
            task_id=task.id,
            generated_task=generated_task,
            endpoints=endpoints,
            warnings=warnings,
            task_input=task_input,
            message="Webhook processed",
        )
    except Exception:
        unregister_delivery_id(db, delivery_id)
        raise
