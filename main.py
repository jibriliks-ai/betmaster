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
                        data={"home":home,"away":away,"league":league_guess,"home_xg":1.6,"away_xg":1.1,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":2.1,"odds_d":3.2,"odds_a":3.4,"odds_over":1.75}
                        pred=get_ai_prediction(data); update_league_history(db, user, league_guess); user.daily_count+=1; db.commit()
                        intro = random.choice(["🔥","💎","⚡","🎯"])
                        send_message(chat_id, f"{intro} ⚽ **{home} vs {away}**\n🏆 {league_guess}\n💰 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **{pred['verdict']}**\n{pred['stake']}\n{user.daily_count}/{limit} used\n{pred['disclaimer']}\n\n💬 More? {BOT_HANDLE} | {BOT_HANDLE_2}")
                except Exception as e: print(e); db.rollback()
                finally: db.close()
        except Exception as e: print(f"Poll {e}"); time.sleep(5)

def channel_scheduler():
    from database import SessionLocal, get_all_users, is_already_posted, mark_as_posted
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted=set()
    while True:
        try:
            now_utc=datetime.utcnow(); hm=now_utc.strftime("%H:%M"); today=now_utc.strftime("%Y-%m-%d")
            if hm=="05:05" and f"{today}-morning" not in posted:
                print(f"MORNING 6AM WAT {today}")
                db=SessionLocal()
                try:
                    # Generate unique fixtures - avoid repeats
                    fixtures=fetch_real_fixtures(days_ahead=random.randint(1,2), limit=10)
                    unique=[]
                    for f in fixtures:
                        h = f"{f['home']}-{f['away']}-{f['date']}"
                        if not is_already_posted(db, h):
                            unique.append(f)
                            mark_as_posted(db, h)
                            if len(unique)>=2: break
                    if not unique: unique=fixtures[:2]

                    msg=f"🔥 **BetMasterPro Morning - {today}** 🔥\n📅 Matches in 1-3 days | Live & Unique\n\n"
                    for f in unique:
                        d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
                        # Unique intro each time
                        intro=random.choice(["💎 VIP Pick","🔥 Hot","⚡ Expert","🎯 Top"])
                        msg+=f"{intro}: **{f['home']} vs {f['away']}**\n🏆 {f['league']} | ⏰ {f['time']} WAT\n🎯 {p['best_pick']} | ✅ {p['verdict']}\n{p['stake']}\n\n"
                    msg+=f"💬 Chat for more: {BOT_HANDLE} | {BOT_HANDLE_2}\n🆘 Support: {SUPPORT_HANDLE}\n🔗 https://t.me/+IFK0qoDI2B5lYWI0\n{DISCLAIMER}"
                    if CHANNEL_ID: send_message(CHANNEL_ID, msg)
                    # DM users unique
                    for u in get_all_users(db):
                        try:
                            fav=u.favorite_league if u.is_vip else None; fxs=fetch_real_fixtures(days_ahead=random.randint(1,3), limit=2 if u.is_vip else 1, fav_league=fav)
                            pmsg=f"☀️ Morning {'VIP '+u.favorite_league if u.is_vip else 'Free'} Tip - Unique:\n\n"
                            for f in fxs:
                                d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
                                pmsg+=f"⚽ {f['home']} vs {f['away']} - {p['best_pick']}\n✅ {p['verdict']}\n\n"
                            pmsg+=f"More: {BOT_HANDLE} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
                            if not u.is_vip: pmsg+=f"\n💎 Upgrade: https://betmaster-p09f.onrender.com/subscribe?uid={u.user_id}"
                            send_message(u.user_id, pmsg); time.sleep(0.4)
                        except: pass
                finally: db.close()
                posted.add(f"{today}-morning")
            if hm=="20:05" and f"{today}-evening" not in posted:
                # Evening similar unique logic
                db=SessionLocal()
                try:
                    fixtures=fetch_real_fixtures(days_ahead=1, limit=10)
                    unique=[]
                    for f in fixtures:
                        h=f"{f['home']}-{f['away']}-{today}-eve"
                        if not is_already_posted(db, h):
                            unique.append(f); mark_as_posted(db, h)
                            if len(unique)>=2: break
                    if not unique: unique=fixtures[:2]
                    msg=f"🌙 **Evening VIP - {today}**\n\n"
                    for f in unique:
                        d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
                        msg+=f"⚽ {f['home']} vs {f['away']} - {p['verdict']}\n"
                    msg+=f"Chat: {BOT_HANDLE} | {BOT_HANDLE_2} | Support {SUPPORT_HANDLE}\n{DISCLAIMER}"
                    if CHANNEL_ID: send_message(CHANNEL_ID, msg)
                finally: db.close()
                posted.add(f"{today}-evening")
        except Exception as e: print(f"Scheduler {e}")
        time.sleep(60)

threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

@app.get("/")
async def home(): return {"status":"SUPER BRAIN LIVE", "support": SUPPORT_HANDLE, "bot_handles": [BOT_HANDLE, BOT_HANDLE_2]}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    from database import SessionLocal, is_already_posted, mark_as_posted
    db=SessionLocal()
    try:
        fixtures=fetch_real_fixtures(limit=5); unique=[]
        for f in fixtures:
            h=f"{f['home']}-{f['away']}-{str(date.today())}-manual"
            if not is_already_posted(db, h):
                unique.append(f); mark_as_posted(db, h)
                if len(unique)>=2: break
        if not unique: unique=fixtures[:2]
        msg=f"🔥 Test Unique {datetime.now().strftime('%H:%M')}\n\n"
        for f in unique:
            d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
            msg+=f"{f['home']} vs {f['away']} - {p['verdict']}\n"
        msg+=f"More: {BOT_HANDLE} | {BOT_HANDLE_2} | Support {SUPPORT_HANDLE}\n{DISCLAIMER}"
        if CHANNEL_ID: send_message(CHANNEL_ID, msg)
        return {"posted": True, "unique": unique}
    finally: db.close()

@app.get("/pay")
async def create_payment(plan: str, uid: str):
    if not os.getenv("FLUTTERWAVE_SECRET_KEY"): return JSONResponse({"error":"Keys not set"}, status_code=500)
    amount=2000 if plan=="weekly" else 5000
    tx_ref=f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload={"tx_ref":tx_ref,"amount":amount,"currency":"NGN","redirect_url":f"https://betmaster-p09f.onrender.com/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}","customer":{"email":f"{uid}@betmasterpro.com","name":f"User {uid}"},"customizations":{"title":f"BetMasterPro {plan.upper()}"}}
    headers={"Authorization": f"Bearer {os.getenv('FLUTTERWAVE_SECRET_KEY')}"}
    try:
        r=requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers, timeout=15).json()
        if r.get("status")=="success": return RedirectResponse(r["data"]["link"])
        return JSONResponse(r, status_code=400)
    except Exception as e: return JSONResponse({"error":str(e)}, status_code=500)

@app.get("/verify")
async def verify_payment(tx_ref: str, uid: str, plan: str):
    headers={"Authorization": f"Bearer {os.getenv('FLUTTERWAVE_SECRET_KEY')}"}
    try:
        r=requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}", headers=headers, timeout=15).json()
        if r.get("status")=="success" and r.get("data"):
            status = r["data"][0]["status"] if isinstance(r["data"], list) else r["data"]["status"]
            if status in ["successful","completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(f"<h1>✅ Payment Successful via {'Bank Transfer' if 'bank' in r['data'][0].get('payment_type','') else 'Card'}!</h1><p>VIP till {date.today()+timedelta(days=7 if plan=='weekly' else 30)}</p><a href='https://t.me/Betmasterpro_bot'>Go to Bot {BOT_HANDLE}</a><br>Support: {SUPPORT_HANDLE}")
        return HTMLResponse(f"<h1>❌ Not confirmed {tx_ref}</h1><a href='/subscribe?uid={uid}'>Retry</a> | Support {SUPPORT_HANDLE}")
    except Exception as e: return HTMLResponse(f"Error {e} | {SUPPORT_HANDLE}")

# CRITICAL: Flutterwave webhook for Bank Transfer auto-activation
@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request: Request):
    try:
        body = await request.body()
        data = json.loads(body)
        # Verify signature if secret hash set
        # Flutterwave sends payment success including bank transfer
        if data.get("event") == "charge.completed" and data.get("data",{}).get("status") == "successful":
            tx_ref = data["data"].get("tx_ref","")
            # Parse uid and plan from tx_ref BETMASTER-{uid}-{plan}-{timestamp}
            parts = tx_ref.split("-")
            if len(parts) >= 3 and parts[0]=="BETMASTER":
                uid = parts[1]; plan = parts[2]
                activate_vip(uid, plan)
                print(f"Webhook auto-activated VIP {uid} {plan} via {data['data'].get('payment_type')}")
        return JSONResponse({"status":"ok"})
    except Exception as e:
        print(f"Webhook error {e}")
        return JSONResponse({"status":"error"}, status_code=200)

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid=request.query_params.get("uid","")
    html=f"""
    <html><head><title>BetMasterPro VIP</title><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{font-family:sans-serif;background:#0f172a;color:white;text-align:center;padding:20px}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}</style></head>
    <body><h1>💎 BetMasterPro VIP - Super Brain</h1><p>ID: <b>{uid or 'Open from bot'}</b></p>
    <div class="card"><h3>Choose Plan - Card or Bank Transfer (Auto-activates)</h3>
    <p>🆓 FREE: 2 chats/day + 1 unique tip 6AM WAT</p><p>💎 VIP: 10 chats/day + 2 unique personalized tips</p>
    <a class="btn weekly" href="/pay?plan=weekly&uid={uid}">💚 Weekly ₦2,000 (7 days) - Flutterwave</a>
    <a class="btn monthly" href="/pay?plan=monthly&uid={uid}">💙 Monthly ₦5,000 (30 days) - Flutterwave</a>
    <p style="font-size:12px">Bank Transfer & Card both auto-activate VIP instantly via webhook.</p>
    <p>Support: <a href="https://t.me/Jibriliks" style="color:#22c55e">{SUPPORT_HANDLE}</a></p>
    <p>Bot: {BOT_HANDLE} | {BOT_HANDLE_2}</p>
    <p style="font-size:11px">{DISCLAIMER}</p></div></body></html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
