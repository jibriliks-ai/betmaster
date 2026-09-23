import os, time, pathlib, threading, requests
print("=== BetMaster Starting ===")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
GROUP_USERNAME = os.getenv("GROUP_USERNAME", "@betmasterpro")

# Fix channel ID - add -100 if user forgot
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")
    print(f"Fixed CHANNEL_ID to {CHANNEL_ID}")

app = FastAPI()

@app.get("/")
async def home():
    return {"status": "LIVE", "bot": bool(BOT_TOKEN), "channel": CHANNEL_ID}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe():
    return HTMLResponse(f"<h1>BetMaster Pro LIVE</h1><p>Bot @Betmasterpro_bot</p><p>Channel {CHANNEL_ID}</p>")

@app.get("/post-now")
async def post_now():
    # Manual post for testing
    threading.Thread(target=post_to_channel, daemon=True).start()
    return {"posted": True, "channel": CHANNEL_ID}

# ---- Safe imports ----
try:
    from database import SessionLocal, get_user
    from predictor import get_ai_prediction
    DB_OK = True
    print("DB and predictor loaded OK")
except Exception as e:
    DB_OK = False
    print(f"DB/Predictor load failed: {e}")
    import traceback; traceback.print_exc()

def fetch_fixtures():
    pool = [
        {"home":"Arsenal","away":"Chelsea","league":"Premier League","time":"15:00","odds_h":2.1,"odds_d":3.3,"odds_a":3.4},
        {"home":"Man City","away":"Liverpool","league":"Premier League","time":"17:30","odds_h":2.0,"odds_d":3.5,"odds_a":3.6},
        {"home":"Man United","away":"Tottenham","league":"Premier League","time":"15:00","odds_h":2.3,"odds_d":3.2,"odds_a":3.0},
    ]
    import random
    return random.sample(pool, 2)

def post_to_channel():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("No BOT_TOKEN or CHANNEL_ID")
        return
    try:
        import random
        fixtures = fetch_fixtures()
        msg = f"🔥 BetMaster Pro VIP Tips {time.strftime('%d %b')}\n\n"
        for f in fixtures:
            msg += f"{f['home']} vs {f['away']} ({f['league']})\nPick: Over 1.5 - Odds {f['odds_h']}\n\n"
        msg += f"More? @Betmasterpro_bot"
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHANNEL_ID, "text": msg}, timeout=10)
        print(f"Channel post result: {r.text[:200]}")
    except Exception as e:
        print(f"post_to_channel error: {e}")

def bot_polling_loop():
    if not BOT_TOKEN or not DB_OK:
        print("Polling disabled - no token or DB error")
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("Webhook deleted, polling start")
    except: pass
    offset = 0
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    while True:
        try:
            resp = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30).json()
            if not resp.get("ok"): time.sleep(5); continue
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!="private": continue
                chat_id = msg["chat"]["id"]; text = msg["text"]; uid = msg["from"]["id"]
                db = SessionLocal()
                try:
                    user = get_user(db, uid)
                    if "/start" in text:
                        requests.post(f"{base}/sendMessage", json={"chat_id": chat_id, "text": "Send: Arsenal vs Chelsea"})
                    elif "vs" in text.lower():
                        requests.post(f"{base}/sendMessage", json={"chat_id": chat_id, "text": f"Analyzing {text}..."})
                        parts = text.lower().split("vs"); home = parts[0].strip().title(); away = parts[1].strip().title() if len(parts)>1 else "Away"
                        data={"home":home,"away":away,"league":"Custom","home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":2.1,"odds_d":3.2,"odds_a":3.4,"odds_over":1.75}
                        pred = get_ai_prediction(data)
                        requests.post(f"{base}/sendMessage", json={"chat_id": chat_id, "text": f"{home} vs {away}\nPick: {pred['best_pick']} {pred['confidence']}%\n{pred['explanation']}"})
                    db.commit()
                except Exception as e:
                    print(f"handler {e}"); db.rollback()
                finally: db.close()
        except Exception as e:
            print(f"poll loop {e}"); time.sleep(5)

# Start threads AFTER app defined
threading.Thread(target=bot_polling_loop, daemon=True).start()
print("Bot thread started")

# Keep Render happy - must bind port
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    print(f"Starting uvicorn on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
