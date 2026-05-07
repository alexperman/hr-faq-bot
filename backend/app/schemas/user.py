from pydantic import BaseModel, EmailStr, field_validator, ConfigDict


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company_name: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("full_name")
    @classmethod
    def full_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Full name cannot be empty")
        return v.strip()

    @field_validator("company_name")
    @classmethod
    def company_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Company name cannot be empty")
        return v.strip()


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int
    tenant_slug: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_owner: bool
    tenant_slug: str

    model_config = ConfigDict(from_attributes=True)
