import os, asyncio, pathlib, threading
from datetime import date, datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import uvicorn

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
GROUP_USERNAME = os.getenv("GROUP_USERNAME", "@betmasterpro").strip() or "@betmasterpro"
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "").strip()
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET", "").strip()
WEBSITE_URL = os.getenv("WEBSITE_URL", "").strip()

def safe_admin_id():
    raw = os.getenv("ADMIN_ID", "0") or "0"
    try:
        # Extract first number from string
        import re
        m = re.search(r"\d+", str(raw))
        return int(m.group()) if m else 0
    except:
        return 0

ADMIN_ID = safe_admin_id()
print(f"STARTUP: ADMIN_ID={ADMIN_ID} BOT_TOKEN={'YES' if BOT_TOKEN else 'NO'} GROUP={GROUP_USERNAME}")

app = FastAPI(title="BetMaster Bot")

telegram_app = None
if BOT_TOKEN:
    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
        from database import SessionLocal, get_user
        from fetcher import get_todays_fixtures, get_odds_from_api_football
        from predictor import get_ai_prediction

        telegram_app = Application.builder().token(BOT_TOKEN).build()
        FREE_LIMIT=2; VIP_LIMIT=10

        def check_limit(user):
            limit = VIP_LIMIT if getattr(user, 'is_vip', False) else FREE_LIMIT
            return user.daily_count < limit, limit

        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            db = SessionLocal()
            user = get_user(db, update.effective_user.id)
            user.username = update.effective_user.username or ""
            db.commit()
            sub_url = (WEBSITE_URL + "/subscribe") if WEBSITE_URL else "/subscribe"
            keyboard = [
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{GROUP_USERNAME.replace('@','')}")],
                [InlineKeyboardButton("Subscribe N2000", url=sub_url)],
            ]
            limit = VIP_LIMIT if getattr(user, 'is_vip', False) else FREE_LIMIT
            msg = f"Welcome to BetMaster!\nFREE {FREE_LIMIT}/day VIP {VIP_LIMIT}/day\nType: Arsenal vs Chelsea\nYou: {user.daily_count}/{limit}"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
            db.close()

        async def predict_any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.message.chat.type != "private":
                return
            text = (update.message.text or "").strip()
            if len(text) < 4 or text.startswith("/") or "http" in text.lower():
                return
            db = SessionLocal()
            user = get_user(db, update.effective_user.id)
            can_predict, limit = check_limit(user)
            if not can_predict:
                await update.message.reply_text(f"Limit {limit}/{limit} Join {GROUP_USERNAME} for more")
                db.close(); return
            await update.message.reply_text(f"Analyzing {text}...")
            if "vs" in text.lower():
                p=text.lower().split("vs"); home=p[0].strip().title(); away=p[1].strip().title()
            else:
                home=text.title(); away="Away"
            data={"home":home,"away":away,"league":"Custom","home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":2.1,"odds_d":3.2,"odds_a":3.4,"odds_over":1.75}
            pred=get_ai_prediction(data); user.daily_count+=1; db.commit()
            await update.message.reply_text(f"{home} vs {away}\nPick: {pred['best_pick']} {pred['confidence']}\n{pred['explanation']}\nLeft {limit-user.daily_count}/{limit}")
            db.close()

        async def daily_group_post(context: ContextTypes.DEFAULT_TYPE):
            try:
                fixtures = get_todays_fixtures()[:3]
                if not fixtures: return
                text = f"Top 3 Picks {date.today()} \n\n"
                for f in fixtures:
                    data={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.6,"away_xg":1.1,"home_form":"WWDWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":2.1,"odds_d":3.2,"odds_a":3.4,"odds_over":1.75}
                    pred=get_ai_prediction(data)
                    text+=f"{f['home']} vs {f['away']} -> {pred['best_pick']}\n"
                text+=f"Add @{context.bot.username} & type any match"
                await context.bot.send_message(chat_id=GROUP_USERNAME, text=text)
            except Exception as e:
                print(f"Group post fail: {e}")

        async def addvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if ADMIN_ID==0 or update.effective_user.id != ADMIN_ID:
                await update.message.reply_text("Not authorized"); return
            try:
                tg_id=int(context.args[0]); days=int(context.args[1])
                db=SessionLocal(); user=get_user(db,tg_id); user.is_vip=True; user.vip_expiry=date.today()+timedelta(days=days); db.commit()
                await update.message.reply_text(f"VIP {tg_id} till {user.vip_expiry}"); db.close()
            except Exception as e:
                await update.message.reply_text(f"Use: /addvip <id> <days> {e}")

        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("addvip", addvip))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, predict_any_text))

        async def run_bot():
            try:
                await telegram_app.initialize()
                await telegram_app.start()
                await telegram_app.updater.start_polling()
                print("Telegram bot polling started")
            except Exception as e:
                print(f"Bot failed to start: {e}")

        def bot_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_bot())
            loop.run_forever()

        threading.Thread(target=bot_thread, daemon=True).start()
        print("Telegram thread started")

    except Exception as e:
        print(f"Telegram init error (non-fatal): {e}")
        telegram_app = None
else:
    print("No BOT_TOKEN - website only mode")

@app.get("/")
async def home():
    return {
        "status": "LIVE - BetMaster working",
        "bot_token_set": bool(BOT_TOKEN),
        "admin_id": ADMIN_ID,
        "group": GROUP_USERNAME,
        "website": "/subscribe",
        "paystack_set": bool(PAYSTACK_PUBLIC_KEY),
        "openrouter_set": bool(os.getenv("OPENROUTER_KEY")),
        "database": "postgres" if os.getenv("DATABASE_URL") else "sqlite (fallback)"
    }

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page():
    p = pathlib.Path("static/index.html")
    if not p.exists():
        return HTMLResponse(f"<h1>BetMaster Pro</h1><p>VIP N2000/month</p><p>Contact admin in {GROUP_USERNAME}</p><p>Status: { 'PAYSTACK READY' if PAYSTACK_PUBLIC_KEY else 'Add PAYSTACK_PUBLIC_KEY to enable pay'}</p>")
    html = p.read_text(encoding="utf-8", errors="ignore")
    html = html.replace("{{PUBLIC_KEY}}", PAYSTACK_PUBLIC_KEY or "pk_test_placeholder")
    html = html.replace("{{GROUP_USERNAME}}", GROUP_USERNAME)
    return HTMLResponse(html)

@app.get("/health")
async def health():
    return {"ok": True}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    print(f"Starting FastAPI on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)