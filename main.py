import os, time, pathlib, threading, requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import uvicorn

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
GROUP_USERNAME = os.getenv("GROUP_USERNAME", "@betmasterpro")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")

app = FastAPI()

def bot_polling_loop():
    if not BOT_TOKEN:
        print("No BOT_TOKEN")
        return
    print(f"Starting SIMPLE polling for @Betmasterpro_bot ...")
    # Delete webhook first
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("Webhook deleted")
    except Exception as e:
        print(f"Webhook delete error: {e}")

    from database import SessionLocal, get_user
    from predictor import get_ai_prediction

    offset = 0
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    
    while True:
        try:
            resp = requests.get(f"{base_url}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=35)
            data = resp.json()
            if not data.get("ok"):
                print(f"getUpdates error: {data}")
                time.sleep(5)
                continue
            
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg or "text" not in msg:
                    continue
                chat_id = msg["chat"]["id"]
                text = msg["text"].strip()
                user_id = msg["from"]["id"]
                
                # Only private chats
                if msg["chat"]["type"] != "private":
                    continue
                
                db = SessionLocal()
                try:
                    user = get_user(db, user_id)
                    
                    if text.startswith("/start"):
                        requests.post(f"{base_url}/sendMessage", json={
                            "chat_id": chat_id,
                            "text": f"Welcome to BetMaster Pro! 🎯\n\nType: Arsenal vs Chelsea\nYou: {user.daily_count}/2 today\nVIP: {user.daily_count}/10\nJoin: {GROUP_USERNAME}"
                        })
                    elif len(text) > 3:
                        if user.daily_count >= 2 and not user.is_vip:
                            requests.post(f"{base_url}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": f"Daily limit reached (2). Join {GROUP_USERNAME} for VIP"
                            })
                        else:
                            requests.post(f"{base_url}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": f"Analyzing {text}..."
                            })
                            pred_data = {"home": text.title(), "away": "Away", "league": "Custom", "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": 2.1, "odds_d": 3.2, "odds_a": 3.4, "odds_over": 1.75}
                            pred = get_ai_prediction(pred_data)
                            user.daily_count += 1
                            requests.post(f"{base_url}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": f"{text}\n\nPick: {pred['best_pick']}\nConfidence: {pred['confidence']}%\n\n{pred['explanation']}"
                            })
                    db.commit()
                except Exception as e:
                    print(f"Handler error: {e}")
                    db.rollback()
                finally:
                    db.close()
        except Exception as e:
            print(f"Polling loop error: {e}")
            time.sleep(5)

threading.Thread(target=bot_polling_loop, daemon=True).start()

@app.get("/")
async def home():
    return {"status": "LIVE", "bot": True, "username": "Betmasterpro_bot", "group": GROUP_USERNAME}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe():
    p = pathlib.Path("static/index.html")
    if p.exists():
        html = p.read_text().replace("{{PUBLIC_KEY}}", PAYSTACK_PUBLIC_KEY).replace("{{GROUP_USERNAME}}", GROUP_USERNAME)
        return HTMLResponse(html)
    return HTMLResponse(f"<h1>BetMaster Pro</h1><p>Join {GROUP_USERNAME}</p><p>Bot: @Betmasterpro_bot LIVE</p>")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
