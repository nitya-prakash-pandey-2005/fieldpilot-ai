from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, EmailStr

from db import get_db
from models.user import User, ROLES
from auth import hash_password, verify_password, create_access_token, get_current_user, CurrentUser

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "worker"
    zone_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {ROLES}")

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        role=req.role,
        zone_code=req.zone_code,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email, user.role)
    return TokenResponse(access_token=token, user=_user_dict(user))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(user.id, user.email, user.role)
    return TokenResponse(access_token=token, user=_user_dict(user))


@router.get("/me")
async def get_me(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == current.id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_dict(user)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "zone_code": user.zone_code,
    }
