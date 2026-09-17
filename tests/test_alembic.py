from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_tree_has_a_real_baseline() -> None:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == ["0001_baseline"]
    revision = script.get_revision("0001_baseline")
    assert revision is not None
    assert revision.down_revision is None
