import os, time, threading, requests, json, traceback
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"): CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")
FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY",""); ADMIN_KEY = os.getenv("ADMIN_KEY","BetMasterAdmin123")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"; SUPPORT_HANDLE = "@Jibriliks"

app = FastAPI(title="BetMasterPro FINAL GUARANTEED")
print(f"=== FINAL GUARANTEED MATCHES + 500K BETSLIP - {BOT_LINK} ===")

def send_message(chat_id, text, parse=None, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000: text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if parse: payload["parse_mode"] = parse
        if reply_markup: payload["reply_markup"] = reply_markup
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 400 and "parse" in r.text.lower():
            payload.pop("parse_mode", None); r = requests.post(url, json=payload, timeout=15)
        return r
    except Exception as e: print(f"Send error: {e}"); traceback.print_exc()

def set_bot_menu():
    commands = [
        {"command": "start", "description": "Start bot"},
        {"command": "today", "description": "Top 10 REAL matches TODAY - Guaranteed every day"},
        {"command": "fixtures", "description": "Search: /fixtures nations, /fixtures asia, /fixtures usa"},
        {"command": "betslip", "description": "VIP ONLY - 10 matches WIN 500K from 1000 stake"},
        {"command": "upgrade", "description": "Upgrade to VIP - 10/day + 500K Betslip"},
        {"command": "help", "description": "Support"},
    ]
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        r = requests.post(url, json={"commands": commands}, timeout=10).json()
        print(f"Menu set: {r}")
    except Exception as e: print(f"Menu error: {e}")

def activate_vip(user_id, plan):
    from database import SessionLocal, get_user
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id)); expiry = date.today() + timedelta(days=7 if "weekly" in plan else 30)
        user.is_vip = True; user.vip_expiry = str(expiry); user.daily_count = 0; db.commit()
        send_message(int(user_id), f"VIP Activated! {plan.upper()} till {expiry}\n10/day + 500K Betslip!\nBot: {BOT_LINK}"); return True
    except Exception as e: print(f"VIP error {e}"); return False
    finally: db.close()

def process_update(upd):
    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures, generate_betslip
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
                        send_message(chat_id, f"Limit {user2.daily_count}/{limit} today.\nUpgrade: {RENDER_URL}/subscribe?uid={from_id}"); return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    send_message(chat_id, f"TOP 5 TODAY - {datetime.now().strftime('%d %B %Y')} - REAL Nations League + Friendlies")
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit: break
                        p = get_ai_prediction(f); update_league_history(db2, user2, f["league"])
                        msg = f"{f['home']} vs {f['away']}\nLeague: {f['league']} | {f['date']} {f['time']} WAT\nSource: {f.get('source','LIVE')}\nPick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\nReason: {p['explanation']}\n\nN1,000 -> N{p['winnings_1000']} | N2,000 -> N{p['winnings_2000']}\n{p['disclaimer']}\n"
                        send_message(chat_id, msg); user2.daily_count += 1; db2.commit(); time.sleep(0.7)
                finally: db2.close()
            elif data == "generate_betslip":
                db2 = SessionLocal()
                try:
                    user2 = get_user(db2, from_id)
                    if not user2.is_vip:
                        send_message(chat_id, f"BETSLIP VIP ONLY - Win 500K!\nUpgrade: {RENDER_URL}/subscribe?uid={from_id}"); return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=20)
                    slip = generate_betslip(fixtures)
                    if not slip:
                        send_message(chat_id, f"Not enough matches today for 10-game slip. Found {len(fixtures)}. Try /today"); return
                    msg = f"BETSLIP 10 MATCHES - {datetime.now().strftime('%d %B %Y')} - VIP ONLY - WIN 500K\nStake: N1,000 or N2,000 to win 500K+\n\n"
                    for i,p in enumerate(slip["picks"],1): msg+=f"{i}. {p['match']}\n {p['league']} - {p['pick']} @ {p['odds']}\n\n"
                    msg+=f"TOTAL ODDS: {slip['total_odds']}\n\nPOTENTIAL WINNINGS:\nStake N1,000 -> WIN N{slip['winnings_1000']} (Profit N{slip['profit_1000']})\nStake N2,000 -> WIN N{slip['winnings_2000']} (Profit N{slip['profit_2000']})\n\nPlay on SportyBet/BetKing - 10 games combo\nVIP EXTRA - Not counted in 10/day\nBot: {BOT_LINK}\n"
                    send_message(chat_id, msg)
                finally: db2.close()
        except Exception as e: print(f"Callback error {e}"); traceback.print_exc()
        return
    msg = upd.get("message")
    if not msg or "text" not in msg or msg["chat"]["type"]!="private": return
    chat_id = msg["chat"]["id"]; text = msg["text"].strip(); user_id = msg["from"]["id"]; username = msg["from"].get("username",""); low = text.lower()
    db = SessionLocal()
    try:
        user = get_user(db, user_id, username); FREE=2; VIP=10; cur = VIP if user.is_vip else FREE
        if low.startswith("/start"):
            send_message(chat_id, f"Welcome to BetMasterPro - GUARANTEED MATCHES + 500K BETSLIP\n\nMatches EVERY DAY - Nations League + Friendlies + Asia + America\n\nMenu:\n/today - 10 REAL TODAY guaranteed (never says no matches)\n/fixtures nations - Nations League today\n/fixtures friendly - Friendlies\n/fixtures asia - Asian leagues\n/betslip - VIP ONLY - Stake N1000 to WIN N500K (10 matches high odds combo)\n/upgrade - VIP\n/help\n\nFREE {FREE}/day, VIP {VIP}/day + Betslip EXTRA\n\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")
        elif low.startswith("/help"):
            send_message(chat_id, f"Support: {SUPPORT_HANDLE}\nBot: {BOT_LINK}\nYou: {user.daily_count}/{cur}\n\nTry:\n/fixtures nations\n/fixtures friendly\n/today")
        elif low.startswith("/betslip"):
            if not user.is_vip:
                send_message(chat_id, f"BETSLIP VIP ONLY - Stake N1000 WIN N500K!\n10 high odds matches combo\nThis is EXTRA - not counted in {cur}/day\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            send_message(chat_id, f"Generating VIP 500K BETSLIP - Stake 1000 to win 500K - Please wait...")
            fixtures = fetch_real_fixtures(days_ahead=0, limit=20)
            from predictor import generate_betslip
            slip = generate_betslip(fixtures)
            msg = f"BETSLIP VIP - WIN 500K - {datetime.now().strftime('%d %B %Y')}\nStake N1000/N2000 to win 500K+\n\n"
            for i,p in enumerate(slip["picks"],1): msg+=f"{i}. {p['match']}\n {p['league']}\n {p['pick']} @ {p['odds']}\n\n"
            msg+=f"TOTAL ODDS: {slip['total_odds']}\n\nWINNINGS:\nStake N1,000 -> WIN N{slip['winnings_1000']} (Profit N{slip['profit_1000']})\nStake N2,000 -> WIN N{slip['winnings_2000']} (Profit N{slip['profit_2000']})\n\nEXTRA - Not counted\nBot: {BOT_LINK}"
            keyboard = {"inline_keyboard": [[{"text": "Regenerate 500K Betslip", "callback_data": "generate_betslip"}]]}
            send_message(chat_id, msg, reply_markup=keyboard)
        elif low.startswith("/fixtures"):
            parts = low.split(); country = parts[1] if len(parts)>1 else "nations"
            if user.daily_count >= cur: send_message(chat_id, f"Limit {user.daily_count}/{cur}\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            send_message(chat_id, f"Fetching REAL {country.title()} TODAY {datetime.now().strftime('%Y-%m-%d')}...")
            fixtures = fetch_fixtures_by_country(country, days_ahead=0, limit=5)
            list_msg = f"{country.upper()} REAL FIXTURES TODAY - {datetime.now().strftime('%Y-%m-%d')}\n\n"
            for i,f in enumerate(fixtures,1): list_msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT | 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']}\n\n"
            keyboard = {"inline_keyboard": [[{"text": f"Predict {country.title()}", "callback_data": "predict_top5"}]]}
            send_message(chat_id, list_msg, reply_markup=keyboard)
        elif low.startswith("/upgrade") or low.startswith("/subscribe"):
            send_message(chat_id, f"VIP:\nFREE {FREE}/day\nVIP {VIP}/day + BETSLIP WIN 500K from N1000 stake EXTRA\nWeekly N2,000 / Monthly N5,000\nLink: {RENDER_URL}/subscribe?uid={user_id}\nBot: {BOT_LINK}")
        elif low.startswith("/today"):
            if user.daily_count >= cur: send_message(chat_id, f"Limit {user.daily_count}/{cur}\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            send_message(chat_id, f"Fetching REAL fixtures TODAY {datetime.now().strftime('%d %B %Y')} - Nations League + Friendlies + Global - Guaranteed...")
            fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
            # NEVER SAY NO MATCHES - Always show something
            header = f"TOP {len(fixtures)} REAL FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')} - Nations League + Friendlies + Global\n\n"
            list_msg = header
            for i,f in enumerate(fixtures,1): list_msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT | 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']} | {f.get('source','LIVE')}\n\n"
            list_msg+=f"Tap Predict! ({user.daily_count}/{cur})\nBot: {BOT_LINK}"
            keyboard = {"inline_keyboard": [[{"text": "Predict Top 5", "callback_data": "predict_top5"}, {"text": "VIP 500K Betslip (N1000->N500K)", "callback_data": "generate_betslip"}]]}
            send_message(chat_id, list_msg, reply_markup=keyboard)
        elif "vs" in low and 5 < len(text) < 100:
            if user.daily_count >= cur: send_message(chat_id, f"Limit {user.daily_count}/{cur}\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}"); return
            try: home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
            except: home=text.title(); away="Opponent"
            all_f = fetch_real_fixtures(days_ahead=0, limit=100)
            matched = next((f for f in all_f if home.lower() in f['home'].lower() and away.lower() in f['away'].lower()), None)
            data = matched if matched else {"home": home, "away": away, "league": user.favorite_league, "odds_h": 2.2, "odds_d": 3.2, "odds_a": 2.9, "odds_over15": 1.30, "odds_over25": 1.85, "odds_btts": 1.75, "odds_1x": 1.35, "best_odds_source": "Live", "date": datetime.now().strftime('%Y-%m-%d'), "source": "Search", "continent": "World"}
            from predictor import get_ai_prediction
            p = get_ai_prediction(data); update_league_history(db, user, data.get("league","Custom")); user.daily_count+=1; db.commit()
            msg = f"{home} vs {away}\nLeague: {data.get('league','Custom')} | {datetime.now().strftime('%d %B %Y')}\nOdds: 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\nPick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\nReason: {p['explanation']}\n\nPotential:\nN1,000 -> N{p['winnings_1000']}\nN2,000 -> N{p['winnings_2000']}\nUsed: {user.daily_count}/{cur}\n{p['disclaimer']}\nBot: {BOT_LINK}"
            send_message(chat_id, msg)
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
                    msg=f"Morning {today} - GLOBAL REAL + 500K Betslip available\n\n"
                    for f in uniq:
                        p=get_ai_prediction(f)
                        msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_pick']} @ {p['odds']} | N1000->N{p['winnings_1000']}\n\n"
                    msg+=f"Bot: {BOT_LINK} | {SUPPORT_HANDLE}"
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
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true", timeout=10)
    except Exception as e: print(f"Webhook error {e}")

@app.get("/")
async def home():
    try:
        r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
        ok=r.get("ok",False); username=r.get("result",{}).get("username","UNKNOWN")
        wh=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=8).json()
    except Exception as e: ok=False; username=str(e); wh={}
    return {"status":"FINAL GUARANTEED MATCHES + 500K BETSLIP","bot_ok":ok,"bot_username":username,"bot_link":BOT_LINK,"webhook_info":wh.get("result",{}),"menu":"/start /today /fixtures /betslip /upgrade /help"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try: data = await request.json(); process_update(data); return JSONResponse({"ok": True})
    except Exception as e: print(f"Webhook error {e}"); traceback.print_exc(); return JSONResponse({"ok": True}, status_code=200)

@app.get("/set-webhook")
async def set_webhook():
    set_bot_menu()
    webhook_url = f"{RENDER_URL}/webhook"
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true", timeout=10).json()
    return r

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
                return HTMLResponse(f"<h1>OK {plan.upper()} 10/day + 500K Betslip till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</h1><a href='{BOT_LINK}'>Go to Bot</a>")
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
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}</style></head><body><h1>BetMasterPro VIP + 500K BETSLIP</h1><p>ID: {uid}</p><div class='card'><p>FREE 2/day<br>VIP 10/day + 10-match BETSLIP<br>Stake N1000 WIN N500K<br>Guaranteed matches every day</p><a class='btn weekly' href='/pay?plan=weekly&uid={uid}'>Weekly N2,000</a><a class='btn monthly' href='/pay?plan=monthly&uid={uid}'>Monthly N5,000</a><p>Bot: {BOT_LINK}</p></div></body></html>")

if __name__=="__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
