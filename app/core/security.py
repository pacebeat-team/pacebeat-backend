from dataclasses import dataclass
from uuid import UUID
import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import Settings, get_settings
from app.core.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_MISSING_TOKEN",
            message="인증 토큰이 필요합니다.",
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError("Missing sub claim")
        return AuthenticatedUser(user_id=UUID(sub), email=payload.get("email"))
    except (jwt.PyJWTError, ValueError) as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_INVALID_TOKEN",
            message=f"유효하지 않거나 만료된 토큰입니다: {exc}",
        ) from exc
