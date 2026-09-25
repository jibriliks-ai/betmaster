import os
import time
import threading
import requests
import random
import json
import hmac
import hashlib
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")

FLW_PUBLIC = os.getenv("FLUTTERWAVE_PUBLIC_KEY", "")
FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
FLW_WEBHOOK_SECRET = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET", "") # Same as Secret Hash you set in Flutterwave dashboard
ADMIN_KEY = os.getenv("ADMIN_KEY", "BetMasterAdmin123")

SUPPORT_HANDLE = "@Jibriliks"
BOT_HANDLE = "@Betmasterpro_bot"
BOT_HANDLE_2 = "@Betmaster_bot"
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"

app = FastAPI()
print(f"=== BETMASTER SUPER BRAIN LIVE ===")
print(f"Channel: {CHANNEL_ID} | Bot: {bool(BOT_TOKEN)} | Flutterwave: {bool(FLW_SECRET)} | Webhook Secret: {bool(FLW_WEBHOOK_SECRET)}")

WELCOME_MSG = f"""🎯 **Welcome to BetMasterPro - Super Smart AI** 🎯

Your 100% CURRENT football prediction expert! All leagues + national teams.

**How to use:**
⚽ Send match: `Arsenal vs Chelsea`
📅 Today's games: `/today`
🌍 Country fixtures: `/fixturesengland`
   Try: /fixtureschina /fixturesspain /fixturesgermany /fixturesnigeria /fixturesbrazil /fixturesworld (national teams!)
💎 Check plan: `/myplan`
💳 Upgrade: `/subscribe`
🆘 Help & Support: `/help`

**Example:**
Type `England vs Brazil` or `/fixturesengland` for England fixtures today with dates!

**Limits:**
🆓 FREE: 2 predictions/day + 1 UNIQUE tip at 6AM WAT
💎 VIP: 10 predictions/day + 2 UNIQUE personalized tips (6AM & 9PM WAT)

Channel: {CHANNEL_LINK}
Support: {SUPPORT_HANDLE}
Bots: {BOT_HANDLE} | {BOT_HANDLE_2}"""

DISCLAIMER = "\n\n⚠️ *Disclaimer:* Betting involves risk. AI analysis only, not financial advice. Stake responsibly, 18+ only."

def send_message(chat_id, text, parse="Markdown"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "..."
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse}, timeout=15)
    except Exception as e:
        print(f"Send error: {e}")

def activate_vip(user_id, plan):
    from database import SessionLocal, get_user
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id))
        today = date.today()
        expiry = today + timedelta(days=7 if plan == "weekly" else 30)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.daily_count = 0
        db.commit()
        print(f"VIP ACTIVATED: {user_id} {plan} till {expiry}")
        # Notify user
        method = "Bank Transfer" if "bank" in plan else "Card/Flutterwave"
        send_message(int(user_id), f"🎉 **VIP Activated via {method}!**\n\n✅ Plan: {plan.upper()} (₦{'2,000' if 'weekly' in plan else '5,000'})\n📅 Valid till: {expiry}\n💎 10 chats/day + 2 personalized tips daily (6AM & 9PM WAT)!\n\nSupport: {SUPPORT_HANDLE}\nChat: {BOT_HANDLE} | {BOT_HANDLE_2}\n\nSend any match now: `Arsenal vs Chelsea`")
        return True
    except Exception as e:
        print(f"VIP activation error {e}")
        return False
    finally:
        db.close()

# ================= BOT LOOP =================
def bot_polling_loop():
    if not BOT_TOKEN:
        print("No BOT_TOKEN")
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("Polling started - SUPER BRAIN active")
    except Exception as e:
        print(f"Webhook delete error {e}")

    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures

    offset = 0
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    while True:
        try:
            resp = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30).json()
            if not resp.get("ok"):
                time.sleep(5)
                continue

            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!= "private":
                    continue

                chat_id = msg["chat"]["id"]
                text = msg["text"].strip()
                user_id = msg["from"]["id"]
                username = msg["from"].get("username", "")
                low = text.lower()

                db = SessionLocal()
                try:
                    user = get_user(db, user_id, username)

                    if low.startswith("/start"):
                        send_message(chat_id, WELCOME_MSG)

                    elif low.startswith("/help"):
                        send_message(chat_id, f"🆘 **BetMasterPro Support**\n\nNeed help? Contact:\n👤 Support Handle: {SUPPORT_HANDLE}\n🔗 https://t.me/Jibriliks\n\n🤖 Bot Handles:\n{BOT_HANDLE} (main)\n{BOT_HANDLE_2}\n\n📢 Channel: {CHANNEL_LINK}\n\n**Commands:**\n/today - Today's worldwide fixtures\n/fixturesengland - England PL today\n/fixtureschina - China SL today\n/fixtures + any country name\n/fixturesworld - National teams\n/myplan - Check plan\n/subscribe - Upgrade ₦2k/₦5k\n\nWe reply within 2 hours!")

                    elif low.startswith("/fixtures"):
                        country_raw = low.replace("/fixtures", "").strip()
                        if not country_raw:
                            country_raw = "england"
                        country_raw = country_raw.split()[0] # first word only
                        if country_raw in ["today", "tomorrow"]:
                            country_raw = "england"

                        send_message(chat_id, f"🌍 Fetching **{country_raw.title()}** fixtures for today... 100% live data + national teams supported...")
                        fixtures = fetch_fixtures_by_country(country_raw, days_ahead=0, limit=5 if user.is_vip else 2)

                        if not fixtures:
                            send_message(chat_id, f"No fixtures for {country_raw.title()} today. Try:\n/fixturesworld (national teams)\n/fixturesengland\n/fixturesspain\n/fixturesnigeria\n\nSupport: {SUPPORT_HANDLE}")
                            continue

                        for f in fixtures:
                            data = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "
