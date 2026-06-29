"""
One-time script to get YouTube OAuth refresh token.
1. Go to https://console.cloud.google.com -> APIs & Services -> Credentials
2. Create OAuth 2.0 Client ID (Desktop app)
3. Download client_secret.json and place next to this script
4. Run: python scripts/get_youtube_token.py
5. Copy the refresh token into GitHub Secrets: YOUTUBE_REFRESH_TOKEN
"""
import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SECRET_FILE = Path(__file__).parent / "client_secret.json"


def main():
    if not SECRET_FILE.exists():
        print(f"Place your client_secret.json in {SECRET_FILE}")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n=== SAVE THESE TO GITHUB SECRETS ===")
    print(f"YOUTUBE_CLIENT_ID: {creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET: {creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN: {creds.refresh_token}")
    print("=====================================")


if __name__ == "__main__":
    main()
