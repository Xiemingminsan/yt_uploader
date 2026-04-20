"""Pure helper functions for bot.py. Isolated from python-telegram-bot so
they can be unit-tested without the SDK dependency chain.
"""
import re

_DRIVE_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")
_DRIVE_QUERY_RE = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{20,}$")


def parse_drive_link(text):
    """
    Extract a Drive file ID from any of:
      https://drive.google.com/file/d/FILE_ID/view?usp=sharing
      https://drive.google.com/file/d/FILE_ID/view
      https://drive.google.com/file/d/FILE_ID
      https://drive.google.com/open?id=FILE_ID
      https://drive.google.com/uc?id=FILE_ID
      bare FILE_ID

    Returns the file ID or None.
    """
    if not text:
        return None
    text = text.strip()
    m = _DRIVE_ID_RE.search(text)
    if m:
        return m.group(1)
    m = _DRIVE_QUERY_RE.search(text)
    if m:
        return m.group(1)
    if _BARE_ID_RE.match(text):
        return text
    return None


def is_authorized(user_id, project_codename, config):
    """
    True if user_id is listed in editors[] AND their projects list includes
    project_codename (exact match) OR is ["*"] (wildcard, admin).
    """
    editors = config.get("editors", []) or []
    for ed in editors:
        try:
            if int(ed.get("telegram_user_id", 0)) != int(user_id):
                continue
        except (TypeError, ValueError):
            continue
        projects = ed.get("projects", []) or []
        if "*" in projects:
            return True
        return project_codename in projects
    return False


def editor_for(user_id, config):
    for ed in (config.get("editors") or []):
        try:
            if int(ed.get("telegram_user_id", 0)) == int(user_id):
                return ed
        except (TypeError, ValueError):
            continue
    return None


def channel_by_codename(codename, config):
    for ch in (config.get("channels") or []):
        if ch.get("display_codename") == codename:
            return ch
    return None


def authorized_projects_for(user_id, config):
    ed = editor_for(user_id, config)
    if not ed:
        return []
    projects = ed.get("projects") or []
    all_codenames = [c["display_codename"] for c in (config.get("channels") or [])]
    if "*" in projects:
        return all_codenames
    return [p for p in projects if p in all_codenames]
