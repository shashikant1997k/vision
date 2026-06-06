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
