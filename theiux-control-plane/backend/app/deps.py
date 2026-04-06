from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.auth import decode_token
from app.db import get_db
from app.errors import raise_api_error
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/v1/auth/login', auto_error=False)

ROLE_ORDER = {'viewer': 0, 'admin': 1, 'owner': 2}


def current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    raw_token = token or request.cookies.get('access_token')
    if not raw_token:
        raise HTTPException(status_code=401, detail='missing token')
    try:
        payload = decode_token(raw_token)
        effective = payload.get('scope') or payload.get('type')
        if str(effective) != 'access':
            raise HTTPException(status_code=401, detail='invalid token scope')
        user_id = str(payload['sub'])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail='invalid token') from exc
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail='user not found')
    return user


def require_min_role(min_role: Literal['viewer', 'admin', 'owner']):
    def _dep(user: User = Depends(current_user)) -> User:
        r = (user.role or 'viewer').lower()
        if r not in ROLE_ORDER:
            r = 'viewer'
        if ROLE_ORDER[r] < ROLE_ORDER[min_role]:
            raise_api_error(
                status_code=403,
                code='forbidden',
                message='insufficient role',
                category='auth_error',
                details={'required': min_role, 'role': r},
            )
        return user

    return _dep
