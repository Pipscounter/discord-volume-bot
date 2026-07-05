# Discord IB Volume Kick Bot

Reads the **Kick Queue** tab of your IB Volume Tracker Google Sheet and kicks
every member marked "Pending kick" - no confirmation prompts, immediate action.

## 1. Google service account (so the bot can read/write your sheet)

1. https://console.cloud.google.com/ -> create a project.
2. Enable **Google Sheets API** and **Google Drive API**.
3. IAM & Admin -> Service Accounts -> Create Service Account -> create a JSON key.
4. Rename the downloaded key `credentials.json`, place it in this folder.
5. Open your Google Sheet -> Share -> add the service account's email
   (looks like `xxx@xxx.iam.gserviceaccount.com`) as Editor.

## 2. Discord bot setup

1. https://discord.com/developers/applications -> New Application -> Bot -> copy token.
2. Under "Privileged Gateway Intents": enable **Server Members Intent** and
   **Message Content Intent**.
3. OAuth2 -> URL Generator -> scope `bot` -> permissions: **Kick Members**,
   **Send Messages**. Use the generated link to invite the bot.
4. The bot's role must sit **above** the member roles it needs to kick
   (Server Settings -> Roles).

## 3. Install & configure

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with your token, guild ID, sheet name
```

## 4. Test once in DRY_RUN mode

Leave `DRY_RUN=true` (default). Run:

```bash
python bot.py
```

In Discord, type `!checkvolumes`. It logs who it *would* kick without kicking
anyone - check the console output matches who you expect.

## 5. Go live

Set `DRY_RUN=false` in `.env`, restart the bot. From here on:

- **Scheduled**: runs automatically once during the hour matching
  `SCHEDULED_DAY` / `SCHEDULED_HOUR_UTC` each month.
- **Manual**: `!checkvolumes` anytime, runs and kicks immediately, no prompts.
- Rows already marked "Kicked" are skipped on future runs, so re-running
  mid-month is safe - it won't double-kick anyone.

## 6. Hosting 24/7

Needed for the scheduled check to fire. Deploy to Render/Railway (same as your
other bots) with:

```
worker: python bot.py
```
