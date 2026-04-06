from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from app.config import settings

pwd = CryptContext(schemes=['argon2', 'bcrypt'], deprecated='auto')

def hash_password(raw: str) -> str:
    return pwd.hash(raw)

def verify_password(raw: str, hashed: str) -> bool:
    return pwd.verify(raw, hashed)

def _encode_token(
    user_id: str,
    expires_delta: timedelta,
    token_type: str,
    token_id: str | None = None,
    *,
    scope: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    effective_scope = scope or token_type
    payload = {
        'sub': user_id,
        'iat': now,
        'exp': now + expires_delta,
        'type': token_type,
        'scope': effective_scope,
    }
    if token_id:
        payload['jti'] = token_id
    return jwt.encode(payload, settings.jwt_secret, algorithm='HS256')

def create_access_token(user_id: str) -> str:
    return _encode_token(
        user_id=user_id,
        expires_delta=timedelta(minutes=settings.jwt_expires_minutes),
        token_type='access',
        scope='access',
    )

def create_refresh_token(user_id: str, token_id: str) -> str:
    return _encode_token(
        user_id=user_id,
        expires_delta=timedelta(days=settings.refresh_token_expires_days),
        token_type='refresh',
        token_id=token_id,
        scope='refresh',
    )

def decode_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'])
    return payload
