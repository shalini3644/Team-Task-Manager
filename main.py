import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

import models
from auth import ALGORITHM, SECRET_KEY, create_token, hash_password, verify_password
from database import SessionLocal, engine


models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Team Task Manager API", version="1.0.0")
security = HTTPBearer()

allowed_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGIN", "*").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials="*" not in allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_ROLES = {"admin", "member"}
VALID_STATUSES = {"todo", "in_progress", "done"}
VALID_PRIORITIES = {"low", "medium", "high"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=255)
    password: str = Field(min_length=6, max_length=128)
    role: str = "member"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name must be at least 2 characters")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in VALID_ROLES:
            raise ValueError("Role must be admin or member")
        return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address")
        return value


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: Optional[str] = Field(default="", max_length=2000)
    member_ids: list[int] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Project name must be at least 2 characters")
        return value

    @field_validator("member_ids")
    @classmethod
    def validate_member_ids(cls, value: list[int]) -> list[int]:
        if any(user_id <= 0 for user_id in value):
            raise ValueError("Member IDs must be positive")
        return list(dict.fromkeys(value))


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Project name must be at least 2 characters")
        return value


class ProjectMemberCreate(BaseModel):
    user_id: int = Field(gt=0)


class UserRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in VALID_ROLES:
            raise ValueError("Role must be admin or member")
        return value


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: Optional[str] = Field(default="", max_length=3000)
    assigned_to_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    due_date: Optional[datetime] = None
    priority: str = "medium"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Task title must be at least 2 characters")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        if value not in VALID_PRIORITIES:
            raise ValueError("Priority must be low, medium, or high")
        return value


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=180)
    description: Optional[str] = Field(default=None, max_length=3000)
    assigned_to_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Task title must be at least 2 characters")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in VALID_PRIORITIES:
            raise ValueError("Priority must be low, medium, or high")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in VALID_STATUSES:
            raise ValueError("Status must be todo, in_progress, or done")
        return value


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in VALID_STATUSES:
            raise ValueError("Status must be todo, in_progress, or done")
        return value


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def serialize_user(user: models.User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def serialize_project(project: models.Project) -> dict:
    members = sorted((serialize_user(member.user) for member in project.members), key=lambda item: item["name"].lower())
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "created_by_id": project.created_by_id,
        "created_at": project.created_at.isoformat(),
        "members": members,
        "task_count": len(project.tasks),
    }


def serialize_task(task: models.Task) -> dict:
    due_date = task.due_date.isoformat() if task.due_date else None
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "status": task.status,
        "priority": task.priority,
        "assigned_to_id": task.assigned_to_id,
        "assignee": serialize_user(task.assignee),
        "project_id": task.project_id,
        "project": {"id": task.project.id, "name": task.project.name},
        "due_date": due_date,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> models.User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(user: models.User = Depends(current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def ensure_project_member(db: Session, project_id: int, user_id: int) -> None:
    membership = (
        db.query(models.ProjectMember)
        .filter(models.ProjectMember.project_id == project_id, models.ProjectMember.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee is not on this project")


def task_query_for(user: models.User, db: Session):
    query = db.query(models.Task).options(joinedload(models.Task.assignee), joinedload(models.Task.project))
    if user.role == "admin":
        return query
    return query.filter(models.Task.assigned_to_id == user.id)


@app.get("/api/health")
def health():
    return {"status": "ok"}



@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(func.lower(models.User.email) == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    user_count = db.query(models.User).count()
    role = "admin" if user_count == 0 else "member"
    user = models.User(
        name=payload.name.strip(),
        email=payload.email,
        password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token({"sub": str(user.id), "role": user.role})
    return {"token": token, "user": serialize_user(user)}


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(func.lower(models.User.email) == payload.email).first()
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_token({"sub": str(user.id), "role": user.role})
    return {"token": token, "user": serialize_user(user)}


@app.get("/api/me")
def me(user: models.User = Depends(current_user)):
    return serialize_user(user)


@app.get("/api/users")
def users(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return [serialize_user(user) for user in db.query(models.User).order_by(models.User.name).all()]


@app.patch("/api/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target.id == admin.id and payload.role != "admin":
        admin_count = db.query(models.User).filter(models.User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one admin is required")

    target.role = payload.role
    db.commit()
    db.refresh(target)
    return serialize_user(target)


@app.get("/api/projects")
def projects(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(models.Project).options(
        joinedload(models.Project.members).joinedload(models.ProjectMember.user),
        joinedload(models.Project.tasks),
    )
    if user.role != "admin":
        query = query.join(models.ProjectMember).filter(models.ProjectMember.user_id == user.id)
    return [serialize_project(project) for project in query.order_by(models.Project.created_at.desc()).all()]


@app.post("/api/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = models.Project(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        created_by_id=admin.id,
    )
    db.add(project)
    db.flush()

    member_ids = set(payload.member_ids)
    member_ids.add(admin.id)
    users = db.query(models.User).filter(models.User.id.in_(member_ids)).all()
    found_ids = {user.id for user in users}
    if found_ids != member_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more members do not exist")

    for user_id in member_ids:
        db.add(models.ProjectMember(project_id=project.id, user_id=user_id))

    db.commit()
    db.refresh(project)
    return serialize_project(
        db.query(models.Project)
        .options(joinedload(models.Project.members).joinedload(models.ProjectMember.user), joinedload(models.Project.tasks))
        .filter(models.Project.id == project.id)
        .one()
    )


@app.post("/api/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
def add_project_member(
    project_id: int,
    payload: ProjectMemberCreate,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    user = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not project or not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project or user not found")

    existing = (
        db.query(models.ProjectMember)
        .filter(models.ProjectMember.project_id == project_id, models.ProjectMember.user_id == payload.user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already on this project")

    db.add(models.ProjectMember(project_id=project_id, user_id=payload.user_id))
    db.commit()
    return {"message": "Member added"}


@app.patch("/api/projects/{project_id}")
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return serialize_project(
        db.query(models.Project)
        .options(joinedload(models.Project.members).joinedload(models.ProjectMember.user), joinedload(models.Project.tasks))
        .filter(models.Project.id == project.id)
        .one()
    )


@app.delete("/api/projects/{project_id}/members/{user_id}")
def remove_project_member(
    project_id: int,
    user_id: int,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.created_by_id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project owner cannot be removed")

    membership = (
        db.query(models.ProjectMember)
        .filter(models.ProjectMember.project_id == project_id, models.ProjectMember.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found on this project")

    assigned_tasks = (
        db.query(models.Task)
        .filter(models.Task.project_id == project_id, models.Task.assigned_to_id == user_id)
        .count()
    )
    if assigned_tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reassign or delete this member's tasks first")

    db.delete(membership)
    db.commit()
    return {"message": "Member removed"}


@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"message": "Project deleted"}


@app.get("/api/tasks")
def tasks(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return [serialize_task(task) for task in task_query_for(user, db).order_by(models.Task.due_date.asc().nullslast()).all()]


@app.post("/api/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.query(models.Project).filter(models.Project.id == payload.project_id).first()
    assignee = db.query(models.User).filter(models.User.id == payload.assigned_to_id).first()
    if not project or not assignee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project or assignee not found")
    ensure_project_member(db, payload.project_id, payload.assigned_to_id)

    task = models.Task(
        title=payload.title.strip(),
        description=(payload.description or "").strip(),
        assigned_to_id=payload.assigned_to_id,
        project_id=payload.project_id,
        due_date=payload.due_date,
        priority=payload.priority,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return serialize_task(
        db.query(models.Task)
        .options(joinedload(models.Task.assignee), joinedload(models.Task.project))
        .filter(models.Task.id == task.id)
        .one()
    )


@app.patch("/api/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: TaskUpdate,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    values = payload.model_dump(exclude_unset=True)
    if "assigned_to_id" in values:
        assignee = db.query(models.User).filter(models.User.id == values["assigned_to_id"]).first()
        if not assignee:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")
        ensure_project_member(db, task.project_id, values["assigned_to_id"])

    for field, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(task, field, value)
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return serialize_task(
        db.query(models.Task)
        .options(joinedload(models.Task.assignee), joinedload(models.Task.project))
        .filter(models.Task.id == task.id)
        .one()
    )


@app.patch("/api/tasks/{task_id}/status")
def update_task_status(
    task_id: int,
    payload: StatusUpdate,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if user.role != "admin" and task.assigned_to_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own tasks")

    task.status = payload.status
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return serialize_task(
        db.query(models.Task)
        .options(joinedload(models.Task.assignee), joinedload(models.Task.project))
        .filter(models.Task.id == task.id)
        .one()
    )


@app.delete("/api/tasks/{task_id}")
def delete_task(
    task_id: int,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"message": "Task deleted"}


@app.get("/api/dashboard")
def dashboard(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    user_tasks = task_query_for(user, db).all()
    status_counts = {status_name: 0 for status_name in VALID_STATUSES}
    for task in user_tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1

    return {
        "total": len(user_tasks),
        "completed": status_counts.get("done", 0),
        "in_progress": status_counts.get("in_progress", 0),
        "todo": status_counts.get("todo", 0),
        "overdue": len([task for task in user_tasks if task.due_date and task.due_date < now and task.status != "done"]),
        "projects": db.query(models.Project).count()
        if user.role == "admin"
        else db.query(models.ProjectMember).filter(models.ProjectMember.user_id == user.id).count(),
    }


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        requested = static_dir / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(static_dir / "index.html")
