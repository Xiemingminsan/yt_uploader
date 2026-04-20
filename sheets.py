"""
Google Sheets logger. Two-phase write:
  append_initial -> row created right after upload (safety net, orphan recovery)
  update_final   -> same row updated after AI + metadata succeeds

Sheet columns (row 1 = headers, we write from row 2):
  A: timestamp_utc
  B: channel
  C: filename
  D: youtube_id
  E: title
  F: url
  G: status
"""
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


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

    def append_initial(self, channel, filename, youtube_id):
        """Phase 1: write immediately after upload with youtube_id."""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = [ts, channel, filename, youtube_id, "", "", "uploaded"]
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!A:G",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    def update_final(self, youtube_id, title, url, status):
        """Phase 2: find row by youtube_id (col D) and fill E, F, G."""
        # Find the row
        resp = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!D:D",
        ).execute()
        values = resp.get("values", [])
        row_index = None
        for i, row in enumerate(values, start=1):
            if row and row[0] == youtube_id:
                row_index = i
        if row_index is None:
            # Row disappeared somehow — just append a new one
            self.append_initial("?", "?", youtube_id)
            return

        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet}!E{row_index}:G{row_index}",
            valueInputOption="RAW",
            body={"values": [[title, url, status]]},
        ).execute()
