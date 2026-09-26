import os, time, threading, requests, random, json, traceback
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"): CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")
FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY","")
FLW_WEBHOOK_SECRET = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET","")
ADMIN_KEY = os.getenv("ADMIN_KEY","BetMasterAdmin123")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"

BOT_LINK = "https://t.me/Betmasterpro_bot"
SUPPORT_HANDLE = "@Jibriliks"
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"

app = FastAPI(title="BetMasterPro Scraper FINAL")
print(f"=== SCRAPER FINAL LIVE - {BOT_LINK} ===")

DISCLAIMER = "\n\nDisclaimer: 18+ Bet responsibly. AI only."

def send_message(chat_id, text, parse=None, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000: text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if parse: payload["parse_mode"] = parse
        if reply_markup: payload["reply_markup"] = reply_markup
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 400 and "parse" in r.text.lower():
            payload.pop("parse_mode", None)
            r = requests.post(url, json=payload, timeout=15)
        print(f"Send {chat_id}: {r.status_code}")
        return r
    except Exception as e:
        print(f"Send error: {e}"); traceback.print_exc()

def set_bot_menu():
    """Sets professional menu - /start, /fixtures, /upgrade, /help"""
    try:
        commands = [
            {"command": "start", "description": "Start bot + welcome"},
            {"command": "today", "description": "Top 10 matches today (scraped from SportyBet, BetKing, etc)"},
            {"command": "fixtures", "description": "Search fixtures by country e.g. /fixtures england"},
            {"command": "upgrade", "description": "Upgrade to VIP - 10 predictions/day"},
            {"command": "help", "description": "Support & how to use"},
        ]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        r = requests.post(url, json={"commands": commands}, timeout=10).json()
        print(f"Menu set: {r}")
    except Exception as e: print(f"Menu error: {e}")

def activate_vip(user_id, plan):
    from database import SessionLocal, get_user
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id))
        expiry = date.today() + timedelta(days=7 if "weekly" in plan else 30)
        user.is_vip = True; user.vip_expiry = str(expiry); user.daily_count = 0; db.commit()
        send_message(int(user_id), f"VIP Activated!\n{plan.upper()} till {expiry}\n10 predictions/day!\nBot: {BOT_LINK}")
        return True
    except Exception as e: print(f"VIP error {e}"); return False
    finally: db.close()

def process_update(upd):
    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    if "callback_query" in upd:
        try:
            cq = upd["callback_query"]; chat_id = cq["message"]["chat"]["id"]; from_id = cq["from"]["id"]; data = cq.get("data","")
            requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": "Generating..."}, timeout=5)
            if data == "predict_top5":
                db2 = SessionLocal()
                try:
                    user2 = get_user(db2, from_id); limit = 10 if user2.is_vip else 2
                    if user2.daily_count >= limit:
                        send_message(chat_id, f"Limit {user2.daily_count}/{limit} today.\nUpgrade: {RENDER_URL}/subscribe?uid={from_id}\nSupport: {SUPPORT_HANDLE}"); return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures: fixtures = fetch_real_fixtures(days_ahead=1, limit=5)
                    send_message(chat_id, f"TOP 5 PREDICTIONS TODAY - {datetime.now().strftime('%d %B %Y')} (Odds from SportyBet, BetKing, 9jaBet merged)")
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit: break
                        p = get_ai_prediction(f)
                        update_league_history(db2, user2, f["league"])
                        msg = f"{f['home']} vs {f['away']}\nLeague: {f['league']} | {f['date']} {f['time']} WAT\nSources: {f.get('best_odds_source','SportyBet')}\nPick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\nReason: {p['explanation']}\nVerdict: {p['verdict']}\n{p['stake']}\n\nPotential Winnings:\n- N1,000 -> N{p['winnings_1000']} (Profit N{p['winnings_1000']-1000})\n- N2,000 -> N{p['winnings_2000']} (Profit N{p['winnings_2000']-2000})\nBest Bookie: {p['best_bookie']}\n{p['disclaimer']}\n"
                        send_message(chat_id, msg)
                        user2.daily_count += 1; db2.commit(); time.sleep(0.7)
                finally: db2.close()
        except Exception as e: print(f"Callback error {e}"); traceback.print_exc()
        return

    msg = upd.get("message")
    if not msg or "text" not in msg or msg["chat"]["type"]!="private": return
    chat_id = msg["chat"]["id"]; text = msg["text"].strip(); user_id = msg["from"]["id"]; username = msg["from"].get("username",""); low = text.lower()
    print(f"Message {user_id}: {text}")
    db = SessionLocal()
    try:
        user = get_user(db, user_id, username); FREE=2; VIP=10; cur = VIP if user.is_vip else FREE

        if low.startswith("/start"):
            send_message(chat_id, f"Welcome to BetMasterPro - Scraper Bot\n\nI scrape SportyBet, 9jaBet, BetKing, Football.com LIVE every day for accurate odds!\n\nCommands (use Menu button):\n- /start - Welcome\n- /today - Top 10 matches TODAY scraped LIVE\n- /fixtures [country] - e.g. /fixtures england\n- /upgrade - VIP 10/day\n- /help - Support\n\nLimits: FREE {FREE}/day, VIP {VIP}/day\n\nHow to play:\n1. Send Arsenal vs Chelsea or /today\n2. Get Pick + Odds + Potential Winnings for N1000/N2000\n3. Play on SportyBet/BetKing with best odds\n\nChannel: {CHANNEL_LINK}\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")

        elif low.startswith("/help"):
            send_message(chat_id, f"Support: {SUPPORT_HANDLE}\nBot: {BOT_LINK}\nChannel: {CHANNEL_LINK}\n\nMenu:\n/start - Start\n/today - 10 LIVE matches scraped\n/fixtures england - Search\n/upgrade - VIP {VIP}/day\n/help - This help\n\nYou: {user.daily_count}/{cur} used today")

        elif low.startswith("/fixtures"):
            parts = low.split()
            country = parts[1] if len(parts)>1 else "england"
            if user.daily_count >= cur:
                send_message(chat_id, f"Limit {user.daily_count}/{cur}\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            send_message(chat_id, f"Scraping {country.title()} LIVE from SportyBet, BetKing, 9jaBet for TODAY {datetime.now().strftime('%d %B %Y')}...")
            fixtures = fetch_fixtures_by_country(country, days_ahead=0, limit=5)
            if not fixtures:
                send_message(chat_id, f"No {country.title()} today - LIVE scraped data. Try /today\nBot: {BOT_LINK}"); return
            list_msg = f"{country.upper()} FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')} - Scraped LIVE\n\n"
            for i,f in enumerate(fixtures,1):
                list_msg+=f"{i}. {f['home']} vs {f['away']}\n League: {f['league']} | {f['time']} WAT | Odds: 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']} | Source: {f.get('source','Live')}\n\n"
            keyboard = {"inline_keyboard": [[{"text": f"Predict {country.title()} Top", "callback_data": "predict_top5"}]]}
            send_message(chat_id, list_msg + f"Bot: {BOT_LINK}", reply_markup=keyboard)

        elif low.startswith("/upgrade") or low.startswith("/subscribe"):
            send_message(chat_id, f"BetMasterPro VIP\nFREE: {FREE}/day | VIP: {VIP}/day\nWeekly N2,000 / Monthly N5,000\nCard + Bank Transfer auto-activate!\nLink: {RENDER_URL}/subscribe?uid={user_id}\nBot: {BOT_LINK}")

        elif low.startswith("/today"):
            if user.daily_count >= cur:
                send_message(chat_id, f"Daily limit {user.daily_count}/{cur} reached.\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            send_message(chat_id, f"Scraping LIVE from SportyBet, BetKing, 9jaBet, Football.com for TODAY {datetime.now().strftime('%d %B %Y')} - Please wait 5s for accuracy...")
            fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
            if not fixtures:
                fixtures = fetch_real_fixtures(days_ahead=1, limit=10)
                header = f"No games today - TOP 10 TOMORROW - {(datetime.now()+timedelta(days=1)).strftime('%d %B %Y')} (Scraped LIVE)\n\n"
            else:
                header = f"TOP {len(fixtures)} LIVE FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')} - Scraped from SportyBet, BetKing, 9jaBet, Football.com\n\n"
            list_msg = header
            for i,f in enumerate(fixtures,1):
                list_msg+=f"{i}. {f['home']} vs {f['away']}\n League: {f['league']} | Time: {f['time']} WAT | Odds 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']} | Sources: {f.get('best_odds_source','Live')}\n\n"
            list_msg+=f"Tap Predict for winnings N1000/N2000 calc!\nBot: {BOT_LINK} ({user.daily_count}/{cur} used)"
            keyboard = {"inline_keyboard": [[{"text": "Predict Top 5 + Winnings", "callback_data": "predict_top5"}]]}
            send_message(chat_id, list_msg, reply_markup=keyboard)

        elif "vs" in low and 5 < len(text) < 100:
            if user.daily_count >= cur:
                send_message(chat_id, f"Limit {user.daily_count}/{cur}\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            try: home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
            except: home=text.title(); away="Opponent"
            # Scrape odds for this specific match
            all_f = fetch_real_fixtures(days_ahead=0, limit=30)
            matched = next((f for f in all_f if home.lower() in f['home'].lower() and away.lower() in f['away'].lower()), None)
            if matched: data = matched
            else: data = {"home": home, "away": away, "league": user.favorite_league, "odds_h": 2.2, "odds_d": 3.2, "odds_a": 2.9, "odds_over15": 1.30, "odds_over25": 1.85, "odds_btts": 1.75, "odds_1x": 1.35, "best_odds_source": "Avg Market", "date": datetime.now().strftime('%Y-%m-%d')}
            p = get_ai_prediction(data)
            update_league_history(db, user, data.get("league","Custom"))
            user.daily_count+=1; db.commit()
            msg = f"{home} vs {away}\nLeague: {data.get('league','Custom')} | {datetime.now().strftime('%d %B %Y')}\nOdds scraped: 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']} | Best: {data.get('best_odds_source','Live')}\n\nPick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\nReason: {p['explanation']}\nVerdict: {p['verdict']}\n{p['stake']}\n\nHow to play: Stake on {p['market']} market\nPotential Winnings:\n- N1,000 stake -> Win N{p['winnings_1000']} (Profit N{p['winnings_1000']-1000})\n- N2,000 stake -> Win N{p['winnings_2000']} (Profit N{p['winnings_2000']-2000})\n\nUsed: {user.daily_count}/{cur}\n{p['disclaimer']}\n\nPlay on SportyBet/BetKing with best odds!\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}"
            send_message(chat_id, msg)
        else:
            send_message(chat_id, f"Send like Arsenal vs Chelsea or use Menu:\n/today - 10 LIVE scraped\n/fixtures england\n/upgrade\nBot: {BOT_LINK}")

    except Exception as e: print(f"Handler {e}"); traceback.print_exc(); db.rollback()
    finally: db.close()

def channel_scheduler():
    from database import SessionLocal, is_already_posted, mark_as_posted
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted=set()
    while True:
        try:
            now_utc=datetime.utcnow(); hm=now_utc.strftime("%H:%M"); today=now_utc.strftime("%Y-%m-%d")
            if hm=="05:05" and f"{today}-morning" not in posted:
                db=SessionLocal()
                try:
                    fixtures=fetch_real_fixtures(days_ahead=1, limit=15); uniq=[]
                    for f in fixtures:
                        h=f"{f['home']}-{f['away']}-{f['date']}"
                        if not is_already_posted(db,h): uniq.append(f); mark_as_posted(db,h)
                        if len(uniq)>=2: break
                    if not uniq: uniq=fixtures[:2]
                    msg=f"Morning {today} - Scraped from SportyBet, BetKing, 9jaBet\n\n"
                    for f in uniq:
                        p=get_ai_prediction(f)
                        msg+=f"{f['home']} vs {f['away']}\nLeague: {f['league']} | {f['date']} {f['time']} WAT\nPick: {p['best_pick']} @ {p['odds']} | N1000->N{p['winnings_1000']} N2000->N{p['winnings_2000']}\n\n"
                    msg+=f"Bot: {BOT_LINK} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
                    if CHANNEL_ID: send_message(CHANNEL_ID, msg)
                finally: db.close()
                posted.add(f"{today}-morning")
        except Exception as e: print(f"Scheduler {e}")
        time.sleep(60)

threading.Thread(target=channel_scheduler, daemon=True).start()

@app.on_event("startup")
async def on_startup():
    set_bot_menu()
    webhook_url = f"{RENDER_URL}/webhook"
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true"
        r = requests.get(url, timeout=10).json()
        print(f"WEBHOOK SET: {webhook_url} -> {r}")
    except Exception as e: print(f"Webhook error {e}")

@app.get("/")
async def home():
    try:
        r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
        ok=r.get("ok",False); username=r.get("result",{}).get("username","UNKNOWN")
        wh=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=8).json()
    except Exception as e: ok=False; username=str(e); wh={}
    return {"status":"SCRAPER FINAL LIVE","bot_ok":ok,"bot_username":username,"bot_link":BOT_LINK,"webhook_info":wh.get("result",{}),"menu":"/start /today /fixtures /upgrade /help"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        process_update(data)
        return JSONResponse({"ok": True})
    except Exception as e: print(f"Webhook error {e}"); traceback.print_exc(); return JSONResponse({"ok": True}, status_code=200)

@app.get("/set-webhook")
async def set_webhook():
    set_bot_menu()
    webhook_url = f"{RENDER_URL}/webhook"
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true", timeout=10).json()
    return r

@app.get("/test-direct")
async def test_direct(chat_id: str = ""):
    if not chat_id: return {"error": "Use /test-direct?chat_id=YOUR_ID"}
    send_message(int(chat_id), f"DIRECT TEST - Scraper bot alive {datetime.now()}\nMenu: /start /today /fixtures /upgrade /help\nBot: {BOT_LINK}")
    return {"sent": True}

@app.get("/pay")
async def pay(plan:str, uid:str):
    if not FLW_SECRET: return JSONResponse({"error":"Keys not set"}, status_code=500)
    amount=2000 if plan=="weekly" else 5000
    tx_ref=f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload={"tx_ref":tx_ref,"amount":amount,"currency":"NGN","redirect_url":f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}","customer":{"email":f"{uid}@betmasterpro.com","name":f"User {uid}"},"customizations":{"title":f"BetMasterPro {plan.upper()}"}}
    headers={"Authorization":f"Bearer {FLW_SECRET}"}
    try:
        r=requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers, timeout=15).json()
        if r.get("status")=="success": return RedirectResponse(r["data"]["link"])
        return JSONResponse(r, status_code=400)
    except Exception as e: return JSONResponse({"error":str(e)}, status_code=500)

@app.get("/verify")
async def verify(tx_ref:str, uid:str, plan:str):
    headers={"Authorization":f"Bearer {FLW_SECRET}"}
    try:
        r=requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}", headers=headers, timeout=15).json()
        if r.get("status")=="success" and r.get("data"):
            data=r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ["successful","completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(f"<h1>Payment OK {plan.upper()} 10/day till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</h1><a href='{BOT_LINK}'>Go to Bot</a>")
        return HTMLResponse(f"<h1>Not confirmed {tx_ref}</h1><a href='/subscribe?uid={uid}'>Retry</a>")
    except Exception as e: return HTMLResponse(f"Error {e}")

@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request:Request):
    try:
        body=await request.body(); data=json.loads(body)
        if data.get("event")=="charge.completed" and data.get("data",{}).get("status")=="successful":
            tx_ref=data["data"].get("tx_ref",""); parts=tx_ref.split("-")
            if len(parts)>=3 and parts[0]=="BETMASTER": activate_vip(parts[1], parts[2])
        return JSONResponse({"status":"ok"})
    except Exception as e: print(f"Webhook {e}"); return JSONResponse({"status":"error"}, status_code=200)

@app.get("/admin/activate")
async def admin_activate(uid:str, plan:str="monthly", key:str=""):
    if key!=ADMIN_KEY: return HTMLResponse("Wrong key", status_code=403)
    ok=activate_vip(uid, plan); return HTMLResponse(f"{'Activated' if ok else 'Failed'} {uid} {plan} - {BOT_LINK}")

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}</style></head><body><h1>BetMasterPro VIP - Scraper</h1><p>ID: {uid}</p><div class='card'><p>FREE 2/day | VIP 10/day<br>Scraped from SportyBet, BetKing, 9jaBet, Football.com</p><a class='btn weekly' href='/pay?plan=weekly&uid={uid}'>Weekly N2,000</a><a class='btn monthly' href='/pay?plan=monthly&uid={uid}'>Monthly N5,000</a><p>Bot: {BOT_LINK}<br>Support: {SUPPORT_HANDLE}</p></div></body></html>")

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
