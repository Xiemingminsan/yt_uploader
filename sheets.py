"""
Google Sheets logger. Two-phase write:
  append_initial -> row created right after YouTube upload (safety net)
  update_final   -> same row updated after AI + metadata patch succeeds
  mark_failed    -> same row updated with status=failed + error message

Sheet columns (row 1 = headers, data written from row 2):
  A: timestamp_utc
  B: internal_channel
  C: display_codename
  D: editor_name
  E: editor_tg_id
  F: source_mp4_id
  G: source_mp4_name
  H: mode                (with_script | with_hint | skip)
  I: youtube_id
  J: youtube_url
  K: ai_title
  L: status              (uploaded | success | failed)
  M: error
"""
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


COLUMNS = "A:M"


class SheetsLogger:
    def __init__(self, token_file, spreadsheet_id, sheet_name="Log"):
        creds = Credentials.from_authorized_user_file(token_file)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.spreadsheet_id = spreadsheet_id
        self.sheet = sheet_name

    def append_initial(
        self,
        internal_channel,
        display_codename,
        editor_name,
        editor_tg_id,
        source_mp4_id,
        source_mp4_name,
        mode,
        youtube_id,
    ):
        """Phase 1: write right after YouTube upload. video_id guarantees recovery."""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = [
            ts,
            internal_channel,
            display_codename,
            editor_name,
            str(editor_tg_id),
            source_mp4_id,
            source_mp4_name,
            mode,
            youtube_id,
            "",     # youtube_url
            "",     # ai_title
            "uploaded",
            "",     # error
        ]
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!{COLUMNS}",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    def update_final(self, youtube_id, title, url, status="success"):
        """Phase 2: find row by youtube_id (col I) and fill J, K, L."""
        row_index = self._find_row_by_video_id(youtube_id)
        if row_index is None:
            return
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!J{row_index}:L{row_index}",
            valueInputOption="RAW",
            body={"values": [[url, title, status]]},
        ).execute()

    def mark_failed(self, youtube_id, error):
        """Mark a row failed. Updates L (status) and M (error)."""
        row_index = self._find_row_by_video_id(youtube_id)
        if row_index is None:
            return
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!L{row_index}:M{row_index}",
            valueInputOption="RAW",
            body={"values": [["failed", str(error)[:500]]]},
        ).execute()

    def _find_row_by_video_id(self, youtube_id):
        resp = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!I:I",
        ).execute()
        values = resp.get("values", [])
        for i, row in enumerate(values, start=1):
            if row and row[0] == youtube_id:
                return i
        return None
