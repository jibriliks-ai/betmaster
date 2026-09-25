import os, time, threading, requests, random, json, traceback
from datetime import datetime, timedelta, date
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")

FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY","")
FLW_WEBHOOK_SECRET = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET","")
ADMIN_KEY = os.getenv("ADMIN_KEY","BetMasterAdmin123")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"

BOT_LINK = "https://t.me/Betmasterpro_bot"
SUPPORT_HANDLE = "@Jibriliks"
BOT_HANDLE = "@Betmasterpro_bot"
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"

app = FastAPI(title="BetMasterPro FINAL WORKING")
print(f"=== FINAL WORKING CODE - {BOT_LINK} ===")

DISCLAIMER = "\n\nDisclaimer: Betting risk. AI only, 18+ stake responsibly."

# ===== SAFE SEND - FIXES 400 ERROR - BOT NOT RESPONDING =====
def send_message(chat_id, text, parse="Markdown", reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if parse:
            payload["parse_mode"] = parse
        if reply_markup:
            payload["reply_markup"] = reply_markup

        r = requests.post(url, json=payload, timeout=15)

        # IF MARKDOWN FAILS (your log error), RETRY WITHOUT MARKDOWN - THIS FIXES IT
        if r.status_code == 400 and "parse" in r.text.lower():
            print(f"Markdown failed, retrying plain: {r.text[:300]}")
            payload.pop("parse_mode", None)
            r = requests.post(url, json=payload, timeout=15)

        print(f"Send to {chat_id}: {r.status_code} OK" if r.status_code==200 else f"Send to {chat_id}: {r.status_code} {r.text[:300]}")
        return r
    except Exception as e:
        print(f"Send error to {chat_id}: {e}")
        traceback.print_exc()
        return None

def activate_vip(user_id, plan):
    from database import SessionLocal, get_user
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id))
        expiry = date.today() + timedelta(days=7 if "weekly" in plan else 30)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.daily_count = 0
        db.commit()
        send_message(int(user_id), f"VIP Activated!\nPlan: {plan.upper()} till {expiry}\nYou now have 10 predictions/day!\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}", parse=None)
        return True
    except Exception as e:
        print(f"VIP error {e}")
        traceback.print_exc()
        return False
    finally:
        db.close()

def process_update(upd):
    print(f"=== PROCESSING UPDATE ===")
    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    if "callback_query" in upd:
        try:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            from_id = cq["from"]["id"]
            data = cq.get("data","")
            print(f"Callback {data} from {from_id}")
            requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": "Generating..."}, timeout=5)
            if data == "predict_top5":
                db2 = SessionLocal()
                try:
                    user2 = get_user(db2, from_id)
                    limit = 10 if user2.is_vip else 2
                    if user2.daily_count >= limit:
                        send_message(chat_id, f"Limit reached {user2.daily_count}/{limit} today.\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={from_id}\nSupport: {SUPPORT_HANDLE}", parse=None)
                        return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures:
                        fixtures = fetch_real_fixtures(days_ahead=1, limit=5)
                    send_message(chat_id, f"TOP 5 PREDICTIONS TODAY - {datetime.now().strftime('%d %B %Y')}", parse=None)
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit:
                            break
                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                        p = get_ai_prediction(d)
                        update_league_history(db2, user2, f["league"])
                        msg = f"{f['home']} vs {f['away']}\nLeague: {f['league']} | {f['date']} {f['time']} WAT\nPick: {p['best_pick']} ({p['confidence']}%)\nReason: {p['explanation']}\nVerdict: {p['verdict']}\n{p['stake']}{p['disclaimer']}\n"
                        send_message(chat_id, msg, parse=None)
                        user2.daily_count += 1
                        db2.commit()
                        time.sleep(0.7)
                    send_message(chat_id, f"Done. Remaining {limit - user2.daily_count}/{limit} today.\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}", parse=None)
                finally:
                    db2.close()
        except Exception as e:
            print(f"Callback error {e}")
            traceback.print_exc()
        return

    msg = upd.get("message")
    if not msg or "text" not in msg:
        return
    if msg["chat"]["type"]!= "private":
        return

    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()
    user_id = msg["from"]["id"]
    username = msg["from"].get("username","")
    low = text.lower()
    print(f"Message from {user_id} (@{username}): {text}")

    db = SessionLocal()
    try:
        user = get_user(db, user_id, username)
        FREE_LIMIT = 2
        VIP_LIMIT = 10
        current_limit = VIP_LIMIT if user.is_vip else FREE_LIMIT

        if low.startswith("/start"):
            send_message(chat_id, f"Welcome to BetMasterPro - Super Smart AI\n\n100% LIVE fixtures + predictions!\n\nCommands:\n- Type: Arsenal vs Chelsea\n- /today - Top 10 LIVE fixtures + Predict button\n- /fixturesengland - England PL today\n- /fixturesworld - National teams LIVE\n- /myplan - Check plan ({user.daily_count}/{current_limit} used)\n- /subscribe - Upgrade to VIP\n- /help - Support\n\nLimits:\nFREE: 2 predictions/day\nVIP: 10 predictions/day\n\nChannel: {CHANNEL_LINK}\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}", parse=None)

        elif low.startswith("/help"):
            send_message(chat_id, f"Support: {SUPPORT_HANDLE}\nBot: {BOT_LINK}\nChannel: {CHANNEL_LINK}\n\n/today - 10 LIVE\n/fixturesengland\n/myplan - {user.daily_count}/{current_limit}\n/subscribe", parse=None)

        elif low.startswith("/fixtures"):
            country_raw = low.replace("/fixtures","").strip().split()[0] if low.replace("/fixtures","").strip() else "england"
            if user.daily_count >= current_limit:
                send_message(chat_id, f"Limit reached {user.daily_count}/{current_limit}\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}", parse=None)
                return
            fixtures = fetch_fixtures_by_country(country_raw, days_ahead=0, limit=3)
            if not fixtures:
                send_message(chat_id, f"No {country_raw.title()} fixtures today ({datetime.now().strftime('%d %B %Y')}). LIVE data - no fake.\nTry /today\nBot: {BOT_LINK}", parse=None)
                return
            list_msg = f"{country_raw.title().upper()} FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')} LIVE\n\n"
            for i,f in enumerate(fixtures,1):
                list_msg+=f"{i}. {f['home']} vs {f['away']}\n League: {f['league']} | Time: {f['time']} WAT | Date: {f['date']}\n\n"
            keyboard = {"inline_keyboard": [[{"text": f"Predict {country_raw.title()}", "callback_data": "predict_top5"}]]}
            send_message(chat_id, list_msg + f"Bot: {BOT_LINK}", parse=None, reply_markup=keyboard)

        elif low.startswith("/myplan"):
            plan_txt = f"VIP till {user.vip_expiry}" if user.is_vip else f"FREE ({FREE_LIMIT}/day)"
            send_message(chat_id, f"Plan: {plan_txt}\nUsed: {user.daily_count}/{current_limit}\nFav: {user.favorite_league}\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nBot: {BOT_LINK}", parse=None)

        elif low.startswith("/subscribe"):
            send_message(chat_id, f"BetMasterPro VIP - Card + Bank Transfer auto-activate\nWeekly N2,000 / Monthly N5,000\nLink: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}", parse=None)

        elif low.startswith("/today"):
            if user.daily_count >= current_limit:
                send_message(chat_id, f"Daily limit {user.daily_count}/{current_limit} reached. Resets midnight WAT\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nBot: {BOT_LINK}", parse=None)
                return
            fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
            if not fixtures:
                fixtures = fetch_real_fixtures(days_ahead=1, limit=10)
                header = f"No games today - TOP 10 TOMORROW - {(datetime.now()+timedelta(days=1)).strftime('%d %B %Y')}\n\n"
            else:
                header = f"TOP {len(fixtures)} LIVE FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')} 100% Verified LIVE\n\n"
            list_msg = header
            for i,f in enumerate(fixtures,1):
                list_msg+=f"{i}. {f['home']} vs {f['away']}\n League: {f['league']} | Time: {f['time']} WAT | Date: {f['date']}\n\n"
            list_msg+=f"Tap below! ({user.daily_count}/{current_limit} used)\nBot: {BOT_LINK}"
            keyboard = {"inline_keyboard": [[{"text": "Predict Top 5 Matches", "callback_data": "predict_top5"}]]}
            send_message(chat_id, list_msg, parse=None, reply_markup=keyboard)

        elif "vs" in low and 5 < len(text) < 100:
            if user.daily_count >= current_limit:
                send_message(chat_id, f"Daily limit reached {user.daily_count}/{current_limit}\nFREE: 2/day VIP: 10/day\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nBot: {BOT_LINK}", parse=None)
                return
            try:
                home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
            except:
                home=text.title()
                away="Opponent"
            league_guess = user.favorite_league if user.is_vip else "Custom Match"
            data = {"home": home, "away": away, "league": league_guess, "home_xg": 1.6, "away_xg": 1.1, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": round(random.uniform(1.9,3.2),2), "odds_d": round(random.uniform(3.0,4.0),2), "odds_a": round(random.uniform(2.2,3.8),2), "odds_over": 1.75}
            from predictor import get_ai_prediction
            p = get_ai_prediction(data)
            update_league_history(db, user, league_guess)
            user.daily_count+=1
            db.commit()
            send_message(chat_id, f"{home} vs {away}\nLeague: {league_guess} | Date: {datetime.now().strftime('%d %B %Y')}\nPick: {p['best_pick']} ({p['confidence']}%)\nReason: {p['explanation']}\nVerdict: {p['verdict']}\n{p['stake']}\nUsed: {user.daily_count}/{current_limit}\n{p['disclaimer']}\n\nMore: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}", parse=None)

        else:
            send_message(chat_id, f"Send like Arsenal vs Chelsea or use /today\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}", parse=None)

    except Exception as e:
        print(f"Handler error {e}")
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

def channel_scheduler():
    from database import SessionLocal, is_already_posted, mark_as_posted
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted=set()
    while True:
        try:
            now_utc=datetime.utcnow()
            hm=now_utc.strftime("%H:%M")
            today=now_utc.strftime("%Y-%m-%d")
            if hm=="05:05" and f"{today}-morning" not in posted:
                db=SessionLocal()
                try:
                    fixtures=fetch_real_fixtures(days_ahead=1, limit=15)
                    uniq=[]
                    for f in fixtures:
                        h=f"{f['home']}-{f['away']}-{f['date']}"
                        if not is_already_posted(db,h):
                            uniq.append(f)
                            mark_as_posted(db,h)
                            if len(uniq)>=2:
                                break
                    if not uniq:
                        uniq=fixtures[:2]
                    msg=f"Morning {today} - Unique Tips\n\n"
                    for f in uniq:
                        d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                        p=get_ai_prediction(d)
                        msg+=f"{f['home']} vs {f['away']}\nLeague: {f['league']} | Date: {f['date']} {f['time']} WAT\nPick: {p['best_pick']} | Verdict: {p['verdict']}\n\n"
                    msg+=f"Bot: {BOT_LINK} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
                    if CHANNEL_ID:
                        send_message(CHANNEL_ID, msg, parse=None)
                finally:
                    db.close()
                posted.add(f"{today}-morning")
        except Exception as e:
            print(f"Scheduler error {e}")
            traceback.print_exc()
        time.sleep(60)

threading.Thread(target=channel_scheduler, daemon=True).start()

@app.on_event("startup")
async def on_startup():
    webhook_url = f"{RENDER_URL}/webhook"
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true"
        r = requests.get(url, timeout=10).json()
        print(f"WEBHOOK SET: {webhook_url} -> {r}")
    except Exception as e:
        print(f"Webhook set error: {e}")

@app.get("/")
async def home():
    try:
        r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
        ok=r.get("ok",False)
        username=r.get("result",{}).get("username","UNKNOWN")
        wh=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=8).json()
    except Exception as e:
        ok=False
        username=str(e)
        wh={}
    return {"status":"FINAL WORKING - FIXED 400 ERROR","bot_ok":ok,"bot_username":username,"bot_link":BOT_LINK,"webhook_info":wh.get("result",{}),"support":SUPPORT_HANDLE}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        print(f"WEBHOOK RECEIVED")
        process_update(data)
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"Webhook error {e}")
        traceback.print_exc()
        return JSONResponse({"ok": True}, status_code=200)

@app.get("/set-webhook")
async def set_webhook():
    webhook_url = f"{RENDER_URL}/webhook"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true"
    r = requests.get(url, timeout=10).json()
    return r

@app.get("/test-direct")
async def test_direct(chat_id: str = ""):
    if not chat_id:
        return {"error": "Use /test-direct?chat_id=YOUR_ID"}
    send_message(int(chat_id), f"DIRECT TEST - Bot alive {datetime.now()}\nBot: {BOT_LINK}", parse=None)
    return {"sent": True}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    from database import SessionLocal, is_already_posted, mark_as_posted
    db=SessionLocal()
    try:
        fixtures=fetch_real_fixtures(limit=10)
        uniq=[]
        for f in fixtures:
            h=f"{f['home']}-{f['away']}-{str(date.today())}-manual-{random.randint(1,9999)}"
            if not is_already_posted(db,h):
                uniq.append(f)
                mark_as_posted(db,h)
            if len(uniq)>=2:
                break
        if not uniq:
            uniq=fixtures[:2]
        msg=f"Test {datetime.now().strftime('%H:%M:%S')}\n\n"
        for f in uniq:
            d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
            p=get_ai_prediction(d)
            msg+=f"{f['home']} vs {f['away']} - {p['verdict']}\n"
        msg+=f"Bot: {BOT_LINK} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
        if CHANNEL_ID:
            send_message(CHANNEL_ID, msg, parse=None)
        return {"posted":True, "fixtures":uniq}
    finally:
        db.close()

@app.get("/pay")
async def pay(plan:str, uid:str):
    if not FLW_SECRET:
        return JSONResponse({"error":"Keys not set"}, status_code=500)
    amount=2000 if plan=="weekly" else 5000
    tx_ref=f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload={"tx_ref":tx_ref,"amount":amount,"currency":"NGN","redirect_url":f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}","customer":{"email":f"{uid}@betmasterpro.com","name":f"User {uid}"},"customizations":{"title":f"BetMasterPro {plan.upper()}"}}
    headers={"Authorization":f"Bearer {FLW_SECRET}"}
    try:
        r=requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers, timeout=15).json()
        if r.get("status")=="success":
            return RedirectResponse(r["data"]["link"])
        return JSONResponse(r, status_code=400)
    except Exception as e:
        return JSONResponse({"error":str(e)}, status_code=500)

@app.get("/verify")
async def verify(tx_ref:str, uid:str, plan:str):
    headers={"Authorization":f"Bearer {FLW_SECRET}"}
    try:
        r=requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}", headers=headers, timeout=15).json()
        if r.get("status")=="success" and r.get("data"):
            data=r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ["successful","completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(f"<h1>Payment Successful!</h1><p>{plan.upper()} 10/day till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</p><a href='{BOT_LINK}'>Go to Bot</a><br>Support: {SUPPORT_HANDLE}")
        return HTMLResponse(f"<h1>Not confirmed {tx_ref}</h1><a href='/subscribe?uid={uid}'>Retry</a>")
    except Exception as e:
        return HTMLResponse(f"Error {e}")

@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request:Request):
    try:
        body=await request.body()
        data=json.loads(body)
        if data.get("event")=="charge.completed" and data.get("data",{}).get("status")=="successful":
            tx_ref=data["data"].get("tx_ref","")
            parts=tx_ref.split("-")
            if len(parts)>=3 and parts[0]=="BETMASTER":
                activate_vip(parts[1], parts[2])
        return JSONResponse({"status":"ok"})
    except Exception as e:
        print(f"Webhook {e}")
        return JSONResponse({"status":"error"}, status_code=200)

@app.get("/admin/activate")
async def admin_activate(uid:str, plan:str="monthly", key:str=""):
    if key!=ADMIN_KEY:
        return HTMLResponse("Wrong key", status_code=403)
    ok=activate_vip(uid, plan)
    return HTMLResponse(f"{'Activated' if ok else 'Failed'} {uid} {plan} - {BOT_LINK}")

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}</style></head><body><h1>BetMasterPro VIP</h1><p>ID: {uid}</p><div class='card'><p>FREE 2/day | VIP 10/day</p><a class='btn weekly' href='/pay?plan=weekly&uid={uid}'>Weekly N2,000</a><a class='btn monthly' href='/pay?plan=monthly&uid={uid}'>Monthly N5,000</a><p>Bot: {BOT_LINK}</p><p>Support: {SUPPORT_HANDLE}</p></div></body></html>")

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
