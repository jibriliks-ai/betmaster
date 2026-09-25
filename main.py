import os, time, threading, requests, random, hmac, hashlib, json
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"): CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")
FLW_PUBLIC = os.getenv("FLUTTERWAVE_PUBLIC_KEY","")
FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY","")
SUPPORT_HANDLE = "@Jibriliks"
BOT_HANDLE = "@Betmasterpro_bot" # Your bot handle - also add @Betmaster_bot as requested in channel messages
BOT_HANDLE_2 = "@Betmaster_bot"

app = FastAPI()
print(f"BETMASTER SUPER BRAIN LIVE | Channel {CHANNEL_ID}")

WELCOME_MSG = f"""🎯 **Welcome to BetMasterPro - Super Smart AI** 🎯

Your 100% current football prediction expert! I know ALL leagues + national teams.

**Commands:**
⚽ `Arsenal vs Chelsea` - Any match prediction
📅 `/today` - Today's fixtures worldwide
🌍 `/fixturesengland` - England Premier League today
🌍 `/fixtureschina` - China Super League today
🌍 `/fixturesspain` - LaLiga today
🌍 `/fixtures` + any country: /fixturesgermany /fixturesnigeria /fixturesbrazil /fixturesworld (for national teams!)
💎 `/myplan` - Check your plan
💳 `/subscribe` - Upgrade to VIP
🆘 `/help` - Support

**Limits:**
🆓 FREE: 2 predictions/day + 1 unique tip daily at 6AM WAT
💎 VIP: 10 predictions/day + 2 unique personalized tips (6AM & 9PM WAT)

Channel: https://t.me/+IFK0qoDI2B5lYWI0
Support: {SUPPORT_HANDLE}

👇 Try: `England vs Brazil` or `/fixturesengland`"""

DISCLAIMER = "\n\n⚠️ *Disclaimer:* Betting risk. AI analysis only, 18+ stake responsibly."

def send_message(chat_id, text, parse="Markdown"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000: text = text[:4000]+"..."
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse}, timeout=15)
    except Exception as e: print(e)

def activate_vip(user_id, plan):
    from database import SessionLocal, get_user
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id))
        today = date.today()
        expiry = today + timedelta(days=7 if plan=="weekly" else 30)
        user.is_vip = True; user.vip_expiry = str(expiry); user.daily_count = 0; db.commit()
        send_message(int(user_id), f"🎉 **VIP Activated via {'Bank Transfer' if 'bank' in plan else 'Card'}!**\n\n✅ Plan: {plan.upper()} till {expiry}\n💎 10 chats/day + 2 daily personalized tips!\n\nSupport: {SUPPORT_HANDLE}\nBot: {BOT_HANDLE} / {BOT_HANDLE_2}")
        return True
    except Exception as e: print(f"VIP activation error {e}"); return False
    finally: db.close()

def bot_polling_loop():
    if not BOT_TOKEN: return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass
    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures
    offset=0; base=f"https://api.telegram.org/bot{BOT_TOKEN}"
    while True:
        try:
            resp=requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30).json()
            if not resp.get("ok"): time.sleep(5); continue
            for upd in resp.get("result", []):
                offset=upd["update_id"]+1
                msg=upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!="private": continue
                chat_id=msg["chat"]["id"]; text=msg["text"].strip(); user_id=msg["from"]["id"]; username=msg["from"].get("username","")
                db=SessionLocal()
                try:
                    user=get_user(db, user_id, username)
                    low=text.lower()

                    # /START
                    if low.startswith("/start"):
                        send_message(chat_id, WELCOME_MSG)

                    # /HELP - with support handle
                    elif low.startswith("/help"):
                        send_message(chat_id, f"🆘 **BetMasterPro Support**\n\nNeed help?\nContact our support: {SUPPORT_HANDLE}\nTelegram: https://t.me/Jibriliks\n\nBot handles:\n{BOT_HANDLE} (main)\n{BOT_HANDLE_2}\n\nChannel: https://t.me/+IFK0qoDI2B5lYWI0\n\nCommands:\n/today - today matches\n/fixturesengland - England fixtures\n/fixtures + country name\n/myplan - check plan\n/subscribe - upgrade\n\nWe reply within 2 hours!")

                    # /FIXTURES{country} - Super smart command
                    elif low.startswith("/fixtures"):
                        # Extract country: /fixturesengland or /fixtures england or /fixturesengland today
                        country_raw = low.replace("/fixtures","").strip()
                        if not country_raw: country_raw = "england"
                        # Remove words like today, tomorrow
                        country_raw = country_raw.split()[0]
                        if country_raw in ["today","tomorrow"]: country_raw = "england"

                        limit = 5 if user.is_vip else 2
                        if user.daily_count >= (10 if user.is_vip else 2) and not low.startswith("/fixtures"):
                            pass # handled elsewhere

                        send_message(chat_id, f"🌍 Fetching **{country_raw.title()}** fixtures for today... 100% live data...")
                        fixtures = fetch_fixtures_by_country(country_raw, days_ahead=0, limit=limit)

                        if not fixtures:
                            send_message(chat_id, f"No fixtures found for {country_raw.title()} today. Try /fixturesworld for national teams or /fixturesengland.\n\nSupport: {SUPPORT_HANDLE}")
                            continue

                        for f in fixtures:
                            data={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                            pred=get_ai_prediction(data); update_league_history(db, user, f["league"])
                            # Unique message variation
                            intro = random.choice(["🔥 Hot Tip:", "💎 Expert Pick:", "⚡ VIP Insight:", "🎯 Top Prediction:"])
                            full_msg = f"{intro}\n⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | 🌍 {f.get('country',country_raw.title())} | ⏰ {f['time']} WAT | 📅 {f.get('date','Today')}\n💰 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']}\n\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **{pred['verdict']}**\n{pred['stake']}{pred['disclaimer']}\n\n💬 More? {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 {SUPPORT_HANDLE}"
                            send_message(chat_id, full_msg)
                            time.sleep(0.5)
                        # Don't count /fixtures as chat limit for free? Count 1
                        user.daily_count+=1; db.commit()

                    elif low.startswith("/myplan"):
                        send_message(chat_id, f"Plan: {'💎 VIP till '+user.vip_expiry if user.is_vip else '🆓 FREE'} ({user.daily_count}/{'10' if user.is_vip else '2'})\nFav: {user.favorite_league}\nSupport: {SUPPORT_HANDLE}\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}")

                    elif low.startswith("/subscribe"):
                        send_message(chat_id, f"💳 Plans:\nWeekly ₦2,000 (7 days)\nMonthly ₦5,000 (30 days)\n\nPay with Card OR Bank Transfer - auto activates!\n\n👉 https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\n\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/today"):
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit}. Upgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}"); continue
                        send_message(chat_id, "📅 Fetching today's worldwide fixtures (including national teams)...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=5, fav_league=user.favorite_league if user.is_vip else None)
                        for f in fixtures:
                            data={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                            pred=get_ai_prediction(data); update_league_history(db, user, f["league"])
                            send_message(chat_id, f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} {f['time']}\n🎯 {pred['best_pick']} | ✅ {pred['verdict']}\n{pred['stake']}{pred['disclaimer']}\n💬 {BOT_HANDLE}")
                        user.daily_count+=1; db.commit()

                    elif "vs" in low and 5 < len(text) < 100:
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit}. I remember even if you clear chat.\n\n💎 Upgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}"); continue
                        try: home, away = [x.strip().title() for x in text.lower().split("vs")][:2]
                        except: home=text.title(); away="Opponent"
                        league_guess = user.favorite_league if user.is_vip else "Custom"
                        # Detect national team
                        if any(c in home.lower() for c in ["nigeria","england","brazil","ghana","france"]) and any(c in away.lower() for c in ["nigeria","england","brazil","ghana","france","germany"]):
                            league_guess = "National Teams - International"
                        data={"home":
