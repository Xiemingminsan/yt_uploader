import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_helpers import is_authorized


CONFIG = {
    "channels": [
        {"internal_name": "wiserice", "display_codename": "Falcon"},
        {"internal_name": "econ", "display_codename": "Meridian"},
        {"internal_name": "cook", "display_codename": "Atlas"},
    ],
    "editors": [
        {"telegram_user_id": 111, "display_name": "Admin",  "projects": ["*"]},
        {"telegram_user_id": 222, "display_name": "Solo",   "projects": ["Falcon"]},
        {"telegram_user_id": 333, "display_name": "Dual",   "projects": ["Meridian", "Atlas"]},
    ],
}


def test_admin_wildcard_any_project():
    assert is_authorized(111, "Falcon", CONFIG)
    assert is_authorized(111, "Meridian", CONFIG)
    assert is_authorized(111, "Atlas", CONFIG)


def test_solo_editor_own_project():
    assert is_authorized(222, "Falcon", CONFIG)


def test_solo_editor_other_project_rejected():
    assert not is_authorized(222, "Meridian", CONFIG)
    assert not is_authorized(222, "Atlas", CONFIG)


def test_dual_editor_both_projects():
    assert is_authorized(333, "Meridian", CONFIG)
    assert is_authorized(333, "Atlas", CONFIG)


def test_dual_editor_other_project_rejected():
    assert not is_authorized(333, "Falcon", CONFIG)


def test_unknown_user_rejected():
    assert not is_authorized(999, "Falcon", CONFIG)
    assert not is_authorized(999, "Meridian", CONFIG)


def test_id_as_string_works():
    # Editor IDs might come in as str from Telegram; comparison should coerce.
    assert is_authorized("222", "Falcon", CONFIG)


def test_empty_config():
    assert not is_authorized(111, "Falcon", {})
    assert not is_authorized(111, "Falcon", {"editors": []})
