import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from app.database import get_db
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
_serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def decode_session_token(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=60 * 60 * 24 * 7)  # 7 días
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    data = decode_session_token(token)
    if not data:
        return None
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (data["user_id"],)
    ).fetchone()
    conn.close()
    return user


def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request):
    user = require_login(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Solo el admin puede hacer esto")
    return user
