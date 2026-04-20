import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_helpers import parse_drive_link


FILE_ID = "1aBcDeF_12345678_XYZabcDEF"


def test_file_d_view_usp():
    url = f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing"
    assert parse_drive_link(url) == FILE_ID


def test_file_d_view():
    url = f"https://drive.google.com/file/d/{FILE_ID}/view"
    assert parse_drive_link(url) == FILE_ID


def test_file_d_bare():
    url = f"https://drive.google.com/file/d/{FILE_ID}"
    assert parse_drive_link(url) == FILE_ID


def test_open_id():
    url = f"https://drive.google.com/open?id={FILE_ID}"
    assert parse_drive_link(url) == FILE_ID


def test_uc_id():
    url = f"https://drive.google.com/uc?id={FILE_ID}"
    assert parse_drive_link(url) == FILE_ID


def test_bare_id():
    assert parse_drive_link(FILE_ID) == FILE_ID


def test_bare_id_with_whitespace():
    assert parse_drive_link(f"  {FILE_ID}  ") == FILE_ID


def test_rejects_short_bare():
    assert parse_drive_link("short") is None


def test_rejects_plain_text():
    assert parse_drive_link("hello world, here is a link") is None


def test_rejects_empty():
    assert parse_drive_link("") is None
    assert parse_drive_link(None) is None


def test_url_with_extra_query():
    url = f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing&foo=bar"
    assert parse_drive_link(url) == FILE_ID


def test_trailing_slash():
    url = f"https://drive.google.com/file/d/{FILE_ID}/"
    assert parse_drive_link(url) == FILE_ID
