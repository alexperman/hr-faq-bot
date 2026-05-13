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


    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    token = create_access_token(data={"user_id": user.id, "tenant_slug": slug})
    return Token(access_token=token, tenant_slug=slug)


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
    return Token(access_token=token, tenant_slug=tenant.slug)


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


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None


class UpdateTenantRequest(BaseModel):
    name: str | None = None
    slug: str | None = None


class TenantOut(BaseModel):
    id: int
    slug: str
    name: str
    is_active: bool


@router.patch("/me")
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile (name, email)."""
    if data.full_name is not None:
        current_user.full_name = data.full_name.strip()
    if data.email is not None:
        existing = await db.execute(select(User).where(User.email == data.email, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")
        current_user.email = data.email
    await db.commit()
    await db.refresh(current_user)
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one()
    return UserOut(id=current_user.id, email=current_user.email, full_name=current_user.full_name, is_owner=current_user.is_owner, tenant_slug=tenant.slug)


@router.get("/tenant", response_model=TenantOut)
async def get_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's tenant details."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one()
    return TenantOut(id=tenant.id, slug=tenant.slug, name=tenant.name, is_active=tenant.is_active)


@router.patch("/tenant")
async def update_tenant(
    data: UpdateTenantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update tenant settings (owner only)."""
    if not current_user.is_owner:
        raise HTTPException(status_code=403, detail="Only owners can update workspace settings")

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one()

    if data.name is not None:
        tenant.name = data.name.strip()
    if data.slug is not None:
        new_slug = re.sub(r'[^a-z0-9]+', '-', data.slug.lower()).strip('-')
        if new_slug and new_slug != tenant.slug:
            existing = await db.execute(select(Tenant).where(Tenant.slug == new_slug, Tenant.id != tenant.id))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Workspace URL already taken")
            tenant.slug = new_slug

    await db.commit()
    await db.refresh(tenant)
    return TenantOut(id=tenant.id, slug=tenant.slug, name=tenant.name, is_active=tenant.is_active)


class TeamMemberOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_owner: bool
    is_active: bool
    created_at: str
    pending_escalations: int = 0


@router.get("/team")
async def list_team(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all team members in the tenant (owner only)."""
    if not current_user.is_owner:
        raise HTTPException(status_code=403, detail="Only owners can view team")

    from app.models import Escalation
    from sqlalchemy import func

    result = await db.execute(
        select(User).where(User.tenant_id == current_user.tenant_id).order_by(User.created_at)
    )
    users = result.scalars().all()

    # Get pending escalation counts per user
    esc_counts_result = await db.execute(
        select(Escalation.user_id, func.count(Escalation.id))
        .where(Escalation.tenant_id == current_user.tenant_id, Escalation.status == "pending")
        .group_by(Escalation.user_id)
    )
    esc_counts = dict(esc_counts_result.all())

    return [
        TeamMemberOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_owner=u.is_owner,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
            pending_escalations=esc_counts.get(u.id, 0),
        )
        for u in users
    ]


class SetAdminRequest(BaseModel):
    is_owner: bool


@router.patch("/team/{user_id}/role")
async def set_user_role(
    user_id: int,
    data: SetAdminRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Promote or demote a team member (owner only)."""
    if not current_user.is_owner:
        raise HTTPException(status_code=403, detail="Only owners can change roles")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_owner = data.is_owner
    await db.commit()
    return {"id": user.id, "email": user.email, "is_owner": user.is_owner}
