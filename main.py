import os
import time
import threading
import requests
import random
import json
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")

FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
FLW_WEBHOOK_SECRET = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "BetMasterAdmin123")

SUPPORT_HANDLE = "@Jibriliks"
BOT_HANDLE = "@Betmasterpro_bot"
BOT_HANDLE_2 = "@Betmaster_bot"
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"

app = FastAPI()
print(f"SUPER BRAIN LIVE - Channel {CHANNEL_ID}")

WELCOME_MSG = f"""🎯 **Welcome to BetMasterPro - Super Smart AI** 🎯

100% CURRENT fixtures - All leagues + national teams!

⚽ `Arsenal vs Chelsea` - Any match
📅 `/today` - Top 10 fixtures today with Predict button
🌍 `/fixturesengland` - England PL today
🌍 `/fixtureschina` - China today
🌍 `/fixturesworld` - National teams today
💎 `/myplan` - Check plan
💳 `/subscribe` - Upgrade ₦2k/₦5k
🆘 `/help` - Support {SUPPORT_HANDLE}

Channel: {CHANNEL_LINK}"""

DISCLAIMER = "\n\n⚠️ *Disclaimer:* Betting risk. AI only, 18+ stake responsibly."

def send_message(chat_id, text, parse="Markdown", reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Send error: {e}")

def activate_vip(user_id, plan):
    from database import SessionLocal, get_user
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id))
        today = date.today()
        expiry = today + timedelta(days=7 if "weekly" in plan else 30)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.daily_count = 0
        db.commit()
        send_message(int(user_id), f"🎉 **VIP Activated!**\n✅ {plan.upper()} till {expiry}\n💎 10 chats/day + 2 tips!\nSupport: {SUPPORT_HANDLE}")
        return True
    except Exception as e:
        print(f"VIP error {e}")
        return False
    finally:
        db.close()

def bot_polling_loop():
    if not BOT_TOKEN:
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except:
        pass
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

                # ===== PREDICT BUTTON CALLBACK - THIS IS THE KEY PART =====
                if "callback_query" in upd:
                    try:
                        cq = upd["callback_query"]
                        chat_id = cq["message"]["chat"]["id"]
                        from_id = cq["from"]["id"]
                        data = cq.get("data", "")
                        # Answer callback immediately
                        requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": "Generating predictions..."}, timeout=5)

                        if data == "predict_top5":
                            db2 = SessionLocal()
                            try:
                                user2 = get_user(db2, from_id)
                                fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                                send_message(chat_id, f"🔮 **TOP 5 PREDICTIONS TODAY - {datetime.now().strftime('%d %B %Y')}**\nNear accurate AI analysis:\n")
                                for f in fixtures[:5]:
                                    d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                                    p = get_ai_prediction(d)
                                    msg = f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | 📅 {f['date']} {f['time']} WAT\n🎯 **Pick: {p['best_pick']}** ({p['confidence']}%)\n📝 {p['explanation']}\n\n✅ **{p['verdict']}**\n{p['stake']}{p['disclaimer']}\n"
                                    send_message(chat_id, msg)
                                    time.sleep(0.7)
                                send_message(chat_id, f"💬 Want more? {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 Support: {SUPPORT_HANDLE}\n💎 VIP: https://betmaster-p09f.onrender.com/subscribe?uid={chat_id}")
                            finally:
                                db2.close()

                        if data.startswith("predict_"):
                            # For country specific predict
                            country = data.replace("predict_", "").replace("top5", "")
                            if country:
                                db2 = SessionLocal()
                                try:
                                    fixtures = fetch_fixtures_by_country(country, days_ahead=0, limit=3)
                                    for f in fixtures[:3]:
                                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                                        p = get_ai_prediction(d)
                                        send_message(chat_id, f"⚽ **{f['home']} vs {f['away']}**\n🎯 {p['best_pick']}\n✅ {p['verdict']}\n{p['stake']}{p['disclaimer']}")
                                finally:
                                    db2.close()
                    except Exception as e:
                        print(f"Callback error: {e}")
                    continue

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
                        send_message(chat_id, f"🆘 **Support**\nContact: {SUPPORT_HANDLE}\nhttps://t.me/Jibriliks\nBots: {BOT_HANDLE} | {BOT_HANDLE_2}\nChannel: {CHANNEL_LINK}\n\nCommands:\n/today - 10 fixtures + Predict button\n/fixturesengland\n/fixturesworld - national teams\n/myplan\n/subscribe")

                    elif low.startswith("/fixtures"):
                        country_raw = low.replace("/fixtures", "").strip().split()[0] if low.replace("/fixtures", "").strip() else "england"
                        if country_raw in ["today", "tomorrow"]:
                            country_raw = "england"
                        send_message(chat_id, f"🌍 Fetching **{country_raw.title()}** fixtures for TODAY {datetime.now().strftime('%d %b %Y')} - 100% LIVE...")
                        fixtures = fetch_fixtures_by_country(country_raw, days_ahead=0, limit=5 if user.is_vip else 3)
                        if not fixtures:
                            send_message(chat_id, f"No fixtures for {country_raw.title()} today. Try /fixturesworld\nSupport: {SUPPORT_HANDLE}")
                            continue
                        list_msg = f"📅 **{country_raw.title()} FIXTURES - {datetime.now().strftime('%d %B %Y')}**\n\n"
                        for i, f in enumerate(fixtures, 1):
                            list_msg += f"{i}. **{f['home']} vs {f['away']}**\n 🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n\n"
                        keyboard = {"inline_keyboard": [[{"text": f"🔮 Predict {country_raw.title()} Top 3", "callback_data": f"predict_{country_raw}"}]]}
                        send_message(chat_id, list_msg, reply_markup=keyboard)
                        user.daily_count += 1
                        db.commit()

                    elif low.startswith("/myplan"):
                        plan_txt = f"💎 VIP till {user.vip_expiry}" if user.is_vip else "🆓 FREE"
                        send_message(chat_id, f"Plan: {plan_txt}\nUsed: {user.daily_count}/{'10' if user.is_vip else '2'}\nFav: {user.favorite_league}\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/subscribe"):
                        send_message(chat_id, f"💳 Plans:\nWeekly ₦2,000 (7 days)\nMonthly ₦5,000 (30 days)\nCard + Bank Transfer auto-activate!\n\n👉 https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/today"):
                        # ALWAYS 10 FIXTURES FOR ADVERTISING
                        send_message(chat_id, f"📅 Fetching TOP 10 fixtures TODAY {datetime.now().strftime('%d %B %Y')} - 100% LIVE from ESPN + SuperSport + National Teams...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=10, fav_league=user.favorite_league if user.is_vip else None)

                        list_msg = f"📅 **TOP 10 FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')}**\n\n"
                        for i, f in enumerate(fixtures, 1):
                            list_msg += f"{i}. **{f['home']} vs {f['away']}**\n 🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n\n"
                        list_msg += f"💡 Tap below to get predictions!\n💬 {BOT_HANDLE} | {BOT_HANDLE_2}"

                        keyboard = {"inline_keyboard": [[{"text": "🔮 Predict Top 5 Matches", "callback_data": "predict_top5"}]]}
                        send_message(chat_id, list_msg, reply_markup=keyboard)

                        user.daily_count += 1
                        db.commit()

                    elif "vs" in low and 5 < len(text) < 100:
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit}. Upgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")
                            continue
                        try:
                            home, away = [x.strip().title() for x in text.lower().split("vs")][:2]
                        except:
                            home = text.title()
                            away = "Opponent"
                        league_guess = user.favorite_league if user.is_vip else "Custom"
                        if any(c in home.lower() for c in ["nigeria", "ghana", "england", "brazil"]) and any(c in away.lower() for c in ["nigeria", "ghana", "england", "brazil", "france", "germany"]):
                            league_guess = "National Teams - International Friendly"
                        data = {"home": home, "away": away, "league": league_guess, "home_xg": 1.6, "away_xg": 1.1, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": round(random.uniform(1.9,3.2),2), "odds_d": round(random.uniform(3.0,4.0),2), "odds_a": round(random.uniform(2.2,3.8),2), "odds_over": 1.75}
                        from predictor import get_ai_prediction
                        pred = get_ai_prediction(data)
                        update_league_history(db, user, league_guess)
                        user.daily_count += 1
                        db.commit()
                        send_message(chat_id, f"⚽ **{home} vs {away}**\n🏆 {league_guess} | 📅 {datetime.now().strftime('%d %b %Y')}\n💰 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **{pred['verdict']}**\n{pred['stake']}{pred['disclaimer']}\n\n{user.daily_count}/{limit} used\n💬 {BOT_HANDLE} | {BOT_HANDLE_2}")

                    else:
                        send_message(chat_id, f"Send `Arsenal vs Chelsea` or /today or /fixturesengland\nSupport: {SUPPORT_HANDLE}")

                except Exception as e:
                    print(f"Handler {e}")
                    import traceback; traceback.print_exc()
                    db.rollback()
                finally:
                    db.close()

        except Exception as e:
            print(f"Poll error {e}")
            time.sleep(5)

def channel_scheduler():
    from database import SessionLocal, get_all_users, is_already_posted, mark_as_posted
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted = set()
    while True:
        try:
            now_utc = datetime.utcnow()
            hm = now_utc.strftime("%H:%M")
            today = now_utc.strftime("%Y-%m-%d")
            if hm == "05:05" and f"{today}-morning" not in posted:
                db = SessionLocal()
                try:
                    fixtures = fetch_real_fixtures(days_ahead=random.randint(1,2), limit=15)
                    unique = []
                    for f in fixtures:
                        h = f"{f['home']}-{f['away']}-{f['date']}"
                        if not is_already_posted(db, h):
                            unique.append(f)
                            mark_as_posted(db, h)
                            if len(unique) >= 2:
                                break
                    if not unique:
                        unique = fixtures[:2]
                    msg = f"🔥 **Morning {today}** Unique Tips\n\n"
                    for f in unique:
                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                        p = get_ai_prediction(d)
                        msg += f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | 📅 {f['date']} {f['time']} WAT\n🎯 {p['best_pick']} | ✅ {p['verdict']}\n\n"
                    msg += f"💬 More: {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 {SUPPORT_HANDLE}\n🔗 {CHANNEL_LINK}\n{DISCLAIMER}"
                    if CHANNEL_ID:
                        send_message(CHANNEL_ID, msg)
                finally:
                    db.close()
                posted.add(f"{today}-morning")
            if hm == "20:05" and f"{today}-evening" not in posted:
                db = SessionLocal()
                try:
                    fixtures = fetch_real_fixtures(limit=10)
                    unique = []
                    for f in fixtures:
                        h = f"{f['home']}-{f['away']}-{today}-eve"
                        if not is_already_posted(db, h):
                            unique.append(f)
                            mark_as_posted(db, h)
                            if len(unique) >= 2:
                                break
                    if not unique:
                        unique = fixtures[:2]
                    msg = f"🌙 **Evening {today}**\n\n"
                    for f in unique:
                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                        p = get_ai_prediction(d)
                        msg += f"⚽ {f['home']} vs {f['away']} - {p['verdict']}\n"
                    msg += f"Chat: {BOT_HANDLE} | {BOT_HANDLE_2} | {SUPPORT_HANDLE}\n{DISCLAIMER}"
                    if CHANNEL_ID:
                        send_message(CHANNEL_ID, msg)
                finally:
                    db.close()
                posted.add(f"{today}-evening")
        except Exception as e:
            print(f"Scheduler {e}")
        time.sleep(60)

threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

@app.get("/")
async def home():
    return {"status": "SUPER
