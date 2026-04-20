"""Drive operations: metadata, download, read text."""
import io

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

    def get_file_metadata(self, file_id):
        """Return {id, name, size, mimeType} or raise if not accessible."""
        return self.service.files().get(
            fileId=file_id,
            fields="id, name, size, mimeType",
            supportsAllDrives=True,
        ).execute()

    def download(self, file_id, dest_path):
        """Download a file to local disk in chunks."""
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with io.FileIO(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def read_text(self, file_id):
        """Read a small text file's contents as a string."""
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")
