import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKENS = ROOT / "tokens"
SECRETS = ROOT / "secrets"
YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
IG_API = "https://graph.instagram.com"
# New Meta apps (since late Oct 2026) use "Unified login": system user tokens that never expire
FB_API = "https://graph.facebook.com/v26.0"


def load_accounts():
    f = ROOT / "accounts.json"
    if not f.exists():
        raise SystemExit("accounts.json not found: copy accounts.example.json to accounts.json and edit it.")
    return json.loads(f.read_text(encoding="utf-8"))


def find_account(key):
    for a in load_accounts():
        if a["key"] == key:
            return a
    keys = ", ".join(a["key"] for a in load_accounts())
    raise SystemExit(f"Key '{key}' not found in accounts.json. Valid keys: {keys}")
