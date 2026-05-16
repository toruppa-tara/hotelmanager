from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request, HTTPException, status

SECRET_KEY = "hotel_manager_secret_key_CHANGE_THIS_IN_PRODUCTION_2024"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user_from_cookie(request: Request) -> Optional[dict]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_token(token)


def require_login(request: Request) -> dict:
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return user


def require_owner(request: Request) -> dict:
    user = require_login(request)
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="เฉพาะเจ้าของเท่านั้น")
    return user


def require_owner_or_manager(request: Request) -> dict:
    user = require_login(request)
    if user.get("role") not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึง")
    return user
