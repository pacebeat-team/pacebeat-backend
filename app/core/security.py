from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID
import jwt
from jwt import PyJWKClient
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import Settings, get_settings
from app.core.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None


@lru_cache
def get_jwk_client(supabase_url: str) -> PyJWKClient:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url, cache_keys=True)


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
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        if alg == "HS256":
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            signing_key = get_jwk_client(settings.SUPABASE_URL).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                options={"verify_aud": False},
            )

        sub = payload.get("sub")
        if not sub:
            raise ValueError("Missing sub claim")
        return AuthenticatedUser(user_id=UUID(sub), email=payload.get("email"))
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_TOKEN_EXPIRED",
            message="인증 토큰이 만료되었습니다.",
        ) from exc
    except (jwt.PyJWTError, ValueError) as exc:
        # Q16 반영: 내부 예외 상세나 시크릿 정보를 응답에 노출하지 않음
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_INVALID_TOKEN",
            message="유효하지 않은 인증 토큰입니다.",
        ) from exc
