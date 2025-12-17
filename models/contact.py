from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import enum

class SubscriptionType(str, enum.Enum):
    CORE = "core"
    PLUS = "plus"
    PRIME = "prime"


class SubscribeSchema(BaseModel):
    email: EmailStr


class ContactUsSchema(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    phone: Optional[str] = None
    subject: str
    message: str


class WaitlistSchema(BaseModel):
    email: EmailStr
    subscription_type: SubscriptionType