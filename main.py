import os, pathlib, threading, asyncio
from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import uvicorn

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
GROUP_USERNAME = os.getenv("GROUP_USERNAME", "@betmasterpro")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")

app = FastAPI()

def start_bot_polling():
    if not BOT_TOKEN:
        print("No BOT_TOKEN - skipping bot")
        return
    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
        from database import SessionLocal, get_user
        from predictor import get_ai_prediction

        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            db = SessionLocal()
            user = get_user(db, update.effective_user.id)
            db.commit()
            await update.message.reply_text(f"Welcome! Type: Arsenal vs Chelsea\nYou: {user.daily_count}/2 today")
            db.close()

        async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.message.chat.type!= "private": return
            text = (update.message.text or "").strip()
            if len(text) < 4 or text.startswith("/"): return
            db = SessionLocal()
            user = get_user(db, update.effective_user.id)
            if user.daily_count >= 2 and not user.is_vip:
                await update.message.reply_text(f"Limit reached. Join {GROUP_USERNAME}")
                db.close(); return
            await update.message.reply_text(f"Analyzing {text}...")
            data = {"home": text.title(), "away": "Away", "league": "Custom", "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": 2.1, "odds_d": 3.2, "odds_a": 3.4, "odds_over": 1.75}
            pred = get_ai_prediction(data)
            user.daily_count += 1; db.commit()
            await update.message.reply_text(f"{text}\nPick: {pred['best_pick']}\n{pred['explanation']}")
            db.close()

        print("Building Telegram Application...")
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, predict))
        print("Starting polling (this fixes the Updater bug)...")
        application.run_polling(drop_pending_updates=True)

    except Exception as e:
        print(f"Bot crashed: {e}")
        import traceback; traceback.print_exc()

threading.Thread(target=start_bot_polling, daemon=True).start()

@app.get("/")
async def home():
    return {"status": "LIVE", "bot": bool(BOT_TOKEN), "group": GROUP_USERNAME}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe():
    p = pathlib.Path("static/index.html")
    if p.exists():
        html = p.read_text().replace("{{PUBLIC_KEY}}", PAYSTACK_PUBLIC_KEY).replace("{{GROUP_USERNAME}}", GROUP_USERNAME)
        return HTMLResponse(html)
    return HTMLResponse(f"<h1>BetMaster Pro</h1><p>Join {GROUP_USERNAME}</p>")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
