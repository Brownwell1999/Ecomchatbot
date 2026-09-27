"""AI Testing Lab accounts, roles and lesson progress (internal API, called only by the gateway).
The gateway decides who may call what (admin-only operations, self-protection); this module
stores and validates the data."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from shared.config import Settings
from shared.db.models import LabBase, LabProgress, LabUser
from shared.security import hash_password, verify_password

router = APIRouter(prefix="/lab")

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Role = Literal["learner", "admin"]


class SignupIn(BaseModel):
    email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)


class CredentialsIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class LabUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    role: str
    active: bool
    created_at: datetime
    last_login_at: datetime | None


class LabUserAdminOut(LabUserOut):
    lessons_completed: int


class UserUpdateIn(BaseModel):
    role: Role | None = None
    active: bool | None = None


class ProgressIn(BaseModel):
    lesson_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    lesson_id: str
    completed_at: datetime


async def get_session(request: Request):
    async with request.app.state.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


async def ensure_lab_schema(engine: AsyncEngine, settings: Settings) -> None:
    """Create the lab tables if missing, and the bootstrap admin from LAB_ADMIN_* if set."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: LabBase.metadata.create_all(c, checkfirst=True))
    email = settings.lab_admin_email.strip().lower()
    if not (email and settings.lab_admin_password):
        return
    async with AsyncSession(engine) as session:
        if await session.scalar(select(LabUser).where(LabUser.email == email)) is None:
            session.add(LabUser(email=email, full_name="Lab Admin", role="admin",
                                password_hash=hash_password(settings.lab_admin_password)))
            await session.commit()


async def _user(session: AsyncSession, user_id: int) -> LabUser:
    user = await session.get(LabUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/register", response_model=LabUserOut, status_code=201)
async def register(body: SignupIn, session: Session):
    full_name = body.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="Name is required")
    user = LabUser(email=body.email.strip().lower(), full_name=full_name,
                   password_hash=hash_password(body.password),
                   last_login_at=datetime.now(UTC).replace(tzinfo=None))  # sign-up signs you in
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409,
                            detail="An account with this email already exists") from None
    await session.refresh(user)
    return user


@router.post("/verify", response_model=LabUserOut)
async def verify(creds: CredentialsIn, session: Session):
    user = await session.scalar(select(LabUser).where(LabUser.email == creds.email.strip().lower()))
    if not user or not verify_password(creds.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.active:
        raise HTTPException(status_code=403, detail="This account has been disabled")
    user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/users", response_model=list[LabUserAdminOut])
async def list_users(session: Session):
    done = (select(LabProgress.user_id, func.count().label("n"))
            .group_by(LabProgress.user_id).subquery())
    stmt = (select(LabUser, func.coalesce(done.c.n, 0))
            .outerjoin(done, done.c.user_id == LabUser.id).order_by(LabUser.created_at.desc()))
    return [LabUserAdminOut(**LabUserOut.model_validate(u).model_dump(), lessons_completed=n)
            for u, n in (await session.execute(stmt)).all()]


@router.get("/users/{user_id}", response_model=LabUserOut)
async def get_user(user_id: int, session: Session):
    return await _user(session, user_id)


@router.patch("/users/{user_id}", response_model=LabUserOut)
async def update_user(user_id: int, body: UserUpdateIn, session: Session):
    user = await _user(session, user_id)
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/users/{user_id}/progress", response_model=list[ProgressOut])
async def get_progress(user_id: int, session: Session):
    await _user(session, user_id)
    stmt = (select(LabProgress).where(LabProgress.user_id == user_id)
            .order_by(LabProgress.completed_at))
    return list(await session.scalars(stmt))


@router.post("/users/{user_id}/progress", response_model=list[ProgressOut], status_code=201)
async def complete_lesson(user_id: int, body: ProgressIn, session: Session):
    """Idempotent: completing a lesson twice keeps the first completion time."""
    await _user(session, user_id)
    session.add(LabProgress(user_id=user_id, lesson_id=body.lesson_id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
    return await get_progress(user_id, session)
