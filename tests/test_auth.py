import pytest

from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.users import AuthError, UserService, verify_user
from vis.security.authz import Perm, has_permission, require
from vis.security.passwords import PasswordPolicy, hash_password, verify_password


def _sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    return make_session_factory(engine)


def test_password_hash_roundtrip_and_salted():
    h = hash_password("Secret123")
    assert verify_password("Secret123", h)
    assert not verify_password("wrong", h)
    assert h != hash_password("Secret123")  # unique salt each time


def test_policy_rejects_weak_passwords():
    policy = PasswordPolicy()
    with pytest.raises(ValueError):
        policy.validate("short")
    with pytest.raises(ValueError):
        policy.validate("alphabetsonly")  # no digit
    policy.validate("Secret123")  # ok


def test_authenticate_and_permissions(tmp_path):
    sf = _sf(tmp_path)
    users = UserService(sf)
    users.seed_roles()
    uid = users.create_user("qa", "Secret123", roles=("qa_manager",))

    assert users.authenticate("qa", "Secret123") == uid
    with pytest.raises(AuthError):
        users.authenticate("qa", "nope")

    with sf() as s:
        assert has_permission(s, uid, Perm.RECIPE_APPROVE)
        assert not has_permission(s, uid, Perm.USER_MANAGE)
        require(s, uid, Perm.RECIPE_APPROVE)
        with pytest.raises(PermissionError):
            require(s, uid, Perm.USER_MANAGE)
        assert verify_user(s, uid, "Secret123")


def test_role_rights_management_and_copy(tmp_path):
    sf = _sf(tmp_path)
    users = UserService(sf)
    users.seed_roles()
    admin = users.create_user("adm", "Secret123", roles=("admin",))
    op = users.create_user("op", "Secret123", roles=("operator",))

    # a plain operator (no USER_MANAGE) cannot manage roles
    with pytest.raises(PermissionError):
        users.set_role_permissions(op, "operator", [Perm.USER_MANAGE])

    # create a role, grant a right, assign it to a user -> permission takes effect
    users.create_role(admin, "line_lead")
    users.set_role_permissions(admin, "line_lead", [Perm.RECIPE_CREATE, Perm.AUDIT_VIEW])
    users.set_roles(admin, op, ("line_lead",))
    with sf() as s:
        assert has_permission(s, op, Perm.RECIPE_CREATE)
        assert not has_permission(s, op, Perm.STATION_MANAGE)

    # copy rights from admin onto line_lead -> now has the full admin set
    users.copy_role_permissions(admin, "admin", "line_lead")
    with sf() as s:
        assert has_permission(s, op, Perm.STATION_MANAGE)

    # delete unassigns from users
    users.set_roles(admin, op, ("operator",))
    users.delete_role(admin, "line_lead")
    assert "line_lead" not in users.list_roles()


def test_admin_create_user_stores_email_phone(tmp_path):
    sf = _sf(tmp_path)
    users = UserService(sf)
    users.seed_roles()
    admin = users.create_user("adm", "Secret123", roles=("admin",))
    users.admin_create_user(admin, "jane", "Secret123", "Jane Q", ("operator",),
                            email="jane@x.com", phone="555-1")
    jane = next(u for u in users.list_users() if u["username"] == "jane")
    assert jane["email"] == "jane@x.com" and jane["phone"] == "555-1"


def test_account_lockout_after_repeated_failures(tmp_path):
    sf = _sf(tmp_path)
    users = UserService(sf)
    users.seed_roles()
    users.create_user("op", "Secret123", roles=("operator",))

    for _ in range(5):
        with pytest.raises(AuthError):
            users.authenticate("op", "bad")
    # now locked even with the correct password
    with pytest.raises(AuthError):
        users.authenticate("op", "Secret123")
