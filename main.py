import os, time, threading, requests, random
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")
GROUP_USERNAME = os.getenv("GROUP_USERNAME", "@betmasterpro")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")

app = FastAPI()

WELCOME_MSG = """🎯 Welcome to **BetMasterPro** 🎯

Your AI football prediction expert!

Here you can chat with me to get best predictions of ALL soccer matches worldwide.

**How to use:**
⚽ Send match: `Arsenal vs Chelsea`
📅 Today matches: `/today`
💎 My plan: `/myplan`
🆘 Help: `/help`

**Limits:**
🆓 Free: 2 predictions/day + 1 daily tip at 6AM WAT
💎 VIP: 10 predictions/day + 2 daily tips (6AM & 9PM WAT) tailored to your favorite league!

Join our channel for free tips:
https://t.me/+IFK0qoDI2B5lYWI0

Type any match to start!
Example: `Man City vs Liverpool`"""

def send_message(chat_id, text, parse="Markdown"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse}, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

# --- Core bot loop ---
def bot_polling_loop():
    if not BOT_TOKEN:
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass
    print("Polling started...")

    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_real_fixtures

    offset = 0
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    while True:
        try:
            resp = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30).json()
            if not resp.get("ok"):
                time.sleep(5); continue

            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!="private":
                    continue

                chat_id = msg["chat"]["id"]
                text = msg["text"].strip()
                user_id = msg["from"]["id"]
                username = msg["from"].get("username","")

                db = SessionLocal()
                try:
                    user = get_user(db, user_id, username)

                    # Commands
                    if text.startswith("/start"):
                        send_message(chat_id, WELCOME_MSG)

                    elif text.startswith("/help"):
                        send_message(chat_id, WELCOME_MSG)

                    elif text.startswith("/myplan"):
                        plan = "💎 VIP (10 chats/day + 2 daily tips)" if user.is_vip else "🆓 FREE (2 chats/day + 1 daily tip)"
                        fav = user.favorite_league or "Not set yet - chat more to set!"
                        send_message(chat_id, f"**Your Plan:** {plan}\n**Used today:** {user.daily_count}\n**Favorite League:** {fav}\n**Total chats:** {user.total_chats}\n\nUpgrade: https://betmaster-p09f.onrender.com/subscribe")

                    elif text.startswith("/today"):
                        # Check limit for /today too
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"⚠️ Daily limit reached ({limit}).\nFree users: 2/day\nVIP: 10/day\n\nUpgrade here: https://betmaster-p09f.onrender.com/subscribe\n\nResets in 24h.")
                            continue

                        send_message(chat_id, "📅 Fetching today's matches from all leagues...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=5, fav_league=user.favorite_league if user.is_vip else None)
                        for f in fixtures:
                            data = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                            pred = get_ai_prediction(data)
                            update_league_history(db, user, f["league"])
                            send_message(chat_id, f"**{f['home']} vs {f['away']}**\n🏆 {f['league']} | ⏰ {f['time']} | 📅 Today\n💰 {f['odds_h']} / {f['odds_d']} / {f['odds_a']}\n🎯 **{pred['best_pick']}** ({pred['confidence']}%)\n{pred['explanation']}")

                        user.daily_count += 1
                        db.commit()

                    elif "vs" in text.lower() and len(text) > 5:
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 You've used {user.daily_count}/{limit} chats today.\n\n**Even if you clear history, I remember** - your limit resets in 24hrs.\n\n💎 Upgrade to VIP for 10 chats/day + personalized daily tips:\nhttps://betmaster-p09f.onrender.com/subscribe\n\nJoin channel for free tip: https://t.me/+IFK0qoDI2B5lYWI0")
                            continue

                        send_message(chat_id, f"🔍 Analyzing {text}...")
                        try:
                            parts = text.lower().split("vs")
                            home = parts[0].strip().title()
                            away = parts[1].strip().title()
                        except:
                            home = text.title(); away = "Opponent"

                        league_guess = user.favorite_league if user.is_vip else "Custom"
                        data = {"home":home,"away":away,"league":league_guess,"home_xg":1.6,"away_xg":1.1,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":2.1,"odds_d":3.2,"odds_a":3.4,"odds_over":1.75}
                        pred = get_ai_prediction(data)

                        update_league_history(db, user, league_guess)
                        user.daily_count += 1
                        db.commit()

                        send_message(chat_id, f"⚽ **{home} vs {away}**\n🏆 {league_guess}\n\n🎯 **Pick: {pred['best_pick']}**\n📊 Confidence: {pred['confidence']}%\n📝 {pred['explanation']}\n\n💰 Suggested odds: 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n{user.daily_count}/{limit} used today. /myplan to check")

                    else:
                        send_message(chat_id, "Send match like:\n`Arsenal vs Chelsea`\nor use /today for today's games\n/help for guide")

                except Exception as e:
                    print(f"Handler error: {e}"); db.rollback()
                finally:
                    db.close()

        except Exception as e:
            print(f"Poll loop: {e}"); time.sleep(5)

def channel_scheduler():
    from database import SessionLocal, get_all_users
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted = set()

    while True:
        try:
            now_utc = datetime.utcnow()
            # WAT = UTC+1: 6AM WAT = 5AM UTC, 9PM WAT = 20PM UTC
            hm = now_utc.strftime("%H:%M")
            today = now_utc.strftime("%Y-%m-%d")
            key = f"{today}-{hm}"

            # 05:05 UTC = 6:05 AM WAT - ALL USERS + Channel
            # 20:05 UTC = 9:05 PM WAT - VIP ONLY + Channel
            if hm == "05:05" and f"{today}-morning" not in posted:
                print("Morning broadcast 6AM WAT")
                # 1. Channel post (2 matches)
                fixtures = fetch_real_fixtures(days_ahead=1, limit=2)
                msg = f"🔥 **Morning VIP Tips - {today}** 🔥\nMatches in 1-2 days:\n\n"
                for f in fixtures:
                    data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                    pred = get_ai_prediction(data)
                    msg += f"**{f['home']} vs {f['away']}** ({f['league']})\n🎯 {pred['best_pick']} ({pred['confidence']}%)\n\n"
                msg += f"Bot: @Betmasterpro_bot"
                if CHANNEL_ID:
                    send_message(CHANNEL_ID, msg)

                # 2. Personal DM to all users (free 1, VIP 2 with fav league)
                db = SessionLocal()
                try:
                    for u in get_all_users(db):
                        try:
                            fav = u.favorite_league if u.is_vip else None
                            fxs = fetch_real_fixtures(days_ahead=random.randint(1,3), limit=2 if u.is_vip else 1, fav_league=fav)
                            pmsg = f"☀️ Good Morning! Your daily tip:\n\n" if not u.is_vip else f"☀️ Good Morning VIP! Your personalized {u.favorite_league} tips:\n\n"
                            for f in fxs:
                                data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                                pred = get_ai_prediction(data)
                                pmsg += f"**{f['home']} vs {f['away']}**\n🎯 {pred['best_pick']} - {pred['explanation']}\n\n"
                            if not u.is_vip:
                                pmsg += f"💎 Want 2 tips daily + 10 chats? Upgrade:\nhttps://betmaster-p09f.onrender.com/subscribe"
                            send_message(u.user_id, pmsg)
                            time.sleep(0.3) # avoid flood
                        except Exception as e:
                            print(f"DM fail {u.user_id}: {e}")
                finally:
                    db.close()

                posted.add(f"{today}-morning")

            if hm == "20:05" and f"{today}-evening" not in posted:
                print("Evening broadcast 9PM WAT - VIP only")
                # Evening only for VIP + channel second post
                fixtures = fetch_real_fixtures(days_ahead=1, limit=2)
                msg = f"🌙 **Evening VIP Tips - {today}**\n\n"
                for f in fixtures:
                    data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                    pred = get_ai_prediction(data)
                    msg += f"**{f['home']} vs {f['away']}**\n🎯 {pred['best_pick']}\n\n"
                if CHANNEL_ID:
                    send_message(CHANNEL_ID, msg)

                db = SessionLocal()
                try:
                    for u in get_all_users(db):
                        if not u.is_vip: continue
                        try:
                            fxs = fetch_real_fixtures(days_ahead=random.randint(1,2), limit=2, fav_league=u.favorite_league)
                            pmsg = f"🌙 Evening VIP {u.favorite_league} tips:\n\n"
                            for f in fxs:
                                data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                                pred = get_ai_prediction(data)
                                pmsg += f"**{f['home']} vs {f['away']}**\n🎯 {pred['best_pick']} - {pred['explanation']}\n\n"
                            send_message(u.user_id, pmsg)
                            time.sleep(0.3)
                        except: pass
                finally:
                    db.close()

                posted.add(f"{today}-evening")

            # Clear old keys
            if len(posted) > 10:
                posted.clear()

        except Exception as e:
            print(f"Scheduler error: {e}")

        time.sleep(60)

threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

@app.get("/")
async def home():
    return {"status":"LIVE","bot":True,"channel":CHANNEL_ID}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    fixtures = fetch_real_fixtures(days_ahead=1, limit=2)
    msg = "🔥 **Test Tips**\n\n"
    for f in fixtures:
        data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
        pred = get_ai_prediction(data)
        msg += f"{f['home']} vs {f['away']} - {pred['best_pick']}\n"
    if CHANNEL_ID:
        send_message(CHANNEL_ID, msg)
    return {"posted": True, "fixtures": fixtures}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe():
    html = f"""
    <html><head><title>BetMasterPro VIP</title></head>
    <body style="font-family:sans-serif;text-align:center;padding:30px">
    <h1>💎 BetMasterPro VIP</h1>
    <p>🆓 Free: 2 chats/day + 1 morning tip</p>
    <p>💎 VIP: 10 chats/day + 2 tips daily (6AM & 9PM WAT) tailored to your favorite league</p>
    <p>Pay with Paystack to activate VIP</p>
    <a href="https://t.me/Betmasterpro_bot" style="background:green;color:white;padding:15px 30px;text-decoration:none;border-radius:10px">Chat with Bot</a>
    <p><a href="https://t.me/+IFK0qoDI2B5lYWI0">Join Channel</a></p>
    </body></html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
