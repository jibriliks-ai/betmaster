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
    return {"status": "SUPER BRAIN LIVE WITH PREDICT BUTTON", "support": SUPPORT_HANDLE, "bots": [BOT_HANDLE, BOT_HANDLE_2]}

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
        msg = f"🔥 Test {datetime.now().strftime('%H:%M:%S')}\n\n"
        for f in unique:
            d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
            p = get_ai_prediction(d)
            msg += f"{f['home']} vs {f['away']} - {p['verdict']}\n"
        msg += f"More: {BOT_HANDLE} | {BOT_HANDLE_2} | {SUPPORT_HANDLE}\n{DISCLAIMER}"
        if CHANNEL_ID:
            send_message(CHANNEL_ID, msg)
        return {"posted": True, "unique": unique}
    finally:
        db.close()

@app.get("/pay")
async def create_payment(plan: str, uid: str):
    if not FLW_SECRET:
        return JSONResponse({"error": "Keys not set"}, status_code=500)
    amount = 2000 if plan == "weekly" else 5000
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": f"https://betmaster-p09f.onrender.com/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer": {"email": f"{uid}@betmasterpro.com", "name": f"User {uid}"},
        "customizations": {"title": f"BetMasterPro {plan.upper()}"},
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
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        r = requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}", headers=headers, timeout=15).json()
        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ["successful", "completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(f"<h1>✅ Payment Successful!</h1><p>{plan.upper()} till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</p><a href='https://t.me/Betmasterpro_bot'>Go to Bot</a><br>Support: {SUPPORT_HANDLE}")
        return HTMLResponse(f"<h1>❌ Not confirmed {tx_ref}</h1><a href='/subscribe?uid={uid}'>Retry</a>")
    except Exception as e:
        return HTMLResponse(f"Error {e}")

@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request: Request):
    try:
        body = await request.body()
        if FLW_WEBHOOK_SECRET:
            signature = request.headers.get("verif-hash", "")
            if signature!= FLW_WEBHOOK_SECRET:
                print(f"Hash mismatch")
        data = json.loads(body)
        if data.get("event") == "charge.completed" and data.get("data", {}).get("status") == "successful":
            tx_ref = data["data"].get("tx_ref", "")
            parts = tx_ref.split("-")
            if len(parts) >= 3 and parts[0] == "BETMASTER":
                uid = parts[1]
                plan = parts[2]
                activate_vip(uid, plan)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"Webhook {e}")
        return JSONResponse({"status": "error"}, status_code=200)

@app.get("/admin/activate")
async def admin_activate(uid: str, plan: str = "monthly", key: str = ""):
    if key!= ADMIN_KEY:
        return HTMLResponse(f"❌ Wrong key. Use?key={ADMIN_KEY}", status_code=403)
    ok = activate_vip(uid, plan)
    return HTMLResponse(f"{'✅ Activated' if ok else '❌ Failed'} {uid} {plan} - Support {SUPPORT_HANDLE}")

@app.get("/admin/users")
async def admin_users(key: str = ""):
    if key!= ADMIN_KEY:
        return HTMLResponse("Wrong key", status_code=403)
    from database import SessionLocal, get_all_users
    db = SessionLocal()
    try:
        users = get_all_users(db)
        html = f"<h1>Users - Support {SUPPORT_HANDLE}</h1><table border=1><tr><th>ID</th><th>VIP</th><th>Expiry</th><th>Action</th></tr>"
        for u in users:
            html += f"<tr><td>{u.user_id}</td><td>{'💎' if u.is_vip else '🆓'}</td><td>{u.vip_expiry}</td><td><a href='/admin/activate?uid={u.user_id}&plan=weekly&key={key}'>Weekly</a> | <a href='/admin/activate?uid={u.user_id}&plan=monthly&key={key}'>Monthly</a></td></tr>"
        html += "</table>"
        return HTMLResponse(html)
    finally:
        db.close()

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    html = f"""
    <html><head><title>BetMasterPro VIP</title><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{font-family:sans-serif;background:#0f172a;color:white;text-align:center;padding:20px}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}</style></head>
    <body><h1>💎 BetMasterPro VIP</h1><p>ID: <b>{uid}</b></p>
    <div class="card"><a class="btn weekly" href="/pay?plan=weekly&uid={uid}">💚 Weekly ₦2,000 - Flutterwave</a>
    <a class="btn monthly" href="/pay?plan=monthly&uid={uid}">💙 Monthly ₦5,000 - Flutterwave</a>
    <p>Bank Transfer & Card auto-activate</p><p>Support: {SUPPORT_HANDLE}</p><p>Bot: {BOT_HANDLE} | {BOT_HANDLE_2}</p></div></body></html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
