"""Save the token of ONE Instagram profile.  Usage:  python add_instagram.py my-profile-ig "TOKEN"

Works with both "Unified login" tokens (new Meta apps) and legacy "Instagram login" tokens.
"""
import sys, json, datetime as dt
import requests
from common import TOKENS, IG_API, FB_API, find_account

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
acc = find_account(sys.argv[1])
if acc["platform"] != "Instagram":
    raise SystemExit("This key is not an Instagram account.")
token = sys.argv[2].strip()
want = acc["handle"].lower().lstrip("@")


def get(url, **params):
    params["access_token"] = token
    return requests.get(url, params=params, timeout=30).json()


data = None
# 1) Unified login: the token sees one or more assigned Instagram accounts
res = get(f"{FB_API}/me/assigned_instagram_accounts")
if "error" not in res:
    found = []
    for item in res.get("data", []):
        info = get(f"{FB_API}/{item['id']}", fields="username")
        found.append(info.get("username", "?"))
        if info.get("username", "").lower() == want:
            data = {"mode": "unified", "token": token, "ig_user_id": item["id"],
                    "refreshed": dt.date.today().isoformat()}
            break
    if not data:
        raise SystemExit(f"This token sees {found or 'no accounts'}, but not @{want}. "
                         "Add the profile as an asset in your Meta configuration.")
else:
    # 2) legacy Instagram login
    me = get(f"{IG_API}/me", fields="username,account_type")
    if "error" in me:
        raise SystemExit(f"Invalid token: {res['error'].get('message')} / {me['error'].get('message')}")
    if me["username"].lower() != want:
        raise SystemExit(f"This token belongs to @{me['username']}, but the key is for @{want}.")
    data = {"mode": "instagram", "token": token, "refreshed": dt.date.today().isoformat()}

TOKENS.mkdir(exist_ok=True)
(TOKENS / f"instagram_{acc['key']}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
print(f"OK: @{want} saved ({data['mode']} mode).")
