from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
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


# class WaitlistSchema(BaseModel):
#     email: EmailStr
#     subscription_type: SubscriptionType
    
class WaitlistSchema(BaseModel):
    email: EmailStr
    subscription_type: SubscriptionType

    health_goal: str

    features: list[str]
    pricing_expectation: str
    current_tracking: str

    biggest_challenge: str

    interview_interest: bool
    
class WaitlistResponseSchema(BaseModel):
    id: str = Field(alias="_id")
    email: EmailStr
    subscription_type: SubscriptionType
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True