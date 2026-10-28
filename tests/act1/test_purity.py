from pathlib import Path

from import_rules import impure_imports

ACT1 = Path(__file__).resolve().parents[2] / "src" / "symbiont" / "act1"
PURE_FILES = (
    "env_text.py",
    "moves.py",
    "goto.py",
    "strategy.py",
    "navtypes.py",
    "navbuild.py",
    "navgrid.py",
    "navsearch.py",
    "navroute.py",
    "navdiagnose.py",
    "navmap.py",
    "levels.py",
    "rooms.py",
    "steplog.py",
    "game_pains.py",
    "episode_records.py",
    "policies.py",
    "game_lessons.py",
    "lesson_rows.py",
)


def test_pure_act1_modules_import_no_network_clock_or_vizdoom():
    for name in PURE_FILES:
        source = (ACT1 / name).read_text()
        assert impure_imports(source) == [], name
        assert "import vizdoom" not in source and "from vizdoom" not in source, name
