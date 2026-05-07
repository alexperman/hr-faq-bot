import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User, Tenant, Subscription
from app.schemas import UserCreate, UserLogin, Token, UserOut
from app.services.auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def slugify(name: str) -> str:
    """Convert company name to URL-safe slug."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug


class InviteRequest(BaseModel):
    email: EmailStr


class InviteResponse(BaseModel):
    message: str
    temp_password: str


class RegisterWithInviteRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    invite_token: str  # tenant slug as invite token for now


@router.post("/register", response_model=Token)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Create tenant
    slug = slugify(data.company_name)
    tenant = Tenant(name=data.company_name, slug=slug)
    db.add(tenant)
    await db.flush()

    # Create user (owner)
    password_hash = hash_password(data.password)
    user = User(
        email=data.email,
        password_hash=password_hash,
        full_name=data.full_name,
        tenant_id=tenant.id,
        is_owner=True,
    )
    db.add(user)

    # Create pending subscription
    subscription = Subscription(tenant_id=tenant.id, status="pending")
    db.add(subscription)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    token = create_access_token(data={"user_id": user.id, "tenant_slug": slug})
    return Token(access_token=token)


@router.post("/invite", response_model=InviteResponse)
async def invite_user(
    request: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Invite a team member to the tenant organization.
    Only owners can invite. Creates the user with a temp password and returns it.
    """
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owners can invite team members")

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409, detail="User already registered")

    # Generate temp password
    import secrets
    import string
    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

    # Create user under same tenant
    password_hash = hash_password(temp_password)
    new_user = User(
        email=request.email,
        password_hash=password_hash,
        full_name=request.email.split("@")[0],  # placeholder, they can update
        tenant_id=current_user.tenant_id,
        is_owner=False,
    )
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    return InviteResponse(
        message=f"Invitation sent to {request.email}",
        temp_password=temp_password,
    )


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_result.scalar_one()

    token = create_access_token(data={"user_id": user.id, "tenant_slug": tenant.slug})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one()
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_owner=current_user.is_owner,
        tenant_slug=tenant.slug,
    )
