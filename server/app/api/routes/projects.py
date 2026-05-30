from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.project import ProjectCreate, ProjectRead
from app.schemas.session import RuntimeSessionCreate, RuntimeSessionRead
from app.services import project_service, session_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    project = project_service.create_project(db, payload.title, payload.input_type, payload.source_ref)
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectRead]:
    projects = project_service.list_projects(db)
    return [ProjectRead.model_validate(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: UUID, db: Session = Depends(get_db)) -> ProjectRead:
    project = project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectRead.model_validate(project)


@router.get("/{project_id}/sessions", response_model=list[RuntimeSessionRead])
def list_project_sessions(project_id: UUID, db: Session = Depends(get_db)) -> list[RuntimeSessionRead]:
    sessions = session_service.list_sessions(db, project_id=project_id)
    return [RuntimeSessionRead.model_validate(session) for session in sessions]


@router.post("/{project_id}/sessions", response_model=RuntimeSessionRead, status_code=status.HTTP_201_CREATED)
def create_project_session(
    project_id: UUID,
    payload: RuntimeSessionCreate,
    db: Session = Depends(get_db),
) -> RuntimeSessionRead:
    project = project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    session = session_service.create_session(db, project_id, payload.title, payload.summary)
    return RuntimeSessionRead.model_validate(session)
