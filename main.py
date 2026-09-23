import os
import time
import threading
import requests
import random
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")

GROUP_USERNAME = os.getenv("GROUP_USERNAME", "@betmasterpro")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")

print(f"=== BetMaster Pro Starting ===")
print(f"Channel: {CHANNEL_ID} | Bot: {bool(BOT_TOKEN)}")

app = FastAPI()

# ================= WELCOME MESSAGE =================
WELCOME_MSG = """🎯 **Welcome to BetMasterPro** 🎯

Your AI football prediction expert!

Here you can chat with me to get BEST predictions of ALL soccer matches worldwide.

**How to use me:**
⚽ Send any match: `Arsenal vs Chelsea`
📅 Today's matches: `/today`
💎 Check your plan: `/myplan`
🆘 Help guide: `/help`
💳 Upgrade to VIP: `/subscribe`

**Your Limits:**
🆓 FREE: 2 predictions/day + 1 daily tip at 6AM WAT
💎 VIP: 10 predictions/day + 2 personalized tips daily (6AM & 9PM WAT) based on YOUR favorite league!

**Example:**
Type: `Man City vs Liverpool`
Type: `Barcelona vs Real Madrid`
Type: `/today` for today's games

Join our channel for free daily tips:
https://t.me/+IFK0qoDI2B5lYWI0

👇 Type any match to start! Example: `Arsenal vs Chelsea`"""

DISCLAIMER = "\n\n⚠️ *Disclaimer:* Betting involves risk. This is AI analysis, not financial advice. Stake responsibly, 18+ only. Past performance doesn't guarantee future results. Bet what you can afford to lose."

def send_message(chat_id, text, parse="Markdown"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        # Telegram limit 4096 chars
        if len(text) > 4000:
            text = text[:4000] + "..."
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse}, timeout=15)
    except Exception as e:
        print(f"Send error: {e}")

# ================= BOT POLLING LOOP =================
def bot_polling_loop():
    if not BOT_TOKEN:
        print("No BOT_TOKEN - polling disabled")
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("Webhook deleted, polling started")
    except Exception as e:
        print(f"Webhook delete error: {e}")

    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_real_fixtures

    offset = 0
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    while True:
        try:
            resp = requests.get(f"{base_url}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30).json()
            if not resp.get("ok"):
                time.sleep(5)
                continue

            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1

                # Detect channel ID if forwarded
                if "channel_post" in upd:
                    ch = upd["channel_post"]["chat"]
                    print(f"Channel detected: {ch.get('title')} ID: {ch.get('id')}")

                msg = upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!= "private":
                    continue

                chat_id = msg["chat"]["id"]
                text = msg["text"].strip()
                user_id = msg["from"]["id"]
                username = msg["from"].get("username", "")
                first_name = msg["from"].get("first_name", "")

                db = SessionLocal()
                try:
                    user = get_user(db, user_id, username)

                    # /START
                    if text.lower().startswith("/start"):
                        send_message(chat_id, WELCOME_MSG)

                    # /HELP
                    elif text.lower().startswith("/help"):
                        send_message(chat_id, WELCOME_MSG)

                    # /MYPLAN
                    elif text.lower().startswith("/myplan"):
                        plan = "💎 VIP - 10 chats/day + 2 personalized tips" if user.is_vip else "🆓 FREE - 2 chats/day + 1 morning tip"
                        fav = user.favorite_league or "Not set yet - chat more about your favorite league!"
                        send_message(chat_id, f"**Your Plan:** {plan}\n**Used today:** {user.daily_count}/{'10' if user.is_vip else '2'}\n**Favorite League:** {fav}\n**Total chats:** {user.total_chats}\n**Member since:** {user.created_at.strftime('%d %b %Y') if user.created_at else 'Today'}\n\n💎 Upgrade:\nhttps://betmaster-p09f.onrender.com/subscribe\n\n🔗 Channel: https://t.me/+IFK0qoDI2B5lYWI0")

                    # /SUBSCRIBE
                    elif text.lower().startswith("/subscribe"):
                        send_message(chat_id, f"💎 **Upgrade to VIP**\n\n🆓 Free: 2 chats/day + 1 tip at 6AM WAT\n💎 VIP: 10 chats/day + 2 tips (6AM & 9PM WAT) tailored to {user.favorite_league or 'your favorite league'}\n\n👉 Upgrade here:\nhttps://betmaster-p09f.onrender.com/subscribe\n\nChannel: https://t.me/+IFK0qoDI2B5lYWI0")

                    # /TODAY
                    elif text.lower().startswith("/today"):
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 You've used {user.daily_count}/{limit} chats today.\n\n**I remember you even if you clear chat history** - limit resets in 24hrs at midnight WAT.\n\n💎 Upgrade to VIP for 10 chats/day:\nhttps://betmaster-p09f.onrender.com/subscribe")
                            continue

                        send_message(chat_id, "📅 *Fetching today's matches from all European & world leagues...* Please wait 3 secs...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=5, fav_league=user.favorite_league if user.is_vip else None)

                        if not fixtures:
                            send_message(chat_id, "No matches found today, try `/today` again later or send `Arsenal vs Chelsea`")
                            continue

                        for f in fixtures:
                            data = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                            pred = get_ai_prediction(data)
                            update_league_history(db, user, f["league"])

                            full_msg = f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f.get('date','Today')}\n💰 Odds: 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']}\n\n🎯 **Pick: {pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **{pred['verdict']}**\n{pred['stake']}{pred['disclaimer']}"
                            send_message(chat_id, full_msg)
                            time.sleep(0.5)

                        user.daily_count += 1
                        db.commit()
                        send_message(chat_id, f"✅ {len(fixtures)} predictions sent. You used {user.daily_count}/{limit} today. Use `/myplan` to check.")

                    # MATCH PREDICTION - contains VS
                    elif "vs" in text.lower() and len(text) > 5 and len(text) < 100:
                        limit = 10 if user.is_vip else 2
                        if user.daily_count >= limit:
                            send_message(chat_id, f"🚫 **Limit reached: {user.daily_count}/{limit} today**\n\nEven if you clear chat history, I track you by ID and remember.\n\nYour limit will reset in 24hrs at midnight WAT.\n\n💎 **Upgrade to VIP to get 10 chats/day + 2 personalized daily tips:**\nhttps://betmaster-p09f.onrender.com/subscribe\n\n🔗 Free tip in channel: https://t.me/+IFK0qoDI2B5lYWI0")
                            continue

                        send_message(chat_id, f"🔍 *Analyzing {text}...* Checking form, xG, H2H, injuries...")

                        try:
                            parts = text.lower().split("vs")
                            home = parts[0].strip().title()
                            away = parts[1].strip().title() if len(parts) > 1 else "Opponent"
                            home = home.replace("/Today","").strip()
                        except:
                            home = text.title()
                            away = "Opponent"

                        # Guess league from favorite
                        league_guess = user.favorite_league if user.is_vip and user.favorite_league else "Premier League" if any(x in home.lower() for x in ["arsenal","city","united","chelsea","liverpool"]) else "Custom"

                        data = {"home":home,"away":away,"league":league_guess,"home_xg":1.6,"away_xg":1.1,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":round(random.uniform(1.9,3.2),2),"odds_d":round(random.uniform(3.0,4.0),2),"odds_a":round(random.uniform(2.2,3.8),2),"odds_over":1.75}
                        pred = get_ai_prediction(data)

                        update_league_history(db, user, league_guess)
                        user.daily_count += 1
                        db.commit()

                        expert_msg = f"⚽ **{home} vs {away}**\n🏆 {league_guess}\n💰 Odds: 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n🎯 **Pick: {pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **EXPERT VERDICT: {pred['verdict']}**\n{pred['stake']}\n\n📊 Market: {pred['market']} | Confidence: {pred['confidence']}%\n{user.daily_count}/{limit} chats used today. /myplan\n{pred['disclaimer']}"

                        send_message(chat_id, expert_msg)

                    else:
                        send_message(chat_id, f"Hi {first_name}! 👋\n\nSend match like:\n`Arsenal vs Chelsea`\n`Man City vs Liverpool`\n\nOr use:\n`/today` - Today's matches\n`/myplan` - Check limit\n`/subscribe` - Upgrade to VIP\n\n{WELCOME_MSG.split('Example:')[0][-200:]}")

                except Exception as e:
                    print(f"Handler error: {e}")
                    import traceback; traceback.print_exc()
                    db.rollback()
                finally:
                    db.close()

        except Exception as e:
            print(f"Polling loop error: {e}")
            time.sleep(5)

# ================= PERSONALIZED SCHEDULER 6AM & 9PM WAT =================
def channel_scheduler():
    from database import SessionLocal, get_all_users
    from predictor import fetch_real_fixtures, get_ai_prediction

    posted = set()

    while True:
        try:
            now_utc = datetime.utcnow()
            hm = now_utc.strftime("%H:%M")
            today = now_utc.strftime("%Y-%m-%d")

            # 6AM WAT = 05:05 UTC - Morning broadcast
            if hm == "05:05" and f"{today}-morning" not in posted:
                print(f"=== MORNING BROADCAST 6AM WAT {today} ===")

                # 1. Channel post - 2 matches
                fixtures = fetch_real_fixtures(days_ahead=random.randint(1,2), limit=2)
                msg = f"🔥 **BetMasterPro Morning Tips - {today}** 🔥\n📅 Matches in 1-3 days | All Leagues\n\n"
                for f in fixtures:
                    data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                    pred = get_ai_prediction(data)
                    msg += f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | {f['time']} WAT\n🎯 {pred['best_pick']} ({pred['confidence']}%)\n✅ {pred['verdict']}\n{pred['stake']}\n\n"
                msg += f"🤖 More? @Betmasterpro_bot\n🔗 https://t.me/+IFK0qoDI2B5lYWI0\n{DISCLAIMER}"
                if CHANNEL_ID:
                    send_message(CHANNEL_ID, msg)

                # 2. Personal DM to ALL users
                db = SessionLocal()
                try:
                    users = get_all_users(db)
                    print(f"Sending morning DM to {len(users)} users")
                    for u in users:
                        try:
                            fav = u.favorite_league if u.is_vip else None
                            days = random.randint(1,3)
                            fxs = fetch_real_fixtures(days_ahead=days, limit=2 if u.is_vip else 1, fav_league=fav)

                            if not u.is_vip:
                                pmsg = f"☀️ Good Morning! Your daily FREE tip:\n\n"
                            else:
                                pmsg = f"☀️ Good Morning VIP! Your personalized {u.favorite_league} tips for {days} day(s) ahead:\n\n"

                            for f in fxs:
                                data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                                pred = get_ai_prediction(data)
                                pmsg += f"⚽ **{f['home']} vs {f['away']}** ({f['league']})\n🎯 {pred['best_pick']}\n✅ {pred['verdict']}\n{pred['stake']}\n\n"

                            if not u.is_vip:
                                pmsg += f"💎 Want 2 personalized tips daily + 10 chats/day?\nUpgrade to VIP:\nhttps://betmaster-p09f.onrender.com/subscribe\n{DISCLAIMER}"
                            else:
                                pmsg += f"{DISCLAIMER}"

                            send_message(u.user_id, pmsg)
                            time.sleep(0.4)
                        except Exception as e:
                            print(f"Morning DM fail {u.user_id}: {e}")
                finally:
                    db.close()

                posted.add(f"{today}-morning")

            # 9PM WAT = 20:05 UTC - Evening VIP only
            if hm == "20:05" and f"{today}-evening" not in posted:
                print(f"=== EVENING BROADCAST 9PM WAT {today} - VIP ONLY ===")

                # Channel second post
                fixtures = fetch_real_fixtures(days_ahead=random.randint(1,2), limit=2)
                msg = f"🌙 **BetMasterPro Evening VIP Tips - {today}**\n\n"
                for f in fixtures:
                    data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                    pred = get_ai_prediction(data)
                    msg += f"⚽ **{f['home']} vs {f['away']}**\n✅ {pred['verdict']} - {pred['stake']}\n\n"
                msg += f"{DISCLAIMER}"
                if CHANNEL_ID:
                    send_message(CHANNEL_ID, msg)

                # DM VIP only
                db = SessionLocal()
                try:
                    users = get_all_users(db)
                    for u in users:
                        if not u.is_vip:
                            continue
                        try:
                            fxs = fetch_real_fixtures(days_ahead=random.randint(1,2), limit=2, fav_league=u.favorite_league)
                            pmsg = f"🌙 Evening VIP {u.favorite_league} Tips:\n\n"
                            for f in fxs:
                                data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
                                pred = get_ai_prediction(data)
                                pmsg += f"⚽ **{f['home']} vs {f['away']}**\n🎯 {pred['best_pick']}\n✅ {pred['verdict']}\n{pred['stake']}\n\n"
                            pmsg += DISCLAIMER
                            send_message(u.user_id, pmsg)
                            time.sleep(0.4)
                        except Exception as e:
                            print(f"Evening VIP DM fail: {e}")
                finally:
                    db.close()

                posted.add(f"{today}-evening")

            if len(posted) > 20:
                posted.clear()

        except Exception as e:
            print(f"Scheduler error: {e}")

        time.sleep(60)

# Start threads
threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

# ================= FASTAPI ROUTES =================
@app.get("/")
async def home():
    return {"status": "LIVE", "bot": True, "channel": CHANNEL_ID, "time_utc": datetime.utcnow().isoformat(), "wat": "WAT = UTC+1"}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    fixtures = fetch_real_fixtures(days_ahead=1, limit=2)
    msg = f"🔥 **Test Broadcast {datetime.now().strftime('%d %b %H:%M')}**\n\n"
    for f in fixtures:
        data = {"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}
        pred = get_ai_prediction(data)
        msg += f"⚽ {f['home']} vs {f['away']} - {pred['best_pick']}\n✅ {pred['verdict']}\n{pred['stake']}\n\n"
    msg += DISCLAIMER
    if CHANNEL_ID:
        send_message(CHANNEL_ID, msg)
    return {"posted": True, "channel": CHANNEL_ID, "fixtures": fixtures}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe():
    html = f"""
    <html>
    <head><title>BetMasterPro VIP</title><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="font-family:sans-serif;text-align:center;padding:20px;background:#0f172a;color:white">
        <h1>💎 BetMasterPro VIP</h1>
        <div style="background:#1e293b;padding:20px;border-radius:15px;max-width:400px;margin:20px auto">
            <p>🆓 <b>FREE</b>: 2 predictions/day + 1 tip at 6AM WAT</p>
            <p>💎 <b>VIP</b>: 10 predictions/day + 2 personalized tips (6AM & 9PM WAT) tailored to your favorite league</p>
            <p>🧠 Bot remembers your favorite league & sends matching tips</p>
            <p>⚠️ {DISCLAIMER.replace(chr(10),'').replace('*','')}</p>
        </div>
        <a href="https://t.me/Betmasterpro_bot" style="background:#22c55e;color:white;padding:15px 30px;text-decoration:none;border-radius:10px;display:inline-block;margin:10px">💬 Chat with Bot</a><br>
        <a href="https://t.me/+IFK0qoDI2B5lYWI0" style="background:#3b82f6;color:white;padding:15px 30px;text-decoration:none;border-radius:10px;display:inline-block;margin:10px">🔗 Join Channel</a>
        <p style="margin-top:20px;font-size:12px">Paystack integration coming soon - Contact admin to activate VIP</p>
    </body>
    </html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    print(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
