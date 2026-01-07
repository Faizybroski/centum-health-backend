# from datetime import datetime
# from pydantic import GetJsonSchemaHandler
# from pydantic.json_schema import JsonSchemaValue
# from typing import Any, Optional, List
# from pydantic import BaseModel, Field
# from bson import ObjectId
from enum import Enum


# # ---------- Mongo ObjectId Helper ----------
# class PyObjectId(ObjectId):
#     @classmethod
#     def __get_pydantic_json_schema__(
#         cls,
#         core_schema: Any,
#         handler: GetJsonSchemaHandler,
#     ) -> JsonSchemaValue:
#         return {
#             "type": "string",
#             "examples": ["507f1f77bcf86cd799439011"],
#         }

#     @classmethod
#     def __get_validators__(cls):
#         yield cls.validate

#     @classmethod
#     def validate(cls, v):
#         if isinstance(v, ObjectId):
#             return v
#         if not ObjectId.is_valid(v):
#             raise ValueError("Invalid ObjectId")
#         return ObjectId(v)
    
    
# # ---------- FAQ Status Enum ----------
# class FAQStatus(str, Enum):
#     draft = "draft"
#     saved = "saved"
    

# # ---------- Base Schema ----------
# class FAQBase(BaseModel):
#     category: str = Field(..., example="General")
#     question: str = Field(..., example="What is Centum?")
#     answer: str = Field(..., example="Centum is a personalized health tracking platform.")
#     status: FAQStatus = Field(default=FAQStatus.draft)

    
# # ---------- Admin Create ----------
# class FAQCreate(FAQBase):
#     pass


# # ---------- Admin Update ----------
# class FAQUpdate(BaseModel):
#     category: Optional[str]
#     question: Optional[str]
#     answer: Optional[str]
#     status: Optional[FAQStatus] = None
#     updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


# # ---------- DB Model ----------
# class FAQInDB(FAQBase):
#     id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
#     created_at: datetime = Field(default_factory=datetime.utcnow)
#     updated_at: datetime = Field(default_factory=datetime.utcnow)
#     is_active: bool = True  # soft delete ready

#     class Config:
#         allow_population_by_field_name = True
#         arbitrary_types_allowed = True
#         json_encoders = {ObjectId: str}


# # ---------- Public Response ----------
# class FAQPublicResponse(BaseModel):
#     id: str
#     category: str
#     question: str
#     answer: str

#     class Config:
#         orm_mode = True

# class FAQCategoryResponse(BaseModel):
#     category: str
#     faqs: List[FAQPublicResponse]
        
        
# # ---------- Admin Response ----------
# class FAQResponse(FAQBase):
#     id: str
#     category: str

#     class Config:
#         orm_mode = True


# # ---------- Category-wise Response ----------
# class FAQCategoryResponse(BaseModel):
#     category: str
#     faqs: List[FAQPublicResponse]



from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class FAQBase(BaseModel):
    question: str
    answer: str
    category: str
    tags: Optional[List[str]] = []
    order: Optional[int] = 0

class FAQCreate(FAQBase):
    status: Optional[str] = "draft"

class FAQUpdate(FAQBase):
    status: Optional[str]
    
class FAQStatus(str, Enum):
    draft = "draft"
    saved = "saved"

class FAQResponse(FAQBase):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime]
