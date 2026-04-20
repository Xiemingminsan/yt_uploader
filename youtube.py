"""YouTube upload via resumable upload. Handles retries on 5xx + quota errors."""
import time
import random

import httplib2
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

RETRIABLE_STATUS = [500, 502, 503, 504]
MAX_RETRIES = 8


class YouTubeClient:
    def __init__(self, token_file):
        creds = Credentials.from_authorized_user_file(token_file)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        self.service = build("youtube", "v3", credentials=creds, cache_discovery=False)

    def upload(self, file_path, title, privacy="private", category_id="22"):
        """
        Resumable upload. Returns video ID.
        - privacy: private | unlisted | public
        - category_id: '22' = People & Blogs, '25' = News, '27' = Education, '28' = Science/Tech
        """
        body = {
            "snippet": {
                "title": title[:100],  # YouTube title hard limit
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        # chunksize=-1 -> single shot; for big files use chunks
        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            chunksize=50 * 1024 * 1024,  # 50MB chunks
            resumable=True,
        )

        request = self.service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        return self._resumable_execute(request)

    def _resumable_execute(self, request):
        """Run resumable upload with exponential backoff on retriable errors."""
        response = None
        retry = 0
        while response is None:
            try:
                _, response = request.next_chunk()
                if response is not None:
                    if "id" in response:
                        return response["id"]
                    raise RuntimeError(f"Upload failed, unexpected response: {response}")
            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS:
                    retry += 1
                    if retry > MAX_RETRIES:
                        raise RuntimeError(f"Upload failed after {MAX_RETRIES} retries: {e}")
                    sleep = (2 ** retry) + random.random()
                    time.sleep(min(sleep, 64))
                else:
                    # Non-retriable (auth, quota, bad request)
                    raise
            except (httplib2.HttpLib2Error, ConnectionError, OSError) as e:
                retry += 1
                if retry > MAX_RETRIES:
                    raise RuntimeError(f"Network failure after {MAX_RETRIES} retries: {e}")
                time.sleep(min((2 ** retry) + random.random(), 64))

    def update_metadata(self, video_id, title, description, tags, category_id="22"):
        """Patch the uploaded video with real title/description/tags."""
        body = {
            "id": video_id,
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:500] if isinstance(tags, list) else tags,
                "categoryId": category_id,
            },
        }
        return self.service.videos().update(part="snippet", body=body).execute()
