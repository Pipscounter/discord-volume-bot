"""
Discord IB Volume Kick Bot
--------------------------
Reads the 'Kick Queue' tab of your IB Volume Tracker Google Sheet and kicks
every member still marked "Pending kick" - no confirmation step, immediate action.

Trigger modes:
1. Scheduled - runs automatically once a month.
2. Manual - run `!checkvolumes` in Discord any time to trigger it early.

Requirements:
    pip install discord.py gspread oauth2client python-dotenv
"""

import os
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")
SHEET_NAME = os.getenv("SHEET_NAME", "IB Volume Tracker")
WORKSHEET_NAME = "Kick Queue"  # fixed - this bot only ever reads/writes this tab

COL_DISCORD_ID = "Discord ID"
COL_USERNAME = "Discord Username"
COL_VOLUME = "Volume This Month"
COL_STATUS = "Status"
COL_LAST_CHECKED = "Last Checked"

PENDING_VALUE = "Pending kick"
DONE_VALUE = "Kicked"

SCHEDULED_DAY = int(os.getenv("SCHEDULED_DAY", "2"))
SCHEDULED_HOUR_UTC = int(os.getenv("SCHEDULED_HOUR_UTC", "3"))  # ~10am WIB

LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
LOG_CHANNEL_ID = int(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None

# One-time safety switch for YOUR first test run only.
# True = logs what it would do without kicking. Flip to false once verified working.
# This is not a per-run confirmation - once set to false, every run kicks immediately, no prompts.
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("volume-bot")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_worksheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)


def _col_index(headers, name):
    return headers.index(name) + 1


async def run_kick_check(triggered_by: str = "scheduled"):
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        logger.error("Guild not found. Check GUILD_ID.")
        return {"error": "Guild not found"}

    try:
        ws = get_worksheet()
        records = ws.get_all_records()
    except Exception as e:
        logger.exception("Failed to read Kick Queue sheet")
        return {"error": f"Sheet read failed: {e}"}

    if not records:
        return {"kicked": [], "skipped_not_found": [], "errors": []}

    headers = list(records[0].keys())
    col_status = _col_index(headers, COL_STATUS)
    col_last_checked = _col_index(headers, COL_LAST_CHECKED)

    results = {"kicked": [], "skipped_not_found": [], "errors": []}
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for idx, row in enumerate(records, start=2):  # row 1 = headers
        discord_id_raw = str(row.get(COL_DISCORD_ID, "")).strip()
        status = str(row.get(COL_STATUS, "")).strip()

        if not discord_id_raw or status != PENDING_VALUE:
            continue  # blank row, already kicked, or manually cleared

        try:
            discord_id = int(discord_id_raw)
        except ValueError:
            results["errors"].append(f"Row {idx}: invalid Discord ID '{discord_id_raw}'")
            continue

        member = guild.get_member(discord_id)
        if member is None:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.NotFound:
                results["skipped_not_found"].append(discord_id)
                ws.update_cell(idx, col_status, "Not in server")
                ws.update_cell(idx, col_last_checked, now_str)
                continue
            except Exception as e:
                results["errors"].append(f"Row {idx}: fetch_member failed: {e}")
                continue

        volume = row.get(COL_VOLUME, "")
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would kick {member} (volume={volume})")
            continue  # don't touch the sheet during dry run

        try:
            await member.kick(reason=f"Monthly trading volume ({volume} lots) below required minimum")
            results["kicked"].append(f"{member} ({discord_id}, {volume} lots)")
            ws.update_cell(idx, col_status, DONE_VALUE)
            ws.update_cell(idx, col_last_checked, now_str)
            logger.info(f"Kicked {member} for {volume} lots")
        except discord.Forbidden:
            results["errors"].append(f"Row {idx}: missing permission to kick {member}")
        except Exception as e:
            results["errors"].append(f"Row {idx}: kick failed: {e}")

    await post_summary(results, triggered_by)
    return results


async def post_summary(results, triggered_by):
    if not LOG_CHANNEL_ID:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        return

    mode = "DRY RUN" if DRY_RUN else "LIVE"
    lines = [f"**Volume check complete** ({mode}, triggered by: {triggered_by})"]
    lines.append(f"Kicked: {len(results.get('kicked', []))}")
    lines.append(f"Not found in server: {len(results.get('skipped_not_found', []))}")
    if results.get("errors"):
        lines.append(f"Errors: {len(results['errors'])}")
        for err in results["errors"][:10]:
            lines.append(f"  - {err}")
    if results.get("kicked"):
        lines.append("\n**Kicked users:**")
        for k in results["kicked"][:20]:
            lines.append(f"  - {k}")

    await channel.send("\n".join(lines))


@tasks.loop(hours=1)
async def scheduled_check():
    now = datetime.now(timezone.utc)
    if now.day == SCHEDULED_DAY and now.hour == SCHEDULED_HOUR_UTC:
        logger.info("Running scheduled monthly kick check...")
        await run_kick_check(triggered_by="scheduled")


@scheduled_check.before_loop
async def before_scheduled_check():
    await bot.wait_until_ready()


@bot.command(name="checkvolumes")
@commands.has_permissions(kick_members=True)
async def checkvolumes(ctx):
    await ctx.send(f"Running kick check now... ({'DRY RUN' if DRY_RUN else 'LIVE'})")
    results = await run_kick_check(triggered_by=f"manual by {ctx.author}")
    if "error" in results:
        await ctx.send(f"Error: {results['error']}")
        return
    await ctx.send(
        f"Done. Kicked: {len(results['kicked'])}, "
        f"Not found: {len(results['skipped_not_found'])}, "
        f"Errors: {len(results['errors'])}"
    )


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    if not scheduled_check.is_running():
        scheduled_check.start()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
