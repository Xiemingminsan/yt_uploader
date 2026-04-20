"""
One-time OAuth setup per channel.
Run: python auth.py <channel_name>
   or: python auth.py sheets    (for the shared Sheets logger account)

Opens browser, you sign in with the Google account that owns that channel's
Drive folder + YouTube channel. Saves tokens/token_<name>.json.
"""
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/spreadsheets",
]

CLIENT_SECRETS = "client_secret.json"


def main():
    if len(sys.argv) < 2:
        print("Usage: python auth.py <channel_name>")
        print("       python auth.py sheets")
        sys.exit(1)

    name = sys.argv[1]
    os.makedirs("tokens", exist_ok=True)
    token_path = f"tokens/token_{name}.json"

    if not os.path.exists(CLIENT_SECRETS):
        print(f"ERROR: {CLIENT_SECRETS} not found.")
        print("Download it from Google Cloud Console -> Credentials -> OAuth 2.0 Client -> Download JSON")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
    # Uses local server flow - opens browser, handles callback automatically
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Saved {token_path}")
    print(f"   Scopes: {', '.join(SCOPES)}")


if __name__ == "__main__":
    main()
