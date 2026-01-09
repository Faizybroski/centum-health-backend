from pydantic import BaseModel, EmailStr, Field, field_validator
from models.objectid import PyObjectId
from typing import Optional, Literal
import re

class UserBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    date_of_birth: str
    gender: Literal['Male', 'Female', 'Non-binary', 'Prefer not to say', 'Other']
    email: EmailStr
    phone_number: str = Field(..., min_length=10, max_length=15)
    preferred_language: Optional[str] = ""
    emergency_contact_name: Optional[str] = ""
    emergency_contact_phone: Optional[str] = ""

    @field_validator('phone_number')
    @classmethod
    def validate_phone(cls, v):
        if not re.fullmatch(r'\+?\d{10,15}', v):
            raise ValueError('Phone number must be 10-15 digits, optionally starting with +')
        return v

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        if not re.search(r'[^A-Za-z0-9]', v):
            raise ValueError('Password must contain at least one special character')
        return v


class UserInDB(UserBase):
    id: Optional[PyObjectId]
    hashed_password: str
    is_active: bool = False
    is_verified: bool = False
    verification_token: Optional[str]
    reset_token: Optional[str]


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = ""
    date_of_birth: Optional[str] = ""
    gender: Optional[Literal['Male', 'Female', 'Non-binary', 'Prefer not to say', 'Other']] = ""
    phone_number: Optional[str] = ""
    individual_reference_number: str
    madicare_card_number: str
    madicare_expiry_date: str

class ForgotPassword(BaseModel):
    email: EmailStr
    

class ResetPassword(BaseModel):
    token: str
    new_password: str
    
class ChangePasswordSchema(BaseModel):
    current_password: str = Field(..., min_length=8)
    new_password: str = Field(..., min_length=8)
    confirm_new_password: str = Field(..., min_length=8)