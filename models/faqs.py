from datetime import datetime
from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from typing import Any, Optional, List
from pydantic import BaseModel, Field
from bson import ObjectId


# ---------- Mongo ObjectId Helper ----------
class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: Any,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return {
            "type": "string",
            "examples": ["507f1f77bcf86cd799439011"],
        }

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


# ---------- Base Schema ----------
class FAQBase(BaseModel):
    category: str = Field(..., example="General")
    question: str = Field(..., example="What is Centum?")
    answer: str = Field(..., example="Centum is a personalized health tracking platform.")


# ---------- Admin Create ----------
class FAQCreate(FAQBase):
    pass


# ---------- Admin Update ----------
class FAQUpdate(BaseModel):
    category: Optional[str]
    question: Optional[str]
    answer: Optional[str]
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


# ---------- DB Model ----------
class FAQInDB(FAQBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True  # soft delete ready

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


# ---------- Public Response ----------
class FAQResponse(FAQBase):
    id: str
    category: str

    class Config:
        orm_mode = True


# ---------- Category-wise Response ----------
class FAQCategoryResponse(BaseModel):
    category: str
    faqs: List[FAQResponse]