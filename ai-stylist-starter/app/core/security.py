from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


# bcrypt hard-limits passwords at 72 bytes (after UTF-8 encoding). We
# surface this as a clean ValueError so the route layer can return a
# 422/400 instead of the backend exploding. The SignupIn schema also
# caps password length to stay comfortably under the limit.
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Raised when a bearer token cannot be decoded or is expired."""


def _encode_password(password: str) -> bytes:
    data = password.encode("utf-8")
    if len(data) > _BCRYPT_MAX_BYTES:
        raise ValueError(
            f"password is {len(data)} bytes; bcrypt supports up to {_BCRYPT_MAX_BYTES}"
        )
    return data


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_encode_password(password), password_hash.encode("ascii"))
    except ValueError:
        # Over-length password, or malformed stored hash. Either way:
        # cannot authenticate → False. Don't leak which case it is.
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a bearer token. Raises ``TokenError`` on any issue.

    Returns the decoded payload dict (`sub`, `exp`, ...). Callers are
    responsible for interpreting `sub` (it is a stringified user_id).
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError(str(exc)) from exc
