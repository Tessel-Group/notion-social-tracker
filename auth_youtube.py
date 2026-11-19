"""Authorize ONE YouTube channel.  Usage:  python auth_youtube.py my-channel-yt

A browser window opens: pick the Google account, then the right CHANNEL from the list.
"""
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from common import TOKENS, SECRETS, YT_SCOPES, find_account

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
acc = find_account(sys.argv[1])
if acc["platform"] != "YouTube":
    raise SystemExit("This key is not a YouTube account.")

secret = SECRETS / "client_secret.json"
if not secret.exists():
    raise SystemExit(f"Missing {secret}. See README, step 2.")

flow = InstalledAppFlow.from_client_secrets_file(str(secret), YT_SCOPES)
creds = flow.run_local_server(port=0, prompt="consent select_account", access_type="offline")

yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
if not items:
    raise SystemExit("No channel on this login. Try again and pick the channel from the list.")
got = items[0]["snippet"].get("customUrl", "")
title = items[0]["snippet"]["title"]
if got.lower() != acc["handle"].lower():
    raise SystemExit(f"You authorized '{title}' ({got}) but this key is for {acc['handle']}. "
                     "Run it again and pick the right channel.")

TOKENS.mkdir(exist_ok=True)
(TOKENS / f"youtube_{acc['key']}.json").write_text(creds.to_json(), encoding="utf-8")
print(f"OK: {title} ({got}) authorized.")
