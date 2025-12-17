import hashlib
import secrets
from passlib.context import CryptContext
from cryptography.fernet import Fernet, InvalidToken
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from typing import Optional, Any, Dict, List
from cryptography.fernet import Fernet

from common.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def generate_reset_token():
    token = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    return token, hashed_token


fernet = Fernet(settings.FERNET_KEY.encode() if isinstance(settings.FERNET_KEY, str) else settings.FERNET_KEY)

SENSITIVE_FIELDS = ["email", "phone_number", "date_of_birth", "gender", "patient name", "DOB", "full_name", "user_name"]
SEARCHABLE_FIELDS = ["email", "full_name"]

# --- encryption / decryption helpers ---
def _encrypt_value(value: Optional[str]) -> Optional[str]:
    return fernet.encrypt(value.encode()).decode() if value else value

def _decrypt_value(value: Optional[str]) -> Optional[str]:
    return fernet.decrypt(value.encode()).decode() if value else value

def _hash_email(email: Optional[str]) -> Optional[str]:
    return hashlib.sha256(email.encode()).hexdigest() if email else None


# --- process helpers ---
def _process_encrypt(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc

    # Compute searchable hashes first
    for field in SEARCHABLE_FIELDS:
        if field in doc and doc[field]:
            doc[f"{field}_hash"] = _hash_email(doc[field])

    # Encrypt sensitive fields recursively
    def _encrypt_recursive(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(v, dict):
                    out[k] = _encrypt_recursive(v)
                elif isinstance(v, list):
                    out[k] = [_encrypt_recursive(x) if isinstance(x, dict) else x for x in v]
                elif k in SENSITIVE_FIELDS and v:
                    out[k] = _encrypt_value(v)
                else:
                    out[k] = v
            return out
        return obj

    return _encrypt_recursive(doc)

def _process_decrypt(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc

    def _decrypt_recursive(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(v, dict):
                    out[k] = _decrypt_recursive(v)
                elif isinstance(v, list):
                    out[k] = [_decrypt_recursive(x) if isinstance(x, dict) else x for x in v]
                elif k in SENSITIVE_FIELDS and isinstance(v, str):
                    try:
                        out[k] = _decrypt_value(v)
                    except Exception:
                        out[k] = v
                else:
                    out[k] = v
            return out
        return obj

    return _decrypt_recursive(doc)


# --- Encrypted collection wrapper ---
class EncryptedCollection:
    def __init__(self, collection: AsyncIOMotorCollection):
        self.collection = collection

    async def insert_one(self, doc: Dict[str, Any], *args, **kwargs):
        prepared = _process_encrypt(doc.copy())
        return await self.collection.insert_one(prepared, *args, **kwargs)

    async def insert_many(self, docs: List[Dict[str, Any]], *args, **kwargs):
        prepared_list = [_process_encrypt(d.copy()) for d in docs]
        return await self.collection.insert_many(prepared_list, *args, **kwargs)

    async def find_one(self, filter: Optional[Dict[str, Any]] = None, *args, **kwargs):
        if filter and "email" in filter:
            email = filter.pop("email")
            filter["email_hash"] = _hash_email(email)
        doc = await self.collection.find_one(filter, *args, **kwargs)
        return _process_decrypt(doc)

    async def find(self, filter: Optional[Dict[str, Any]] = None, *args, **kwargs):
        if filter and "email" in filter:
            email = filter.pop("email")
            filter["email_hash"] = _hash_email(email)
        cursor = self.collection.find(filter, *args, **kwargs)
        docs = await cursor.to_list(length=None)
        return [_process_decrypt(d) for d in docs]

    async def update_one(self, filter: Dict[str, Any], update: Dict[str, Any], *args, **kwargs):
        if filter and "email" in filter:
            email = filter.pop("email")
            filter["email_hash"] = _hash_email(email)
        if "$set" in update:
            update_copy = update.copy()
            update_copy["$set"] = _process_encrypt(update_copy["$set"])
            update = update_copy
        return await self.collection.update_one(filter, update, *args, **kwargs)

    async def aggregate(self, pipeline: List[Dict[str, Any]], *args, **kwargs):
        # convert $match on email to email_hash
        def _convert_pipeline(p):
            new_pipeline = []
            for stage in p:
                if isinstance(stage, dict) and "$match" in stage and isinstance(stage["$match"], dict):
                    match = stage["$match"].copy()
                    if "email" in match and isinstance(match["email"], str):
                        val = match.pop("email")
                        match["email_hash"] = _hash_email(val)
                    new_pipeline.append({"$match": match})
                else:
                    new_pipeline.append(stage)
            return new_pipeline

        pipeline = _convert_pipeline(pipeline)
        cursor = self.collection.aggregate(pipeline, *args, **kwargs)
        docs = await cursor.to_list(length=None)
        return [_process_decrypt(d) for d in docs]

    def __getattr__(self, item):
        return getattr(self.collection, item)


# --- Encrypted database wrapper ---
class EncryptedDatabase:
    def __init__(self, db: AsyncIOMotorDatabase, encrypted_collections=None):
        self._db = db
        self._collections: Dict[str, Any] = {}
        self._encrypted_collections = encrypted_collections or []

    def __getitem__(self, name: str):
        if name not in self._collections:
            if name in self._encrypted_collections:
                self._collections[name] = EncryptedCollection(self._db[name])
            else:
                self._collections[name] = self._db[name]
        return self._collections[name]

    def __getattr__(self, name: str):
        # Protect private attributes (e.g., _db, _collections)
        if name.startswith("_"):
            raise AttributeError(name)

        # Always treat attribute access as collection access
        return self.__getitem__(name)
