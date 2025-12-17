import jwt
from fastapi import HTTPException, status
from common.config import settings
from jwt import ExpiredSignatureError, InvalidTokenError

def get_user_from_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_email = payload.get('sub')
        user_id = payload.get('user_id')
        if not user_email and not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload.")
        return {'email': user_email, 'user_id': user_id}
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired.")
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
