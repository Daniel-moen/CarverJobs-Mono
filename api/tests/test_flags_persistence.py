"""Feature-flag persistence — a kill-switch must survive a deploy.

The flags used to live in memory only, so switching the paid Apify scraper off
lasted until the next restart and then silently switched itself back on.
"""
import json

import pytest

from app import flags


@pytest.fixture(autouse=True)
def _isolated_flag_file(tmp_path, monkeypatch):
    """Point the module at a throwaway file and restore defaults afterwards."""
    path = tmp_path / "flags.json"
    monkeypatch.setenv("CARVER_FLAGS_PATH", str(path))
    flags.reload_from_disk()
    yield path
    with flags._lock:
        flags._flags.clear()
        flags._flags.update(flags._DEFAULTS)


def test_defaults_are_all_on(_isolated_flag_file):
    assert all(flags.get_all().values())


def test_set_flag_writes_the_file(_isolated_flag_file):
    assert flags.set_flag("scraper", False) is True

    stored = json.loads(_isolated_flag_file.read_text())
    assert stored["scraper"] is False


def test_flag_off_survives_a_restart(_isolated_flag_file):
    flags.set_flag("scraper", False)

    # Simulate a process restart: in-memory state is rebuilt from defaults + disk.
    restored = flags.reload_from_disk()

    assert restored["scraper"] is False
    assert flags.is_enabled("scraper") is False
    assert flags.is_enabled("whatsapp") is True, "untouched flags stay on"


def test_flag_back_on_also_survives(_isolated_flag_file):
    flags.set_flag("scraper", False)
    flags.set_flag("scraper", True)

    assert flags.reload_from_disk()["scraper"] is True


def test_unknown_key_is_rejected_and_not_persisted(_isolated_flag_file):
    assert flags.set_flag("not_a_flag", False) is False
    assert not _isolated_flag_file.exists()


def test_unknown_keys_in_the_file_are_ignored(_isolated_flag_file):
    """A flag renamed in code must not be resurrected by a stale file."""
    _isolated_flag_file.write_text(json.dumps({"scraper": False, "retired_flag": False}))

    restored = flags.reload_from_disk()

    assert restored["scraper"] is False
    assert "retired_flag" not in restored


def test_corrupt_file_falls_back_to_defaults(_isolated_flag_file):
    """Fail open: booting with every feature silently off is the worse failure."""
    _isolated_flag_file.write_text("{not json at all")

    restored = flags.reload_from_disk()

    assert all(restored.values())


def test_non_bool_values_are_ignored(_isolated_flag_file):
    _isolated_flag_file.write_text(json.dumps({"scraper": "false", "whatsapp": False}))

    restored = flags.reload_from_disk()

    assert restored["scraper"] is True, "a string is not a flag value"
    assert restored["whatsapp"] is False


def test_unwritable_path_does_not_break_the_toggle(monkeypatch):
    """Losing persistence must not fail the request that pulls a kill-switch."""
    monkeypatch.setenv("CARVER_FLAGS_PATH", "/proc/definitely/not/writable/flags.json")

    assert flags.set_flag("scraper", False) is True
    assert flags.is_enabled("scraper") is False


def test_default_path_sits_beside_the_database(monkeypatch):
    from app.database import DB_PATH

    monkeypatch.delenv("CARVER_FLAGS_PATH", raising=False)
    assert flags.flags_path() == DB_PATH.parent / "flags.json"
