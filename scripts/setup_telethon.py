"""
One-time setup: generate a Telethon StringSession for the bot.

Usage:
    python scripts/setup_telethon.py

You will need:
    1. API ID and API Hash from https://my.telegram.org/apps
    2. Your phone number (with country code)
    3. The verification code sent to Telegram

After success, copy the printed session string into:
    - .env as TELETHON_SESSION_STRING
    - GitHub secret TELETHON_SESSION_STRING
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    load_dotenv()

    api_id = os.getenv("TELETHON_API_ID", "").strip()
    api_hash = os.getenv("TELETHON_API_HASH", "").strip()

    if not api_id or not api_hash:
        print("TELETHON_API_ID and TELETHON_API_HASH must be set in .env")
        print("Get them at https://my.telegram.org/apps")
        sys.exit(1)

    api_id = int(api_id)
    phone = input("Enter your phone number (e.g. +79123456789): ").strip()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start(phone)
    session_str = client.session.save()
    await client.disconnect()

    print("\n" + "=" * 60)
    print("SUCCESS! Copy this session string to .env and GitHub secrets:")
    print("=" * 60)
    print(f"TELETHON_SESSION_STRING={session_str}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
