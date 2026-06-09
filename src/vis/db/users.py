from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..security.authz import Perm, require, seed_roles
from ..security.passwords import PasswordPolicy, hash_password, verify_password
from .audit import AuditService
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

    # --- management (RBAC user.manage + audited) ----------------------------
    def list_roles(self) -> list[str]:
        with self._sf() as s:
            return [r.name for r in s.execute(select(Role).order_by(Role.name)).scalars()]

    def _roles_of(self, s, user_id: int) -> list[str]:
        rows = s.execute(select(UserRole).where(UserRole.user_id == user_id)).scalars().all()
        names = []
        for ur in rows:
            role = s.get(Role, ur.role_id)
            if role:
                names.append(role.name)
        return names

    def list_users(self) -> list[dict]:
        with self._sf() as s:
            out = []
            for u in s.execute(select(User).order_by(User.username)).scalars():
                out.append({
                    "id": u.id, "username": u.username, "full_name": u.full_name,
                    "active": u.active, "locked": u.locked, "last_login": u.last_login,
                    "roles": self._roles_of(s, u.id),
                })
            return out

    def admin_create_user(self, by_user: int, username: str, password: str,
                          full_name: str = "", roles: tuple[str, ...] = ()) -> int:
        self.policy.validate(password)
        with self._sf() as s:
            require(s, by_user, Perm.USER_MANAGE)
            user = User(username=username, full_name=full_name,
                        password_hash=hash_password(password), active=True)
            s.add(user)
            s.flush()
            self._apply_roles(s, user.id, roles)
            AuditService(s).record("user.create", "user", user.id, user_id=by_user,
                                   after={"username": username, "roles": list(roles)})
            s.commit()
            return user.id

    def _apply_roles(self, s, user_id: int, roles) -> None:
        for ur in s.execute(select(UserRole).where(UserRole.user_id == user_id)).scalars().all():
            s.delete(ur)
        for role_name in roles:
            role = s.execute(select(Role).where(Role.name == role_name)).scalars().first()
            if role is None:
                raise ValueError(f"unknown role {role_name!r}")
            s.add(UserRole(user_id=user_id, role_id=role.id))

    def set_roles(self, by_user: int, user_id: int, roles: tuple[str, ...]) -> None:
        with self._sf() as s:
            require(s, by_user, Perm.USER_MANAGE)
            before = self._roles_of(s, user_id)
            self._apply_roles(s, user_id, roles)
            AuditService(s).record("user.roles", "user", user_id, user_id=by_user,
                                   before={"roles": before}, after={"roles": list(roles)})
            s.commit()

    def set_active(self, by_user: int, user_id: int, active: bool) -> None:
        with self._sf() as s:
            require(s, by_user, Perm.USER_MANAGE)
            user = s.get(User, user_id)
            if user is None:
                raise ValueError(f"user {user_id} not found")
            user.active = active
            if active:
                user.locked = False
                user.failed_attempts = 0
            AuditService(s).record("user.active", "user", user_id, user_id=by_user,
                                   after={"active": active})
            s.commit()

    def reset_password(self, by_user: int, user_id: int, new_password: str) -> None:
        self.policy.validate(new_password)
        with self._sf() as s:
            require(s, by_user, Perm.USER_MANAGE)
            user = s.get(User, user_id)
            if user is None:
                raise ValueError(f"user {user_id} not found")
            user.password_hash = hash_password(new_password)
            user.locked = False
            user.failed_attempts = 0
            AuditService(s).record("user.password_reset", "user", user_id, user_id=by_user)
            s.commit()

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
