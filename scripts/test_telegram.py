#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env")
        return 2
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": "CatFinder test OK"},
        timeout=20,
    )
    print(response.status_code, response.text[:500])
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
