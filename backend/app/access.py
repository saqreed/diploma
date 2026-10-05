"""Server-enforced sessions and role checks, independent of the frontend."""
import hmac

from fastapi import Request
from sqlalchemy import select

from app.decisions import DomainError, db_time
from app.models import Account, Application, LoginSession
from app.runtime import antifraud_sessions
from app.security import digest


async def user(request: Request):
    authorization = request.headers.get("authorization", "")
    bearer = authorization.startswith("Bearer ")
    token = authorization[7:] if bearer else request.cookies.get("antifraud_session")
    if not token:
        raise DomainError("unauthorized", "Войдите в систему", 401)
    request.state.session_token_hash = digest(token)
    if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-requested-with") != "antifraud-ui":
        raise DomainError("csrf", "Обновите страницу и повторите действие", 403)
    async with antifraud_sessions()() as session:
        login = await session.get(LoginSession, digest(token))
        if not login or login.expires_at <= await db_time(session):
            raise DomainError("session_expired", "Сеанс завершён. Войдите снова", 401)
        account = await session.get(Account, login.account_id)
        if account is None:
            raise DomainError("session_expired", "Аккаунт недоступен. Войдите снова", 401)
        return account


def require(account, *roles):
    if account.role not in roles:
        raise DomainError("forbidden", "Для этого действия недостаточно прав", 403)


async def application_access(session, application_id, key):
    application = await session.get(Application, application_id)
    if not application or not key or not hmac.compare_digest(application.api_key_hash, digest(key)):
        raise DomainError("application_unauthorized", "Не удалось подтвердить подключённое приложение", 401)
    return application
