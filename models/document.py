from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

class DocumentMetadata(BaseModel):
    id: str
    file_name: str
    size: str  # in bytes
    path: str
    content_type: str = "application/pdf"
    extension: str = "pdf"
    status: str = Field(default="pending")
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.now(timezone.utc))


class DocumentResponse(BaseModel):
    # id: str
    file_name: str
    content_type: str
    size: str
    extension: str
    status: str
    # created_at: Optional[str] = None

    
