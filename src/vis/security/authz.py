"""Role-based access control: permission codes, default roles, and checks."""

from __future__ import annotations

from sqlalchemy import select

from ..db.models import Role, UserRole


class Perm:
    RECIPE_CREATE = "recipe.create"
    RECIPE_APPROVE = "recipe.approve"
    BATCH_MANAGE = "batch.manage"
    STATION_MANAGE = "station.manage"  # configure hardware (cameras, reject outputs)
    USER_MANAGE = "user.manage"
    AUDIT_VIEW = "audit.view"


# Default role presets. Customers can adjust per their SOP.
DEFAULT_ROLES: dict[str, list[str]] = {
    "admin": [
        Perm.RECIPE_CREATE,
        Perm.RECIPE_APPROVE,
        Perm.BATCH_MANAGE,
        Perm.STATION_MANAGE,
        Perm.USER_MANAGE,
        Perm.AUDIT_VIEW,
    ],
    "qa_manager": [Perm.RECIPE_CREATE, Perm.RECIPE_APPROVE, Perm.BATCH_MANAGE, Perm.AUDIT_VIEW],
    "engineer": [Perm.RECIPE_CREATE, Perm.BATCH_MANAGE, Perm.STATION_MANAGE],
    "operator": [Perm.BATCH_MANAGE],
}


def seed_roles(session) -> None:
    """Create/update the default roles. Idempotent."""
    for name, perms in DEFAULT_ROLES.items():
        role = session.execute(select(Role).where(Role.name == name)).scalars().first()
        if role is None:
            session.add(Role(name=name, permissions=list(perms)))
        else:
            role.permissions = list(perms)
    session.flush()


def permissions_for(session, user_id: int) -> set[str]:
    role_ids = [
        ur.role_id
        for ur in session.execute(
            select(UserRole).where(UserRole.user_id == user_id)
        ).scalars()
    ]
    perms: set[str] = set()
    if role_ids:
        for role in session.execute(select(Role).where(Role.id.in_(role_ids))).scalars():
            perms.update(role.permissions or [])
    return perms


def has_permission(session, user_id: int, perm: str) -> bool:
    return perm in permissions_for(session, user_id)


def require(session, user_id: int | None, perm: str) -> None:
    if user_id is None or not has_permission(session, user_id, perm):
        raise PermissionError(f"user {user_id} lacks permission {perm!r}")
