from pydantic import BaseModel, EmailStr, Field


class LeadSubscribeRequest(BaseModel):
    email: EmailStr
    source: str = Field(default="landing")
