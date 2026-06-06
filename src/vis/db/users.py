from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..security.authz import seed_roles
from ..security.passwords import PasswordPolicy, hash_password, verify_password
from .models import Role, User, UserRole

MAX_FAILED_ATTEMPTS = 5


class AuthError(Exception):
    """Raised on failed authentication (bad credentials, locked, inactive)."""


def verify_user(session, user_id: int, password: str) -> bool:
    """Verify a user's password within an existing session (used for e-sign re-auth)."""
    user = session.get(User, user_id)
    return bool(user and verify_password(password, user.password_hash))


class UserService:
    """User lifecycle + authentication with lockout."""

    def __init__(self, session_factory, policy: PasswordPolicy | None = None) -> None:
        self._sf = session_factory
        self.policy = policy or PasswordPolicy()

    def seed_roles(self) -> None:
        with self._sf() as s:
            seed_roles(s)
            s.commit()

    def create_user(
        self, username: str, password: str, full_name: str = "", roles: tuple[str, ...] = ()
    ) -> int:
        self.policy.validate(password)
        with self._sf() as s:
            user = User(
                username=username,
                full_name=full_name,
                password_hash=hash_password(password),
                active=True,
            )
            s.add(user)
            s.flush()
            for role_name in roles:
                role = s.execute(select(Role).where(Role.name == role_name)).scalars().first()
                if role is None:
                    raise ValueError(f"unknown role {role_name!r}")
                s.add(UserRole(user_id=user.id, role_id=role.id))
            s.commit()
            return user.id

    def authenticate(self, username: str, password: str) -> int:
        with self._sf() as s:
            user = s.execute(select(User).where(User.username == username)).scalars().first()
            if user is None:
                raise AuthError("invalid credentials")
            if user.locked or not user.active:
                raise AuthError("account locked or inactive")
            if not verify_password(password, user.password_hash):
                user.failed_attempts += 1
                if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    user.locked = True
                s.commit()
                raise AuthError("invalid credentials")
            user.failed_attempts = 0
            user.last_login = datetime.now(timezone.utc).isoformat()
            s.commit()
            return user.id
