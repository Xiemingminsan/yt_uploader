"""Drive operations: list MP4s, find matching TXT, download, read text."""
import io
import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


class DriveClient:
    def __init__(self, token_file):
        creds = Credentials.from_authorized_user_file(token_file)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_mp4s(self, folder_id):
        """Return list of {id, name, size} for MP4s in folder (not in trash)."""
        q = (
            f"'{folder_id}' in parents "
            f"and mimeType='video/mp4' "
            f"and trashed=false"
        )
        resp = self.service.files().list(
            q=q,
            fields="files(id, name, size, createdTime)",
            pageSize=100,
            orderBy="createdTime",
        ).execute()
        return resp.get("files", [])

    def find_txt(self, folder_id, base_name):
        """Find <base_name>.txt in the same folder. Returns file dict or None."""
        txt_name = f"{base_name}.txt"
        q = (
            f"'{folder_id}' in parents "
            f"and name='{txt_name}' "
            f"and trashed=false"
        )
        resp = self.service.files().list(
            q=q, fields="files(id, name)", pageSize=1
        ).execute()
        files = resp.get("files", [])
        return files[0] if files else None

    def download(self, file_id, dest_path):
        """Download a file to local disk in chunks."""
        request = self.service.files().get_media(fileId=file_id)
        with io.FileIO(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def read_text(self, file_id):
        """Read a small text file's contents as a string."""
        request = self.service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")
