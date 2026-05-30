from sqlalchemy.orm import Session

from app.models.project_context import ProjectContext


def detect_stack(input_type: str, source_ref: str) -> dict:
    lower_ref = source_ref.lower()
    framework = "unknown"
    language = "unknown"

    if "next" in lower_ref:
        framework = "nextjs"
        language = "typescript"
    elif "fastapi" in lower_ref:
        framework = "fastapi"
        language = "python"
    elif "django" in lower_ref:
        framework = "django"
        language = "python"

    return {
        "framework": framework,
        "language": language,
        "package_manager": "unknown",
        "ci": [],
        "docker": False,
        "input_type": input_type,
    }


def create_project(db: Session, title: str, input_type: str, source_ref: str) -> ProjectContext:
    stack = detect_stack(input_type, source_ref)
    project = ProjectContext(
        title=title,
        input_type=input_type,
        source_ref=source_ref,
        status="indexed",
        detected_stack=stack,
        metadata={},
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[ProjectContext]:
    return db.query(ProjectContext).order_by(ProjectContext.updated_at.desc()).all()


def get_project(db: Session, project_id) -> ProjectContext | None:
    return db.get(ProjectContext, project_id)
