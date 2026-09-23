import os, time, threading, requests, random
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")

FLW_PUBLIC = os.getenv("FLUTTERWAVE_PUBLIC_KEY","")
FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY","")
FLW_ENC = os.getenv("FLUTTERWAVE_ENCRYPTION_KEY","")
PAYSTACK_PUBLIC = os.getenv("PAYSTACK_PUBLIC_KEY","")

app = FastAPI()

WELCOME_MSG = """🎯 **Welcome to BetMasterPro** 🎯

Your AI football prediction expert!

⚽ Send: `Arsenal vs Chelsea`
📅 Today: `/today`
💎 Plan: `/myplan`
💳 Upgrade: `/subscribe`

🆓 FREE: 2 chats/day + 1 tip 6AM WAT
💎 VIP: 10 chats/day + 2 personalized tips (6AM & 9PM WAT)

Join: https://t.me/+IFK0qoDI2B5lYWI0"""

DISCLAIMER = "\n\n⚠️ *Disclaimer:* Betting involves risk. AI analysis, not financial advice. Stake responsibly, 18+ only."

def send_message(chat_id, text, parse="Markdown"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000: text = text[:4000]+"..."
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse}, timeout=15)
    except Exception as e:
        print(f"Send error: {e}")

# ========== PAYMENT VERIFICATION ==========
def activate_vip(user_id, plan):
    """Activate VIP after payment"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        from database import get_user
        user = get_user(db, int(user_id))
        today = date.today()
        if plan == "weekly":
            expiry = today + timedelta(days=7)
        else: # monthly
            expiry = today + timedelta(days=30)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.daily_count = 0 # reset so they can use immediately
        db.commit()
        print(f"VIP activated: {user_id} {plan} till {expiry}")
        # Notify user via bot
        send_message(int(user_id), f"🎉 **VIP Activated!**\n\n✅ Plan: {plan.upper()} (₦{'2,000' if plan=='weekly' else '5,000'})\n📅 Valid till: {expiry}\n💎 You now have 10 chats/day + 2 personalized tips daily!\n\nSend any match: `Arsenal vs Chelsea`")
        return True
    except Exception as e:
        print(f"VIP activation error: {e}")
        return False
    finally:
        db.close()

# ========== BOT LOOP (same as before, with subscribe link with uid) ==========
def bot_polling_loop():
    if not BOT_TOKEN: return
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass
    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_real_fixtures
    offset = 0
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    while True:
        try:
            resp = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30).json()
            if not resp.get("ok"): time.sleep(5); continue
            for upd in resp.get("result", []):
                offset = upd["update_id"]+1
                msg = upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!="private": continue
                chat_id = msg["chat"]["id"]; text = msg["text"].strip(); user_id = msg["from"]["id"]; username = msg["from"].get("username","")
                db = SessionLocal()
                try:
                    user = get_user(db, user_id, username)
                    if text.lower().startswith("/start"):
                        send_message(chat_id, WELCOME_MSG + f"\n\n💳 Upgrade:\nhttps://betmaster-p09f.onrender.com/subscribe?uid={user_id}")
                    elif text.lower().startswith("/myplan"):
                        plan = "💎 VIP" if user.is_vip else "🆓 FREE"
                        send_message(chat_id, f"Plan: {plan} ({user.daily_count}/{'10' if user.is_vip else '2'})\nFav: {user.favorite_league}\nExpiry: {user.vip_expiry or 'N/A'}\n\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}")
                    elif text.lower().startswith("/subscribe"):
                        send_message(chat_id, f"💳 **Choose Plan:**\n\nWeekly: ₦2,000 (7 days)\nMonthly: ₦5,000 (30 days)\n\nPay here:\nhttps://betmaster-p09f.onrender.com/subscribe?uid={user_id}\n\nFlutterwave + Paystack accepted!")
                    elif text.lower().startswith("/today"):
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit}. Upgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}")
                            continue
                        send_message(chat_id, "📅 Fetching today's matches...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=5, fav_league=user.favorite_league if user.is_vip else None)
                        for f in fixtures:
                            data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                            pred = get_ai_prediction(data); update_league_history(db, user, f["league"])
                            send_message(chat_id, f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} {f['time']}\n🎯 {pred['best_pick']} ({pred['confidence']}%)\n✅ {pred['verdict']}\n{pred['stake']}{pred['disclaimer']}")
                        user.daily_count+=1; db.commit()
                    elif "vs" in text.lower() and 5 < len(text) < 100:
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 Limit {user.daily_count}/{limit} today. Even clearing chat, I remember. Reset midnight WAT.\n\n💎 Upgrade:\nhttps://betmaster-p09f.onrender.com/subscribe?uid={user_id}")
                            continue
                        try: home, away = [x.strip().title() for x in text.lower().split("vs")][:2]
                        except: home=text.title(); away="Opponent"
                        league_guess = user.favorite_league if user.is_vip else "Premier League"
                        data = {"home":home,"away":away,"league":league_guess,"home_xg":1.6,"away_xg":1.1,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":2.1,"odds_d":3.2,"odds_a":3.4,"odds_over":1.75}
                        pred = get_ai_prediction(data); update_league_history(db, user, league_guess); user.daily_count+=1; db.commit()
                        send_message(chat_id, f"⚽ **{home} vs {away}**\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **{pred['verdict']}**\n{pred['stake']}{pred['disclaimer']}\n\n{user.daily_count}/{limit} used")
                    else:
                        send_message(chat_id, f"Send `Arsenal vs Chelsea` or /today or /subscribe?uid={user_id}")
                except Exception as e:
                    print(e); db.rollback()
                finally: db.close()
        except Exception as e:
            print(f"Poll error {e}"); time.sleep(5)

def channel_scheduler():
    from database import SessionLocal, get_all_users
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted=set()
    while True:
        try:
            now_utc=datetime.utcnow(); hm=now_utc.strftime("%H:%M"); today=now_utc.strftime("%Y-%m-%d")
            if hm=="05:05" and f"{today}-morning" not in posted:
                fixtures=fetch_real_fixtures(days_ahead=random.randint(1,2), limit=2)
                msg=f"🔥 **Morning Tips {today}**\n\n"
                for f in fixtures:
                    d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
                    msg+=f"⚽ **{f['home']} vs {f['away']}** {f['league']}\n🎯 {p['best_pick']} | ✅ {p['verdict']}\n\n"
                msg+=f"Bot @Betmasterpro_bot {DISCLAIMER}"
                if CHANNEL_ID: send_message(CHANNEL_ID, msg)
                # DM users
                db=SessionLocal()
                try:
                    for u in get_all_users(db):
                        try:
                            fav=u.favorite_league if u.is_vip else None; fxs=fetch_real_fixtures(days_ahead=random.randint(1,3), limit=2 if u.is_vip else 1, fav_league=fav)
                            pmsg="☀️ Morning tip:\n\n" if not u.is_vip else f"☀️ Morning VIP {u.favorite_league}:\n\n"
                            for f in fxs:
                                d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
                                pmsg+=f"⚽ {f['home']} vs {f['away']} - {p['best_pick']}\n✅ {p['verdict']}\n{p['stake']}\n\n"
                            if not u.is_vip: pmsg+=f"💎 Upgrade 10 chats/day: https://betmaster-p09f.onrender.com/subscribe?uid={u.user_id}\n{DISCLAIMER}"
                            send_message(u.user_id, pmsg); time.sleep(0.4)
                        except: pass
                finally: db.close()
                posted.add(f"{today}-morning")
            if hm=="20:05" and f"{today}-evening" not in posted:
                fixtures=fetch_real_fixtures(limit=2); msg="🌙 **Evening Tips**\n\n"
                for f in fixtures:
                    d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
                    msg+=f"{f['home']} vs {f['away']} - {p['verdict']}\n"
                msg+=DISCLAIMER
                if CHANNEL_ID: send_message(CHANNEL_ID, msg)
                posted.add(f"{today}-evening")
        except Exception as e:
            print(f"Scheduler {e}")
        time.sleep(60)

threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

# ================= ROUTES =================
@app.get("/")
async def home():
    return {"status":"LIVE", "flutterwave": bool(FLW_PUBLIC)}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    fixtures=fetch_real_fixtures(limit=2)
    msg="🔥 Test Tips\n"
    for f in fixtures:
        d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
        msg+=f"{f['home']} vs {f['away']} - {p['verdict']}\n"
    if CHANNEL_ID: send_message(CHANNEL_ID, msg)
    return {"posted": True}

# Flutterwave payment creation
@app.get("/pay")
async def create_flutterwave_payment(plan: str, uid: str):
    if not FLW_SECRET:
        return JSONResponse({"error": "Flutterwave keys not set"}, status_code=500)
    amount = 2000 if plan=="weekly" else 5000
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": f"https://betmaster-p09f.onrender.com/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer": {"email": f"{uid}@betmasterpro.com", "name": f"User {uid}"},
        "customizations": {"title": f"BetMasterPro {plan.upper()}", "description": f"{plan} VIP subscription"},
    }
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        r = requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers, timeout=15)
        data = r.json()
        if data.get("status")=="success":
            return RedirectResponse(data["data"]["link"])
        return JSONResponse(data, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/verify")
async def verify_payment(tx_ref: str, uid: str, plan: str):
    # Verify with Flutterwave
    if not FLW_SECRET:
        return HTMLResponse("Keys not set")
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        # Get transaction ID from tx_ref
        r = requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}", headers=headers, timeout=15).json()
        if r.get("status")=="success" and r.get("data"):
            # Check if successful
            status = r["data"][0]["status"] if isinstance(r["data"], list) else r["data"]["status"]
            if status in ["successful", "completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(f"<html><body style='text-align:center;padding:40px;font-family:sans-serif'><h1>✅ Payment Successful!</h1><p>Plan: {plan.upper()} ₦{'2000' if plan=='weekly' else '5000'}</p><p>VIP activated till {date.today()+timedelta(days=7 if plan=='weekly' else 30)}</p><a href='https://t.me/Betmasterpro_bot' style='background:green;color:white;padding:15px 30px;text-decoration:none;border-radius:10px'>Go to Bot</a></body></html>")
        return HTMLResponse(f"<h1>❌ Payment not confirmed</h1><p>Ref: {tx_ref}</p><a href='/subscribe?uid={uid}'>Try again</a>")
    except Exception as e:
        return HTMLResponse(f"<h1>Error verifying: {e}</h1><a href='/subscribe?uid={uid}'>Retry</a>")

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    html = f"""
    <html>
    <head><title>BetMasterPro VIP</title><meta name="viewport" content="width=device-width,initial-scale=1">
    <script src="https://checkout.flutterwave.com/v3.js"></script>
    <style>body{{font-family:sans-serif;background:#0f172a;color:white;text-align:center;padding:20px}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}.paystack{{background:#f59e0b}}</style>
    </head>
    <body>
        <h1>💎 BetMasterPro VIP</h1>
        <p>Telegram ID: <b>{uid or 'Not linked - open from bot'}</b></p>
        <div class="card">
            <h3>Choose Plan</h3>
            <p>🆓 FREE: 2 chats/day + 1 tip 6AM WAT</p>
            <p>💎 VIP: 10 chats/day + 2 personalized tips (6AM & 9PM WAT)</p>
            <hr>
            <a class="btn weekly" href="/pay?plan=weekly&uid={uid}">💚 Weekly - ₦2,000 (7 days) - Pay with Flutterwave</a>
            <a class="btn monthly" href="/pay?plan=monthly&uid={uid}">💙 Monthly - ₦5,000 (30 days) - Pay with Flutterwave</a>
            <p style="font-size:12px;margin-top:15px">Secure payment by Flutterwave. After payment, VIP activates instantly.</p>
            <p style="font-size:11px">{DISCLAIMER}</p>
        </div>
        <p>Need help? Chat: <a href="https://t.me/Betmasterpro_bot" style="color:#22c55e"> @Betmasterpro_bot</a></p>
        <p>Channel: <a href="https://t.me/+IFK0qoDI2B5lYWI0" style="color:#3b82f6">Join Channel</a></p>
        <script>
        // If uid missing, ask
        const urlParams = new URLSearchParams(window.location.search);
        if(!urlParams.get('uid')){{
            let uid = prompt("Enter your Telegram User ID (send /myplan in bot to see it) or username:");
            if(uid) window.location.href = "/subscribe?uid="+uid;
        }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
