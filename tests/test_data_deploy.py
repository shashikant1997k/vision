from vis.cli import build_code_demo_recipe
from vis.db.backup import backup_database, restore_database
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.recipe_io import export_recipe, import_recipe, recipe_to_dict, dict_to_recipe
from vis.db.store import RecipeRepository
from vis.db.users import UserService
from vis.domain.entities import Fixture


def _setup(tmp_path, name="t.db"):
    engine = make_engine(f"sqlite:///{tmp_path}/{name}")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    return engine, sf, qa


def test_recipe_dict_roundtrip_preserves_everything():
    recipe = build_code_demo_recipe()
    recipe.image_rotation = 90
    recipe.regions[0].fixture = Fixture(template=b"PNGBYTES", anchor_x=5, anchor_y=6)
    back = dict_to_recipe(recipe_to_dict(recipe))
    assert back.image_rotation == 90
    assert back.regions[0].fixture.template == b"PNGBYTES"
    assert [t.tool_type for t in back.regions[0].tools] == [t.tool_type for t in recipe.regions[0].tools]


def test_export_then_import_recipe(tmp_path):
    _engine, sf, qa = _setup(tmp_path)
    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=qa)
    repo.approve(rid, qa, "Secret123", "released")

    path = str(tmp_path / "recipe.json")
    export_recipe(sf, rid, path)
    new_id = import_recipe(sf, path, user_id=qa)  # imports as a fresh draft
    assert new_id != rid
    loaded = repo.load(new_id)
    assert loaded.regions[0].tools[0].config.get("expected_data")


def test_database_backup_and_restore(tmp_path):
    engine, sf, qa = _setup(tmp_path)
    rid = RecipeRepository(sf).save_draft(build_code_demo_recipe(), user_id=qa)
    backup = str(tmp_path / "backup.db")
    backup_database(engine, backup)

    # delete the recipe, then restore from backup -> it's back
    with sf() as s:
        from vis.db.models import Recipe as RecipeRow

        s.delete(s.get(RecipeRow, rid))
        s.commit()
    restore_database(engine, backup)
    engine2 = make_engine(str(engine.url))
    sf2 = make_session_factory(engine2)
    from vis.db.models import Recipe as RecipeRow

    with sf2() as s:
        assert s.get(RecipeRow, rid) is not None
