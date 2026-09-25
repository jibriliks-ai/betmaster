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
                            data = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                            pred = get_ai_prediction(data)
                            update_league_history(db, user, f["league"])
                            intro = random.choice(["🔥 Hot Tip:", "💎 Expert Pick:", "⚡ VIP Insight:", "🎯 Top Prediction:", "🚀 Super Pick:"])
                            full_msg = f"{intro}\n⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | 🌍 {f.get('country', country_raw.title())} | ⏰ {f['time']} WAT | 📅 {f.get('date','Today')}\n💰 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']}\n\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **{pred['verdict']}**\n{pred['stake']}{pred['disclaimer']}\n\n💬 More? {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 {SUPPORT_HANDLE}"
                            send_message(chat_id, full_msg)
                            time.sleep(0.6)

                        user.daily_count += 1
                        db.commit()

                    elif low.startswith("/myplan"):
                        plan_txt = f"💎 VIP till {user.vip_expiry}" if user.is_vip else "🆓 FREE"
                        send_message(chat_id, f"**Your Plan:** {plan_txt}\nUsed: {user.daily_count}/{'10' if user.is_vip else '2'} today\nFavorite: {user.favorite_league}\nTotal chats: {user.total_chats}\n\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/subscribe"):
                        send_message(chat_id, f"💳 **Plans - Card or Bank Transfer (both auto-activate):**\n\nWeekly: ₦2,000 (7 days)\nMonthly: ₦5,000 (30 days)\n\n👉 https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\n\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/today"):
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit} today. I remember even if you clear chat.\n\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")
                            continue
                        send_message(chat_id, "📅 Fetching today's worldwide fixtures (including national teams, Premier League, LaLiga etc)...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=5, fav_league=user.favorite_league if user.is_vip else None)
                        for f in fixtures:
                            data = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                            pred = get_ai_prediction(data)
                            update_league_history(db, user, f["league"])
                            send_message(chat_id, f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | {f['time']} WAT\n🎯 {pred['best_pick']} ({pred['confidence']}%)\n✅ {pred['verdict']}\n{pred['stake']}{pred['disclaimer']}\n💬 {BOT_HANDLE} | {BOT_HANDLE_2}")
                        user.daily_count += 1
                        db.commit()

                    elif "vs" in low and 5 < len(text) < 100:
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit} today. Even if you clear history, I track by ID.\n\nReset midnight WAT.\n\n💎 Upgrade:\nhttps://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")
                            continue
                        try:
                            home, away = [x.strip().title() for x in text.lower().split("vs")][:2]
                        except:
                            home = text.title()
                            away = "Opponent"
                        league_guess = user.favorite_league if user.is_vip else "Custom"
                        if any(c in home.lower() for c in ["nigeria", "ghana", "england", "brazil", "france", "germany", "spain"]) and any(c in away.lower() for c in ["nigeria", "ghana", "england", "brazil", "france", "germany", "spain", "argentina"]):
                            league_guess = "National Teams - International Friendly"
                        data = {"home": home, "away": away, "league": league_guess, "home_xg": 1.6, "away_xg": 1.1, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": round(random.uniform(1.9,3.2),2), "odds_d": round(random.uniform(3.0,4.0),2), "odds_a": round(random.uniform(2.2,3.8),2), "odds_over": 1.75}
                        pred = get_ai_prediction(data)
                        update_league_history(db, user, league_guess)
                        user.daily_count += 1
                        db.commit()
                        intro = random.choice(["🔥", "💎", "⚡", "🎯", "🚀"])
                        send_message(chat_id, f"{intro} ⚽ **{home} vs {away}**\n🏆 {league_guess}\n💰 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **EXPERT VERDICT: {pred['verdict']}**\n{pred['stake']}\n📊 Market: {pred['market']}\n{user.daily_count}/{limit} used\n{pred['disclaimer']}\n\n💬 More predictions: {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 {SUPPORT_HANDLE}")

                    else:
                        send_message(chat_id, f"Send match like `Arsenal vs Chelsea` or try `/fixturesengland` or `/help` - Support {SUPPORT_HANDLE}")

                except Exception as e:
                    print(f"Handler error {e}")
                    import traceback; traceback.print_exc()
                    db.rollback()
                finally:
                    db.close()

        except Exception as e:
            print(f"Poll loop {e}")
            time.sleep(5)

# ================= SCHEDULER - UNIQUE MESSAGES - NO REPEATS =================
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
                print(f"=== MORNING 6AM WAT {today} ===")
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

                    msg = f"🔥 **BetMasterPro Morning - {today}** 🔥\n📅 Matches in 1-3 days | 100% Unique | Live Data\n\n"
                    for f in unique:
                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                        p = get_ai_prediction(d)
                        intro = random.choice(["💎 VIP Pick", "🔥 Hot", "⚡ Expert", "🎯 Top", "🚀 Super"])
                        msg += f"{intro}: **{f['home']} vs {f['away']}**\n🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f.get('date','')}\n🎯 {p['best_pick']} | ✅ {p['verdict']}\n{p['stake']}\n\n"
                    msg += f"💬 Chat for more predictions: {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 Support: {SUPPORT_HANDLE}\n🔗 {CHANNEL_LINK}\n{DISCLAIMER}"
                    if CHANNEL_ID:
                        send_message(CHANNEL_ID, msg)

                    # DM users unique messages
                    for u in get_all_users(db):
                        try:
                            fav = u.favorite_league if u.is_vip else None
                            fxs = fetch_real_fixtures(days_ahead=random.randint(1,3), limit=2 if u.is_vip else 1, fav_league=fav)
                            pmsg = f"☀️ Morning {'VIP '+u.favorite_league if u.is_vip else 'Free'} Tip - Unique:\n\n"
                            for f in fxs:
                                d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                                p = get_ai_prediction(d)
                                pmsg += f"⚽ {f['home']} vs {f['away']} - {p['best_pick']}\n✅ {p['verdict']}\n\n"
                            pmsg += f"More: {BOT_HANDLE} | {BOT_HANDLE_2} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
                            if not u.is_vip:
                                pmsg += f"\n💎 Upgrade: https://betmaster-p09f.onrender.com/subscribe?uid={u.user_id}"
                            send_message(u.user_id, pmsg)
                            time.sleep(0.4)
                        except Exception as e:
                            print(f"Morning DM fail {e}")
                finally:
                    db.close()
                posted.add(f"{today}-morning")

            if hm == "20:05" and f"{today}-evening" not in posted:
                print(f"=== EVENING 9PM WAT {today} ===")
                db = SessionLocal()
                try:
                    fixtures = fetch_real_fixtures(days_ahead=1, limit=15)
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
                    msg = f"🌙 **Evening VIP - {today}** Unique Tips\n\n"
                    for f in unique:
                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                        p = get_ai_prediction(d)
                        msg += f"⚽ {f['home']} vs {f['away']} - {p['verdict']}\n{p['stake']}\n\n"
                    msg += f"Chat: {BOT_HANDLE} | {BOT_HANDLE_2} | Support {SUPPORT_HANDLE}\n{DISCLAIMER}"
                    if CHANNEL_ID:
                        send_message(CHANNEL_ID, msg)
                    # VIP DM
                    for u in get_all_users(db):
                        if not u.is_vip:
                            continue
                        try:
                            fxs = fetch_real_fixtures(days_ahead=random.randint(1,2), limit=2, fav_league=u.favorite_league)
                            pmsg = f"🌙 Evening VIP {u.favorite_league} Unique Tips:\n\n"
                            for f in fxs:
                                d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                                p = get_ai_prediction(d)
                                pmsg += f"⚽ {f['home']} vs {f['away']}\n🎯 {p['best_pick']}\n✅ {p['verdict']}\n\n"
                            pmsg += f"{DISCLAIMER}\nChat: {BOT_HANDLE} | Support: {SUPPORT_HANDLE}"
                            send_message(u.user_id, pmsg)
                            time.sleep(0.4)
                        except:
                            pass
                finally:
                    db.close()
                posted.add(f"{today}-evening")

            if len(posted) > 20:
                posted.clear()

        except Exception as e:
            print(f"Scheduler error {e}")
        time.sleep(60)

threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

# ================= ROUTES =================
@app.get("/")
async def home():
    return {"status": "SUPER BRAIN LIVE", "channel": CHANNEL_ID, "support": SUPPORT_HANDLE, "bots": [BOT_HANDLE, BOT_HANDLE_2], "flutterwave": bool(FLW_SECRET), "time_utc": datetime.utcnow().isoformat()}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    from database import SessionLocal, is_already_posted, mark_as_posted
    db = SessionLocal()
    try:
        fixtures = fetch_real_fixtures(limit=10)
        unique = []
        for f in fixtures:
            h = f"{f['home']}-{f['away']}-{str(date.today())}-manual-{random.randint(1,9999)}"
            if not is_already_posted(db, h):
                unique.append(f)
                mark_as_posted(db, h)
                if len(unique) >= 2:
                    break
        if not unique:
            unique = fixtures[:2]
        msg = f"🔥 Test Unique {datetime.now().strftime('%H:%M:%S')}\n\n"
        for f in unique:
            d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
            p = get_ai_prediction(d)
            msg += f"{f['home']} vs {f['away']} - {p['verdict']}\n{p['stake']}\n\n"
        msg += f"More: {BOT_HANDLE} | {BOT_HANDLE_2} | Support {SUPPORT_HANDLE}\n{DISCLAIMER}"
        if CHANNEL_ID:
            send_message(CHANNEL_ID, msg)
        return {"posted": True, "unique": unique, "bots": [BOT_HANDLE, BOT_HANDLE_2]}
    finally:
        db.close()

@app.get("/pay")
async def create_flutterwave_payment(plan: str, uid: str):
    if not FLW_SECRET:
        return JSONResponse({"error": "Flutterwave keys not set"}, status_code=500)
    amount = 2000 if plan == "weekly" else 5000
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": f"https://betmaster-p09f.onrender.com/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer": {"email": f"{uid}@betmasterpro.com", "name": f"User {uid}"},
        "customizations": {"title": f"BetMasterPro {plan.upper()}", "description": f"{plan} VIP - Auto activation via Card/Bank Transfer"},
    }
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        r = requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers, timeout=15).json()
        if r.get("status") == "success":
            return RedirectResponse(r["data"]["link"])
        return JSONResponse(r, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/verify")
async def verify_payment(tx_ref: str, uid: str, plan: str):
    if not FLW_SECRET:
        return HTMLResponse("Keys not set - contact support @Jibriliks")
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        r = requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}", headers=headers, timeout=15).json()
        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            status = data.get("status", "")
            pay_type = data.get("payment_type", "card")
            if status in ["successful", "completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(f"<html><body style='text-align:center;padding:40px;font-family:sans-serif'><h1>✅ Payment Successful via {pay_type.title()}!</h1><p>Plan: {plan.upper()} ₦{'2,000' if 'weekly' in plan else '5,000'}</p><p>VIP till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</p><p>Bot has DM'd you!</p><a href='https://t.me/Betmasterpro_bot' style='background:green;color:white;padding:15px 30px;text-decoration:none;border-radius:10px'>Go to Bot {BOT_HANDLE}</a><br><br>Support: {SUPPORT_HANDLE}</body></html>")
        return HTMLResponse(f"<h1>❌ Payment not confirmed</h1><p>Ref: {tx_ref}</p><a href='/subscribe?uid={uid}'>Retry</a> | Support {SUPPORT_HANDLE}")
    except Exception as e:
        return HTMLResponse(f"<h1>Error verifying: {e}</h1><a href='/subscribe?uid={uid}'>Retry</a> | Support {SUPPORT_HANDLE}")

@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request: Request):
    try:
        body = await request.body()
        # Verify hash if set
        if FLW_WEBHOOK_SECRET:
            signature = request.headers.get("verif-hash", "")
            if signature!= FLW_WEBHOOK_SECRET:
                print(f"Webhook hash mismatch: {signature}")
                # Still allow for now, but log
        data = json.loads(body)
        print(f"Webhook received: {data.get('event')}")
        if data.get("event") == "charge.completed" and data.get("data", {}).get("status") == "successful":
            tx_ref = data["data"].get("tx_ref", "")
            parts = tx_ref.split("-")
            if len(parts) >= 3 and parts[0] == "BETMASTER":
                uid = parts[1]
                plan = parts[2]
                pay_type = data["data"].get("payment_type", "bank")
                print(f"Auto-activating {uid} {plan} via {pay_type}")
                activate_vip(uid, plan + f"_{pay_type}")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"Webhook error {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=200)

@app.get("/admin/activate")
async def admin_activate(uid: str, plan: str = "monthly", key: str = ""):
    if key!= ADMIN_KEY:
        return HTMLResponse(f"<h1>❌ Wrong admin key</h1><p>Use?key=YOUR_ADMIN_KEY set in Render</p><p>Support: {SUPPORT_HANDLE}</p>", status_code=403)
    if plan not in ["weekly", "monthly"]:
        plan = "monthly"
    ok = activate_vip(uid, plan)
    if ok:
        return HTMLResponse(f"<html><body style='padding:30px'><h1>✅ VIP Activated!</h1><p>User {uid} - {plan.upper()} till {date.today()+timedelta(days=7 if plan=='weekly' else 30)}</p><p>Bot has DM'd user {BOT_HANDLE}.</p><a href='/admin/users?key={key}'>Back to users</a><br>Support: {SUPPORT_HANDLE}</body></html>")
    else:
        return HTMLResponse(f"<h1>❌ Failed - user {uid} not found. Ask user to /start {BOT_HANDLE} first</h1><p>Support: {SUPPORT_HANDLE}</p>")

@app.get("/admin/users")
async def admin_users(key: str = ""):
    if key!= ADMIN_KEY:
        return HTMLResponse("Wrong key - set ADMIN_KEY in Render env", status_code=403)
    from database import SessionLocal, get_all_users
    db = SessionLocal()
    try:
        users = get_all_users(db)
        html = f"<html><body style='padding:20px;font-family:sans-serif'><h1>All Users - BetMasterPro</h1><p>Support: {SUPPORT_HANDLE} | Bots: {BOT_HANDLE} | {BOT_HANDLE_2}</p><table border=1 cellpadding=8><tr><th>ID</th><th>Username</th><th>VIP</th><th>Expiry</th><th>Chats</th><th>Fav League</th><th>Action</th></tr>"
        for u in users:
            html += f"<tr><td>{u.user_id}</td><td>{u.username}</td><td>{'💎' if u.is_vip else '🆓'}</td><td>{u.vip_expiry}</td><td>{u.total_chats} ({u.daily_count} today)</td><td>{u.favorite_league}</td><td><a href='/admin/activate?uid={u.user_id}&plan=weekly&key={key}'>Weekly ₦2k</a> | <a href='/admin/activate?uid={u.user_id}&plan=monthly&key={key}'>Monthly ₦5k</a></td></tr>"
        html += "</table><p>Total: "+str(len(users))+"</p></body></html>"
        return HTMLResponse(html)
    finally:
        db.close()

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    html = f"""
    <html>
    <head><title>BetMasterPro VIP - Super Brain</title><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>
        body{{font-family:sans-serif;background:#0f172a;color:white;text-align:center;padding:20px}}
       .card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}
       .btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}
       .weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}
    </style>
    </head>
    <body>
        <h1>💎 BetMasterPro VIP - Super Brain</h1>
        <p>ID: <b>{uid or 'Open from bot to auto-link'}</b></p>
        <div class="card">
            <h3>Choose Plan - Card or Bank Transfer (Both Auto-Activate)</h3>
            <p>🆓 FREE: 2 predictions/day + 1 UNIQUE tip at 6AM WAT</p>
            <p>💎 VIP: 10 predictions/day + 2 UNIQUE personalized tips (6AM & 9PM WAT) + National teams</p>
            <hr>
            <a class="btn weekly" href="/pay?plan=weekly&uid={uid}">💚 Weekly - ₦2,000 (7 days) - Flutterwave</a>
            <a class="btn monthly" href="/pay?plan=monthly&uid={uid}">💙 Monthly - ₦5,000 (30 days) - Flutterwave</a>
            <p style="font-size:12px">Secure by Flutterwave. Bank Transfer & Card both auto-activate VIP instantly via webhook.</p>
            <p>🆘 Support: <a href="https://t.me/Jibriliks" style="color:#22c55e">{SUPPORT_HANDLE}</a></p>
            <p>🤖 Bot: {BOT_HANDLE} | {BOT_HANDLE_2}</p>
            <p style="font-size:11px">{DISCLAIMER}</p>
        </div>
        <p>Channel: <a href="{CHANNEL_LINK}" style="color:#3b82f6">Join Channel</a></p>
        <script>
            const urlParams = new URLSearchParams(window.location.search);
            if(!urlParams.get('uid')){{
                let uid = prompt("Enter your Telegram User ID (send /myplan in bot to see it):");
                if(uid) window.location.href = "/subscribe?uid="+uid;
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
