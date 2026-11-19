"""Create the Notion database and save its ID in .env.
Usage:  python setup_notion.py NOTION_PAGE_URL

The page must be shared with your integration (page menu ... > Connections).
"""
import os, re, sys
import requests
from dotenv import load_dotenv
from common import ROOT

load_dotenv(ROOT / ".env")
TOKEN = os.environ.get("NOTION_TOKEN")
if not TOKEN:
    raise SystemExit("Put NOTION_TOKEN in .env first (README, step 1).")
if len(sys.argv) != 2:
    raise SystemExit(__doc__)
m = re.search(r"([0-9a-f]{32})", sys.argv[1].replace("-", ""))
if not m:
    raise SystemExit("Could not find a page ID in that URL.")
page_id = m.group(1)

num = {"number": {}}
sel = lambda *opts: {"select": {"options": [{"name": o} for o in opts]}}
props = {
    "Title": {"title": {}},
    "Post ID": {"rich_text": {}},
    "Platform": sel("YouTube", "Instagram"),
    "Account": {"select": {}},
    "Format": sel("Short", "Long", "Reel", "Carousel", "Image"),
    "Link": {"url": {}},
    "Published": {"date": {}},
    "Duration s": num, "Views": num, "Reach": num, "Likes": num, "Comments": num,
    "Shares": num, "Saves": num, "Avg watch time s": num, "% watched": num,
    "Skip rate %": num, "Retention 3s %": num, "Subscribers gained": num,
    "Profile visits": num, "Follows": num,
    "Views D7": num, "% watched D7": num, "Shares D7": num,
    "Updated": {"date": {}},
    # filled in by you, never touched by the script
    "Hook": sel("Question", "Second-person scenario", "Shock statement", "List", "Story"),
    "Topic": {"multi_select": {}},
    "Hypothesis": {"rich_text": {}},
    "Notes": {"rich_text": {}},
}
r = requests.post("https://api.notion.com/v1/databases", timeout=30, headers={
    "Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
    json={"parent": {"type": "page_id", "page_id": page_id},
          "title": [{"text": {"content": "Content performance"}}], "properties": props})
if r.status_code >= 400:
    raise SystemExit(f"Notion error {r.status_code}: {r.text[:300]}\n"
                     "Is the page shared with your integration?")
db_id = r.json()["id"].replace("-", "")

env = ROOT / ".env"
text = env.read_text(encoding="utf-8")
if re.search(r"^NOTION_DATABASE_ID=.*$", text, flags=re.M):
    text = re.sub(r"^NOTION_DATABASE_ID=.*$", f"NOTION_DATABASE_ID={db_id}", text, flags=re.M)
else:
    text += f"\nNOTION_DATABASE_ID={db_id}\n"
env.write_text(text, encoding="utf-8")
print(f"OK: database created and saved in .env ({db_id})")
