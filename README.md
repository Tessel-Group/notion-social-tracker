# notion-social-tracker

A small Python script that runs once a day on your computer, pulls the metrics of every
post from your **YouTube** channels and **Instagram** profiles, and writes them into a
**Notion** database, one row per post. Then you connect Claude to Notion and ask it what's working.

Built with Claude Code. Free, MIT license, unlimited accounts, no server: your data and
your tokens stay on your machine.

**What it collects**

| | YouTube | Instagram |
|---|---|---|
| Views, likes, comments, shares | yes | yes |
| Reach, saves | | yes |
| Avg watch time, % watched | yes | yes (reels, see notes) |
| Subscribers gained | yes | |
| Skip rate, 3s retention | | yes (reels) |
| Profile visits, follows | | posts and carousels only |
| Snapshot at 7 days (D7) | yes (exact) | yes (taken at day 7-9) |

The D7 columns let you compare a 3-day-old post with a 3-week-old one fairly.
The columns **Hook, Topic, Hypothesis, Notes** are yours: the script never touches them.
They're what turns "this post did well" into "this *kind* of post does well".

Setup takes ~45 minutes, mostly creating your own Google Cloud project and Meta app.
After that it runs by itself.

---

## 0. Install

Python 3.10+. In this folder:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      (Windows)
.venv/bin/pip install -r requirements.txt          (Mac/Linux)
copy .env.example .env                              (cp on Mac/Linux)
copy accounts.example.json accounts.json
```

Edit `accounts.json`: one entry per channel/profile. `key` is any short name you like,
`account` is how it appears in Notion, `handle` is the YouTube handle (with @) or the
Instagram username. Use the same `account` name for a YouTube channel and an Instagram
profile that post the same videos (see "Reel duration" below).

The commands below use the Windows path `.venv\Scripts\python`. On Mac/Linux use `.venv/bin/python`.

## 1. Notion (5 min)

1. https://www.notion.so/profile/integrations, **New integration**, type *Internal*.
2. Copy the secret into `.env` as `NOTION_TOKEN=...`
3. Create an empty page in Notion. Open its `...` menu, then **Connections**, and add your integration.
4. Create the database:
   ```
   .venv\Scripts\python setup_notion.py "https://www.notion.so/your-page-url"
   ```

## 2. YouTube (15 min)

1. https://console.cloud.google.com, create a project.
2. **APIs & Services > Library**: enable **YouTube Data API v3** and **YouTube Analytics API** (you need both).
3. **OAuth consent screen**: type *External*. You don't need to add scopes there:
   the script requests them itself. Google may ask for an app domain, homepage and
   privacy policy link before it lets you publish: use any site you own.
   Then **Publish app** (status *In production*). You don't need to submit it for verification.
   **Important:** if you leave it in *Testing*, tokens expire after 7 days and the script stops.
   You don't need Google's verification for personal use.
4. **Credentials > Create credentials > OAuth client ID**, type **Desktop app**.
   Download the JSON and save it as `secrets/client_secret.json`.
5. Authorize each channel:
   ```
   .venv\Scripts\python auth_youtube.py mychannel-yt
   ```
   In the browser, pick the Google account, then the **channel** (Brand Accounts show up in the list).
   Google will say "unverified app": click *Advanced > Go to ...*. It's your own app.
   If you pick the wrong channel, the script tells you.

## 3. Instagram (15 min)

Profiles must be **professional** (business or creator). Meta apps created since late
October 2026 only offer **"API setup with Unified login"**.

1. https://developers.facebook.com/apps, **Create app**, use case **"Manage messaging & content on Instagram"**.
   The app must be connected to a **business portfolio** (Meta lets you create one),
   otherwise Unified login doesn't show up.
2. **Use cases > Customize > API setup with Unified login > Create new configuration**:
   - token type: **System user access token**
   - expiration: **Never**
   - assets: your Instagram profiles
   - permissions: **instagram_basic**, **instagram_manage_insights**
3. If Meta asks you to add a profile as an **Instagram tester**, accept the invite **from a browser**:
   log in on instagram.com as that profile, go to `instagram.com/accounts/manage_access/`,
   then the **Tester invites** tab. The invite does not show in the phone app.
4. Generate the token and save it for each profile (one token can serve several profiles):
   ```
   .venv\Scripts\python add_instagram.py mychannel-ig "TOKEN"
   ```

Unified login tokens never expire. Legacy "Instagram login" tokens also work; the script refreshes those weekly.

## 4. First run

```
.venv\Scripts\python collect.py
```

To test a single account: `.venv\Scripts\python collect.py mychannel-ig`

## 5. Run it every day

**Windows** (PowerShell, in this folder):

```powershell
$a = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$PWD\run_daily.bat`"" -WorkingDirectory "$PWD"
$t = New-ScheduledTaskTrigger -Daily -At 11:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "Social Tracker" -Action $a -Trigger $t -Settings $s -Force
```

`-StartWhenAvailable` runs it as soon as you turn the PC on if it was off at 11:00.
Logs go to `logs\collect.log`.

**Mac/Linux**: add a cron line (`crontab -e`):

```
0 11 * * * cd /path/to/notion-social-tracker && .venv/bin/python collect.py >> logs/collect.log 2>&1
```

## 6. Analyze with Claude

Connect Notion to Claude (claude.ai connectors, or the Notion MCP in Claude Code) and ask, for example:

> Read my "Content performance" Notion database. For each account, compare every post with
> that account's median views and D7 views, and list the outliers. Then tell me which Hook,
> Format and Topic values show up in the outliers vs the flops, and what I should stop making.
> Say how many posts each conclusion is based on, and flag anything based on fewer than 10.

The more you fill in Hook, Topic and Hypothesis, the more useful the answer.

---

## Notes and limits

- **Short or Long:** a YouTube video up to 180 seconds is classified as a Short.
- **YouTube Analytics lags 2-3 days.** Views show up immediately; watch time, % watched,
  shares and subscribers fill in a few days later. YouTube D7 is computed on day 10, using days 0-6.
- **YouTube CTR and impressions** aren't in the public API. They stay in YouTube Studio.
- **Reel duration:** Instagram's API doesn't return the video length, so "% watched" can't be
  computed directly. If you post the same video as a YouTube Short, the script finds it
  (same `account` name, published within 3 days, most title words in the caption) and
  takes the duration from YouTube. If there's no confident match, the cell stays empty.
- **3s retention** = 100 - Instagram skip rate (people who swipe away in the first 3 seconds).
- **Profile visits and follows** aren't available per reel from Meta, only for posts and carousels.
- **Secrets:** `.env`, `secrets/` and `tokens/` hold your keys. They're in `.gitignore`: never commit them.

## License

MIT
