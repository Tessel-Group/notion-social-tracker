"""Collects the metrics of every account in accounts.json and writes them to the Notion database.
Usage:  python collect.py        (all accounts)
        python collect.py KEY    (one account, for testing)
"""
import os, sys, json, time, re, datetime as dt, traceback
import requests
from dotenv import load_dotenv
from common import ROOT, TOKENS, YT_SCOPES, IG_API, FB_API, load_accounts

load_dotenv(ROOT / ".env")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB = os.environ.get("NOTION_DATABASE_ID")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "90"))
TODAY = dt.date.today()


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] {msg}", flush=True)


# ------------------------------------------------------------------ Notion
NH = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28",
      "Content-Type": "application/json"}

# Notion column -> row field
METRICS = {
    "Duration s": "duration", "Views": "views", "Reach": "reach", "Likes": "likes",
    "Comments": "comments", "Shares": "shares", "Saves": "saves",
    "Avg watch time s": "avg_watch_s", "% watched": "watched_pct", "Skip rate %": "skip_rate",
    "Subscribers gained": "subs_gained", "Views D7": "views_d7",
    "Retention 3s %": "retention_3s", "Profile visits": "profile_visits", "Follows": "follows",
    "% watched D7": "watched_pct_d7", "Shares D7": "shares_d7",
}


def notion(method, path, **kw):
    for _ in range(6):
        r = requests.request(method, "https://api.notion.com/v1" + path, headers=NH, timeout=30, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError("Notion: too many failed attempts")


def load_existing():
    """Post ID -> {page_id, has_d7, ...}"""
    out, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = notion("POST", f"/databases/{NOTION_DB}/query", json=body)
        for p in res["results"]:
            props = p["properties"]
            key = "".join(t["plain_text"] for t in props["Post ID"]["rich_text"])
            if key:
                pub = (props["Published"]["date"] or {}).get("start")
                out[key] = {
                    "page_id": p["id"], "has_d7": props["Views D7"]["number"] is not None,
                    "platform": (props["Platform"]["select"] or {}).get("name"),
                    "account": (props["Account"]["select"] or {}).get("name"),
                    "format": (props["Format"]["select"] or {}).get("name"),
                    "title": "".join(t["plain_text"] for t in props["Title"]["title"]),
                    "published": pub[:10] if pub else None,
                    "duration": props["Duration s"]["number"],
                }
        if not res.get("has_more"):
            return out
        cursor = res["next_cursor"]


def to_props(row):
    p = {
        "Title": {"title": [{"text": {"content": (row.get("title") or "(untitled)")[:200]}}]},
        "Post ID": {"rich_text": [{"text": {"content": row["key"]}}]},
        "Platform": {"select": {"name": row["platform"]}},
        "Account": {"select": {"name": row["account"]}},
        "Format": {"select": {"name": row["format"]}},
        "Link": {"url": row["url"]},
        "Published": {"date": {"start": row["published"]}},
        "Updated": {"date": {"start": TODAY.isoformat()}},
    }
    for col, field in METRICS.items():
        v = row.get(field)
        if v is not None:
            p[col] = {"number": round(float(v), 2)}
    return p


def upsert(rows, existing):
    created = updated = 0
    for row in rows:
        props = to_props(row)
        hit = existing.get(row["key"])
        if hit:
            notion("PATCH", f"/pages/{hit['page_id']}", json={"properties": props})
            updated += 1
        else:
            res = notion("POST", "/pages", json={"parent": {"database_id": NOTION_DB}, "properties": props})
            hit = existing[row["key"]] = {"page_id": res["id"], "has_d7": False}
            created += 1
        if row.get("views_d7") is not None:
            hit["has_d7"] = True
        hit.update({k: row.get(k) for k in ("platform", "account", "format", "title", "published", "duration")})
    return created, updated


# ------------------------------------------------------------------ YouTube
def iso_duration(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def collect_youtube(acc, existing):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    f = TOKENS / f"youtube_{acc['key']}.json"
    if not f.exists():
        raise RuntimeError(f"missing token: run  python auth_youtube.py {acc['key']}")
    creds = Credentials.from_authorized_user_file(str(f), YT_SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        f.write_text(creds.to_json(), encoding="utf-8")

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    since = TODAY - dt.timedelta(days=LOOKBACK_DAYS)

    ids, token = [], None
    while True:
        res = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                      maxResults=50, pageToken=token).execute()
        old = False
        for it in res.get("items", []):
            pub = it["contentDetails"].get("videoPublishedAt")
            if not pub:
                continue
            if dt.date.fromisoformat(pub[:10]) < since:
                old = True
                continue
            ids.append(it["contentDetails"]["videoId"])
        token = res.get("nextPageToken")
        if old or not token:
            break
    if not ids:
        return []

    videos = {}
    for batch in chunks(ids, 50):
        res = yt.videos().list(part="snippet,contentDetails,statistics,status", id=",".join(batch)).execute()
        for v in res.get("items", []):
            if v["status"].get("privacyStatus") != "public":
                continue
            videos[v["id"]] = v
    if not videos:
        return []

    # lifetime metrics from YouTube Analytics
    start = min(v["snippet"]["publishedAt"][:10] for v in videos.values())
    an = {}
    for batch in chunks(list(videos), 200):
        res = ya.reports().query(
            ids="channel==MINE", startDate=start, endDate=TODAY.isoformat(),
            metrics="views,averageViewDuration,averageViewPercentage,subscribersGained,likes,comments,shares",
            dimensions="video", filters="video==" + ",".join(batch), maxResults=200, sort="-views",
        ).execute()
        cols = [c["name"] for c in res["columnHeaders"]]
        for r in res.get("rows", []):
            an[r[0]] = dict(zip(cols, r))

    rows = []
    for vid, v in videos.items():
        pub = dt.date.fromisoformat(v["snippet"]["publishedAt"][:10])
        dur = iso_duration(v["contentDetails"].get("duration"))
        st, a = v.get("statistics", {}), an.get(vid, {})
        is_short = dur is not None and dur <= 180
        row = {
            "key": f"yt:{vid}", "platform": "YouTube", "account": acc["account"],
            "format": "Short" if is_short else "Long",
            "title": v["snippet"]["title"], "published": pub.isoformat(),
            "url": f"https://www.youtube.com/{'shorts/' if is_short else 'watch?v='}{vid}",
            "duration": dur,
            # public views are real-time; Analytics lags 2-3 days
            "views": st.get("viewCount"), "likes": st.get("likeCount"), "comments": st.get("commentCount"),
            "shares": a.get("shares"), "avg_watch_s": a.get("averageViewDuration"),
            "watched_pct": a.get("averageViewPercentage"), "subs_gained": a.get("subscribersGained"),
        }
        # exact D7 snapshot: days 0-6 after publishing, once the data has settled
        hit = existing.get(row["key"])
        if (not hit or not hit["has_d7"]) and (TODAY - pub).days >= 10:
            r = ya.reports().query(
                ids="channel==MINE", startDate=pub.isoformat(),
                endDate=(pub + dt.timedelta(days=6)).isoformat(),
                metrics="views,averageViewPercentage,shares", filters=f"video=={vid}",
            ).execute()
            if r.get("rows"):
                row["views_d7"], row["watched_pct_d7"], row["shares_d7"] = r["rows"][0]
        rows.append(row)
    return rows


# ------------------------------------------------------------------ Instagram
class IGError(Exception):
    pass


_IG_BASE = {"base": IG_API}


def ig_get(path, token, **params):
    params["access_token"] = token
    r = requests.get(f"{_IG_BASE['base']}/{path}", params=params, timeout=30)
    data = r.json()
    if "error" in data:
        raise IGError(data["error"].get("message", str(data["error"])))
    return data


def ig_token(acc):
    f = TOKENS / f"instagram_{acc['key']}.json"
    if not f.exists():
        raise RuntimeError(f"missing token: run  python add_instagram.py {acc['key']} TOKEN")
    d = json.loads(f.read_text(encoding="utf-8"))
    if d.get("mode") == "unified":
        # system user token: never expires, uses graph.facebook.com with the profile ID
        _IG_BASE["base"] = FB_API
        return d["token"], d["ig_user_id"]
    _IG_BASE["base"] = IG_API
    # legacy Instagram login tokens last 60 days: refresh weekly
    if (TODAY - dt.date.fromisoformat(d["refreshed"])).days >= 7:
        try:
            r = ig_get("refresh_access_token", d["token"], grant_type="ig_refresh_token")
            d["token"], d["refreshed"] = r["access_token"], TODAY.isoformat()
            f.write_text(json.dumps(d, indent=2), encoding="utf-8")
            log(f"  Instagram token refreshed for {acc['key']}")
        except IGError as e:
            log(f"  WARNING: token refresh failed for {acc['key']}: {e}")
    return d["token"], "me"


REEL_METRICS = ["views", "reach", "likes", "comments", "shares", "saved",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
FEED_METRICS = ["views", "reach", "likes", "comments", "shares", "saved"]
# optional metrics: requested one by one; if the API rejects one for a format,
# it is skipped for that format for the rest of the run
OPTIONAL_REEL = ["reels_skip_rate"]  # Meta gives profile_visits and follows only for posts, not reels
OPTIONAL_FEED = ["profile_visits", "follows"]
_optional_ok = {}


def _parse_insights(data):
    out = {}
    for item in data.get("data", []):
        val = None
        if item.get("values"):
            val = item["values"][0].get("value")
        elif item.get("total_value"):
            val = item["total_value"].get("value")
        out[item["name"]] = val
    return out


def ig_insights(media_id, metrics, token):
    try:
        return _parse_insights(ig_get(f"{media_id}/insights", token, metric=",".join(metrics)))
    except IGError:
        out = {}  # one unsupported metric fails the whole call: retry one by one
        for m in metrics:
            try:
                out.update(_parse_insights(ig_get(f"{media_id}/insights", token, metric=m)))
            except IGError:
                pass
        return out


_WORD = re.compile(r"[a-z0-9']+")
_STOP = {"the", "and", "you", "your", "are", "for", "with", "this", "that", "what", "how", "shorts"}


def _words(text):
    text = re.sub(r"#\S+", " ", (text or "").lower())
    return {w for w in _WORD.findall(text) if len(w) > 2 and w not in _STOP}


def match_youtube(acc_name, caption, pub, existing):
    """Find the YouTube Short of the same account that matches the reel:
    published within 3 days, with most title words present in the caption."""
    cap = _words(caption)
    best, best_key = None, None
    for e in existing.values():
        if e.get("platform") != "YouTube" or e.get("account") != acc_name or e.get("format") != "Short":
            continue
        if not e.get("duration") or not e.get("published"):
            continue
        gap = abs((dt.date.fromisoformat(e["published"]) - pub).days)
        if gap > 3:
            continue
        tw = _words(e.get("title"))
        if not tw:
            continue
        score = len(tw & cap) / len(tw)
        if score >= 0.6 and (best_key is None or (score, -gap) > best_key):
            best, best_key = e, (score, -gap)
    return best


def collect_instagram(acc, existing):
    token, user = ig_token(acc)
    since = TODAY - dt.timedelta(days=LOOKBACK_DAYS)
    media, after = [], None
    while True:
        params = {"fields": "id,caption,media_type,media_product_type,timestamp,permalink", "limit": 50}
        if after:
            params["after"] = after
        res = ig_get(f"{user}/media", token, **params)
        old = False
        for m in res.get("data", []):
            if dt.date.fromisoformat(m["timestamp"][:10]) < since:
                old = True
                continue
            media.append(m)
        after = res.get("paging", {}).get("cursors", {}).get("after")
        if old or not res.get("paging", {}).get("next"):
            break

    rows = []
    for m in media:
        is_reel = m.get("media_product_type") == "REELS" or m.get("media_type") == "VIDEO"
        fmt = "Reel" if is_reel else ("Carousel" if m.get("media_type") == "CAROUSEL_ALBUM" else "Image")
        ins = ig_insights(m["id"], REEL_METRICS if is_reel else FEED_METRICS, token)
        for opt in (OPTIONAL_REEL if is_reel else OPTIONAL_FEED):
            k = (opt, is_reel)
            if _optional_ok.get(k, True):
                try:
                    ins.update(_parse_insights(ig_get(f"{m['id']}/insights", token, metric=opt)))
                    _optional_ok[k] = True
                except IGError as e:
                    if not _optional_ok.get(k):  # never worked: disable it
                        _optional_ok[k] = False
                        log(f"  metric {opt} not available for {'reels' if is_reel else 'posts'}: {e}")
        pub = dt.date.fromisoformat(m["timestamp"][:10])
        caption = (m.get("caption") or "").strip().split("\n")[0]
        avg_ms = ins.get("ig_reels_avg_watch_time")
        dur = None
        if is_reel:
            yt = match_youtube(acc["account"], m.get("caption"), pub, existing)
            dur = yt["duration"] if yt else None
        row = {
            "key": f"ig:{m['id']}", "platform": "Instagram", "account": acc["account"], "format": fmt,
            "title": caption[:90] or "(no caption)", "published": pub.isoformat(), "url": m.get("permalink"),
            "views": ins.get("views"), "reach": ins.get("reach"), "likes": ins.get("likes"),
            "comments": ins.get("comments"), "shares": ins.get("shares"), "saves": ins.get("saved"),
            "avg_watch_s": avg_ms / 1000 if avg_ms is not None else None,
            "duration": dur,
            "watched_pct": avg_ms / 10 / dur if (avg_ms is not None and dur) else None,
            "skip_rate": ins.get("reels_skip_rate"),
            "retention_3s": 100 - ins["reels_skip_rate"] if ins.get("reels_skip_rate") is not None else None,
            "profile_visits": ins.get("profile_visits"), "follows": ins.get("follows"),
        }
        # Instagram only gives lifetime values: D7 is captured when the post is 7-9 days old
        hit = existing.get(row["key"])
        if (not hit or not hit["has_d7"]) and 7 <= (TODAY - pub).days <= 9:
            row["views_d7"], row["shares_d7"] = row["views"], row["shares"]
        rows.append(row)
    return rows


# ------------------------------------------------------------------ main
def main():
    if not NOTION_TOKEN or not NOTION_DB:
        raise SystemExit("NOTION_TOKEN or NOTION_DATABASE_ID missing in .env (see README, step 1).")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    accounts = [a for a in load_accounts() if not only or a["key"] == only]
    accounts.sort(key=lambda a: a["platform"] != "YouTube")  # YouTube first: reels need the durations
    existing = load_existing()
    log(f"Start: {len(accounts)} accounts, {len(existing)} posts already in the database")
    errors = 0
    for acc in accounts:
        try:
            fn = collect_youtube if acc["platform"] == "YouTube" else collect_instagram
            rows = fn(acc, existing)
            c, u = upsert(rows, existing)
            log(f"{acc['key']}: {len(rows)} posts ({c} new, {u} updated)")
        except Exception as e:
            errors += 1
            log(f"{acc['key']}: ERROR {e}")
            traceback.print_exc()
    log(f"Done. Accounts with errors: {errors}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
