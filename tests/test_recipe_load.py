import pytest

from vis.cli import build_code_demo_recipe
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.store import RecipeRepository
from vis.db.users import UserService


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa_id = users.create_user("qa", "Secret123", roles=("qa_manager",))
    return sf, qa_id


def test_list_and_load_approved_recipe(tmp_path):
    sf, qa_id = _setup(tmp_path)
    repo = RecipeRepository(sf)
    original = build_code_demo_recipe()
    rid = repo.save_draft(original, user_id=qa_id)

    # not approved yet -> not listed
    assert repo.list_approved() == []

    repo.approve(rid, qa_id, "Secret123", "released")
    approved = repo.list_approved()
    assert len(approved) == 1 and approved[0][0] == rid

    loaded = repo.load(rid)
    assert len(loaded.regions) == len(original.regions)
    assert loaded.regions[0].roi.w == original.regions[0].roi.w
    assert [t.tool_type for t in loaded.regions[0].tools] == [
        t.tool_type for t in original.regions[0].tools
    ]
    # tool config (expected_data) survives the round trip
    code_tool = loaded.regions[0].tools[0]
    assert code_tool.config.get("expected_data")


def test_load_preserves_image_rotation(tmp_path):
    sf, qa_id = _setup(tmp_path)
    repo = RecipeRepository(sf)
    recipe = build_code_demo_recipe()
    recipe.image_rotation = 90
    rid = repo.save_draft(recipe, user_id=qa_id)
    repo.approve(rid, qa_id, "Secret123", "released")
    assert repo.load(rid).image_rotation == 90


def test_load_missing_recipe_raises(tmp_path):
    sf, _ = _setup(tmp_path)
    with pytest.raises(ValueError):
        RecipeRepository(sf).load(999)
