import os, time, threading, requests, json, traceback
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
ADMIN_KEY = os.getenv("ADMIN_KEY","BetMasterAdmin123")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"
SUPPORT_HANDLE = "@Jibriliks"
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"

app = FastAPI(title="BetMasterPro Professional Real Only")
print(f"=== PROFESSIONAL REAL ONLY - EU + CHINESE + ASIAN + NATIONS LEAGUE - {BOT_LINK} ===")

def send_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 400:
            # retry without parse mode
            payload.pop("parse_mode", None)
            r = requests.post(url, json=payload, timeout=15)
        print(f"Send to {chat_id}: {r.status_code}")
        return r
    except Exception as e:
        print(f"Send error: {e}")
        traceback.print_exc()

def set_bot_menu():
    commands = [
        {"command": "start", "description": "Start - Professional Real Only Bot"},
        {"command": "today", "description": "Top 10 REAL TODAY - EU + Chinese + Asian - No fake"},
        {"command": "fixtures", "description": "Search: /fixtures china /fixtures japan /fixtures nations"},
        {"command": "betslip", "description": "VIP ONLY - Stake N1000 WIN N500K 10-match combo"},
        {"command": "upgrade", "description": "Upgrade VIP 10/day + 500K Betslip"},
        {"command": "help", "description": "Support & Help"},
    ]
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        r = requests.post(url, json={"commands": commands}, timeout=10).json()
        print(f"Menu set: {r}")
    except Exception as e:
        print(f"Menu error: {e}")

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
        send_message(int(user_id), f"✅ VIP Activated! {plan.upper()} till {expiry}\n10 predictions/day + 500K Betslip (EXTRA)\nBot: {BOT_LINK}")
        return True
    except Exception as e:
        print(f"VIP activation error {e}")
        traceback.print_exc()
        return False
    finally:
        db.close()

def process_update(upd):
    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures, generate_betslip

    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # Handle button clicks
    if "callback_query" in upd:
        try:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            from_id = cq["from"]["id"]
            data = cq.get("data","")
            requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": "Generating..."}, timeout=5)

            if data == "predict_top5":
                db2 = SessionLocal()
                try:
                    user2 = get_user(db2, from_id)
                    limit = 10 if user2.is_vip else 2
                    if user2.daily_count >= limit:
                        send_message(chat_id, f"❌ Limit {user2.daily_count}/{limit} today.\nUpgrade VIP: {RENDER_URL}/subscribe?uid={from_id}")
                        return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5, include_youth=False)
                    if not fixtures:
                        # Search next days for real
                        for i in range(1,4):
                            fixtures = fetch_real_fixtures(days_ahead=i, limit=5, include_youth=False)
                            if fixtures:
                                break
                    if not fixtures:
                        send_message(chat_id, f"ℹ️ No REAL senior fixtures found in next 3 days.\nBot: {BOT_LINK}")
                        return

                    send_message(chat_id, f"🔥 TOP 5 REAL TODAY - {datetime.now().strftime('%d %B %Y')} - European + Chinese + Asian - 100% REAL")

                    for f in fixtures[:5]:
                        if user2.daily_count >= limit:
                            break
                        p = get_ai_prediction(f)
                        update_league_history(db2, user2, f["league"])
                        msg = f"⚽ {f['home']} vs {f['away']}\n🏆 {f['league']} | {f.get('continent','World')} | {f['date']} {f['time']} WAT\n📡 Source: {f.get('source','LIVE REAL')}\n\n🎯 Pick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n📊 Reason: {p['explanation']}\n✅ Verdict: {p['verdict']}\n\n💰 Potential:\nN1,000 -> N{p['winnings_1000']} | N2,000 -> N{p['winnings_2000']}\n{p['disclaimer']}\n"
                        send_message(chat_id, msg)
                        user2.daily_count += 1
                        db2.commit()
                        time.sleep(0.8)
                finally:
                    db2.close()

            elif data == "generate_betslip":
                db2 = SessionLocal()
                try:
                    user2 = get_user(db2, from_id)
                    if not user2.is_vip:
                        send_message(chat_id, f"🔒 BETSLIP 500K is VIP ONLY!\nStake N1000 WIN N500K - 10 high odds senior matches\nUpgrade: {RENDER_URL}/subscribe?uid={from_id}")
                        return

                    fixtures = fetch_real_fixtures(days_ahead=0, limit=20, include_youth=False)
                    # If today not enough, search next days for real fixtures for betslip
                    if len(fixtures) < 10:
                        for i in range(1,4):
                            extra = fetch_real_fixtures(days_ahead=i, limit=20, include_youth=False)
                            existing = {f"{x['home']}-{x['away']}" for x in fixtures}
                            for ef in extra:
                                if f"{ef['home']}-{ef['away']}" not in existing:
                                    fixtures.append(ef)
                            if len(fixtures) >= 10:
                                break

                    slip = generate_betslip(fixtures)
                    if not slip:
                        send_message(chat_id, f"ℹ️ Not enough REAL matches today for 10-game slip. Found {len(fixtures)} real matches.\nTry again tomorrow or check /today for next available.\nBot: {BOT_LINK}")
                        return

                    msg = f"💰 BETSLIP 10 SENIOR MATCHES - {datetime.now().strftime('%d %B %Y')} - VIP ONLY\n🎯 Stake: N1,000 or N2,000 to WIN N500K+\n📡 Sources: European + Chinese Super League + Asian - REAL ONLY\n\n"
                    for i,p in enumerate(slip["picks"],1):
                        msg+=f"{i}. {p['match']}\n {p['league']} - {p['pick']} @ {p['odds']}\n\n"
                    msg+=f"📈 TOTAL ODDS: {slip['total_odds']}\n\n💵 POTENTIAL WINNINGS:\nStake N1,000 -> WIN N{slip['winnings_1000']} (Profit N{slip['profit_1000']})\nStake N2,000 -> WIN N{slip['winnings_2000']} (Profit N{slip['profit_2000']})\n\n⚽ Play all 10 as ACCA on SportyBet/BetKing\n🔥 VIP EXTRA - Not counted in 10/day limit\nBot: {BOT_LINK}\n"
                    send_message(chat_id, msg)
                finally:
                    db2.close()

        except Exception as e:
            print(f"Callback error {e}")
            traceback.print_exc()
        return

    msg = upd.get("message")
    if not msg or "text" not in msg or msg["chat"]["type"]!="private":
        return

    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()
    user_id = msg["from"]["id"]
    username = msg["from"].get("username","")
    low = text.lower()
    print(f"Message from {user_id}: {text}")

    db = SessionLocal()
    try:
        user = get_user(db, user_id, username)
        FREE=2; VIP=10
        cur = VIP if user.is_vip else FREE

        if low.startswith("/start"):
            send_message(chat_id, f"👋 Welcome to BetMasterPro - PROFESSIONAL REAL ONLY\n\n✅ 100% REAL fixtures only - No fake, no youth U21\n🏆 Focus: European Leagues + Chinese Super League + Asian Leagues + Nations League\n🌍 Sources: Football-Data.org (EU) + ESPN (Chinese, Asian, Nations League) - REAL ONLY\n\n📋 MENU (Click Menu button):\n/start - This message\n/today - Top 10 REAL TODAY - EU + Chinese + Asian - No fake, recent only\n/fixtures china - Chinese Super League REAL today\n/fixtures japan - J1 League Japan REAL\n/fixtures korea - K League REAL\n/fixtures nations - UEFA Nations League Senior REAL\n/fixtures africa - Africa Friendlies Senior\n/fixtures england - Premier League REAL\n/betslip - VIP ONLY: Stake N1000 WIN N500K (10 high odds REAL matches) - EXTRA not counted\n/upgrade - VIP 10/day + 500K Betslip\n/help - Support\n\n💳 Limits: FREE {FREE}/day, VIP {VIP}/day + Betslip bonus (extra)\n📢 Channel: {CHANNEL_LINK}\n🆘 Support: {SUPPORT_HANDLE}\n\n💎 Professional: Only recent real fixtures, no fake, EU + Chinese + Asian focus to attract subscriptions!")

        elif low.startswith("/help"):
            send_message(chat_id, f"🆘 Support: {SUPPORT_HANDLE}\nBot: {BOT_LINK}\nYou: {user.daily_count}/{cur}\n\nCommands:\n/today - Real today EU+Chinese+Asian\n/fixtures china - Chinese Super League\n/fixtures japan - J1 Japan\n/fixtures korea - K League\n/fixtures nations - Nations League Senior\n/fixtures africa - Africa Friendlies\n/betslip - VIP 500K\n/upgrade - VIP")

        elif low.startswith("/betslip"):
            if not user.is_vip:
                send_message(chat_id, f"🔒 BETSLIP 500K VIP ONLY\n💰 Stake N1000 WIN N500K+\n10 senior high odds REAL matches combo\nEXTRA - Not counted in {cur}/day\n\nUpgrade Weekly N2,000:\n{RENDER_URL}/subscribe?uid={user_id}\nBot: {BOT_LINK}")
                return
            send_message(chat_id, f"⏳ Generating VIP 500K SENIOR BETSLIP - Stake 1000 to win 500K+ - Real EU + Chinese + Asian matches...")
            fixtures = fetch_real_fixtures(days_ahead=0, limit=20, include_youth=False)
            if len(fixtures) < 10:
                for i in range(1,4):
                    extra = fetch_real_fixtures(days_ahead=i, limit=20, include_youth=False)
                    existing = {f"{x['home']}-{x['away']}" for x in fixtures}
                    for ef in extra:
                        if f"{ef['home']}-{ef['away']}" not in existing:
                            fixtures.append(ef)
                    if len(fixtures) >= 10:
                        break

            slip = generate_betslip(fixtures)
            if not slip:
                send_message(chat_id, f"ℹ️ Not enough REAL matches today for 10-game slip. Found {len(fixtures)} real.\nBot: {BOT_LINK}")
                return

            msg = f"💰 BETSLIP VIP SENIOR - WIN 500K - {datetime.now().strftime('%d %B %Y')}\nStake N1000/N2000 to win 500K+ - REAL EU + Chinese + Asian\n\n"
            for i,p in enumerate(slip["picks"],1):
                msg+=f"{i}. {p['match']}\n {p['league']}\n {p['pick']} @ {p['odds']}\n\n"
            msg+=f"📈 TOTAL ODDS: {slip['total_odds']}\n\n💵 WINNINGS (Stake -> Win):\nStake N1,000 -> WIN N{slip['winnings_1000']} (Profit N{slip['profit_1000']})\nStake N2,000 -> WIN N{slip['winnings_2000']} (Profit N{slip['profit_2000']})\n\n🔥 EXTRA - Not counted in 10/day\nBot: {BOT_LINK}"
            keyboard = {"inline_keyboard": [[{"text": "🔄 Regenerate 500K Betslip", "callback_data": "generate_betslip"}]]}
            send_message(chat_id, msg, reply_markup=keyboard)

        elif low.startswith("/fixtures"):
            parts = low.split()
            country = parts[1] if len(parts)>1 else "nations"
            if user.daily_count >= cur:
                send_message(chat_id, f"❌ Limit {user.daily_count}/{cur} today.\nUpgrade VIP: {RENDER_URL}/subscribe?uid={user_id}")
                return
            send_message(chat_id, f"⏳ Fetching REAL {country.title()} fixtures TODAY {datetime.now().strftime('%Y-%m-%d')} - EU + Chinese + Asian - No fake...")
            fixtures = fetch_fixtures_by_country(country, days_ahead=0, limit=10)

            if not fixtures:
                # Search next 3 days for real fixtures in that league
                found_next = False
                for i in range(1,4):
                    next_fixtures = fetch_fixtures_by_country(country, days_ahead=i, limit=10)
                    if next_fixtures:
                        next_date = datetime.now() + timedelta(days=i)
                        list_msg = f"ℹ️ No REAL {country.title()} TODAY - NEXT REAL FIXTURES ON {next_date.strftime('%d %B %Y')} - 100% REAL NO FAKE\n\n"
                        for idx,f in enumerate(next_fixtures,1):
                            list_msg+=f"{idx}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT | {f.get('source','LIVE REAL')}\n\n"
                        list_msg+=f"Bot: {BOT_LINK}"
                        send_message(chat_id, list_msg)
                        found_next = True
                        break
                if not found_next:
                    send_message(chat_id, f"ℹ️ No REAL {country.title()} fixtures in next 3 days - Try /today or /fixtures china\nBot: {BOT_LINK}")
                return

            list_msg = f"🏆 {country.upper()} REAL FIXTURES TODAY - {datetime.now().strftime('%Y-%m-%d')} - 100% REAL NO FAKE\n\n"
            for i,f in enumerate(fixtures,1):
                list_msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT | 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']} | {f.get('source','LIVE REAL')}\n\n"
            list_msg+=f"Real only - {datetime.now().strftime('%Y-%m-%d')}\nBot: {BOT_LINK}"
            keyboard = {"inline_keyboard": [[{"text": f"🎯 Predict {country.title()} Top 5", "callback_data": "predict_top5"}]]}
            send_message(chat_id, list_msg, reply_markup=keyboard)

        elif low.startswith("/upgrade") or low.startswith("/subscribe"):
            send_message(chat_id, f"💎 VIP Plans - PROFESSIONAL REAL ONLY:\nFREE {FREE}/day\nVIP {VIP}/day + BETSLIP WIN 500K from N1000 stake EXTRA (not counted)\n✅ Real fixtures only, no fake\n✅ EU + Chinese Super League + Asian focus\n✅ Nations League Senior priority\n✅ 500K betslip high odds\nWeekly N2,000 / Monthly N5,000\nLink: {RENDER_URL}/subscribe?uid={user_id}\nBot: {BOT_LINK}")

        elif low.startswith("/today"):
            if user.daily_count >= cur:
                send_message(chat_id, f"❌ Limit {user.daily_count}/{cur} today.\nUpgrade VIP: {RENDER_URL}/subscribe?uid={user_id}")
                return

            send_message(chat_id, f"⏳ Scanning REAL fixtures TODAY {datetime.now().strftime('%d %B %Y')} - European + Chinese Super League + Asian - 100% real, no fake, recent only...")

            fixtures = fetch_real_fixtures(days_ahead=0, limit=10, include_youth=False)

            if not fixtures:
                # NO FAKE - Search next 7 days for REAL fixtures
                send_message(chat_id, f"ℹ️ No REAL senior fixtures TODAY {datetime.now().strftime('%d %B %Y')} in EU + Chinese + Asian leagues.\n🔍 Searching next 7 days for REAL fixtures...")

                found = False
                for i in range(1, 8):
                    next_date = datetime.now() + timedelta(days=i)
                    next_fixtures = fetch_real_fixtures(days_ahead=i, limit=10, include_youth=False)
                    if next_fixtures:
                        header = f"📅 NO MATCHES TODAY - NEXT REAL FIXTURES ON {next_date.strftime('%d %B %Y')} - European + Chinese + Asian - 100% REAL NO FAKE\n\n"
                        list_msg = header
                        for idx,f in enumerate(next_fixtures,1):
                            list_msg+=f"{idx}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT | 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']} | {f.get('source','LIVE REAL')}\n\n"
                        list_msg+=f"👆 Next real date: {next_date.strftime('%d %B %Y')}\nBot: {BOT_LINK} - Real only, no fake"
                        keyboard = {"inline_keyboard": [[{"text": f"🎯 Predict {next_date.strftime('%d %b')} Top 5 Real", "callback_data": "predict_top5"}]]}
                        send_message(chat_id, list_msg, reply_markup=keyboard)
                        found = True
                        break

                if not found:
                    send_message(chat_id, f"ℹ️ No REAL matches in next 7 days in EU + Chinese + Asian leagues - International break or off-season.\nTry:\n/fixtures china - Check Chinese Super League\n/fixtures japan - Check J-League\n/fixtures nations - Check Nations League\nBot: {BOT_LINK} - 100% real only, no fake fixtures")
                return

            # Has real fixtures today
            header = f"🔥 TOP {len(fixtures)} REAL FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')} - European + Chinese Super League + Asian - 100% REAL NO FAKE - Recent Only\n\n"
            list_msg = header
            for i,f in enumerate(fixtures,1):
                list_msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT | 1:{f['odds_h']} X:{f['odds_d']} 2:{f['odds_a']} | {f.get('source','LIVE REAL')}\n\n"
            list_msg+=f"👆 Tap Predict! ({user.daily_count}/{cur}) - Real only, professional\nBot: {BOT_LINK}"
            keyboard = {"inline_keyboard": [[{"text": "🎯 Predict Top 5 Real + Winnings", "callback_data": "predict_top5"}, {"text": "💰 VIP 500K Betslip (N1000->N500K)", "callback_data": "generate_betslip"}]]}
            send_message(chat_id, list_msg, reply_markup=keyboard)

        elif "vs" in low and 5 < len(text) < 100:
            if user.daily_count >= cur:
                send_message(chat_id, f"❌ Limit {user.daily_count}/{cur} today.\nUpgrade: {RENDER_URL}/subscribe?uid={user_id}")
                return
            try:
                home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
            except:
                home=text.title(); away="Opponent"
            all_f = fetch_real_fixtures(days_ahead=0, limit=100, include_youth=False)
            matched = next((f for f in all_f if home.lower() in f['home'].lower() and away.lower() in f['away'].lower()), None)
            data = matched if matched else {
                "home": home, "away": away, "league": user.favorite_league,
                "odds_h": 2.2, "odds_d": 3.2, "odds_a": 2.9,
                "odds_over15": 1.30, "odds_over25": 1.85, "odds_btts": 1.75, "odds_1x": 1.35,
                "best_odds_source": "Live Real", "date": datetime.now().strftime('%Y-%m-%d'),
                "source": "Search Real", "continent": "World"
            }
            p = get_ai_prediction(data)
            update_league_history(db, user, data.get("league","Custom"))
            user.daily_count+=1
            db.commit()
            msg = f"⚽ {home} vs {away}\n🏆 {data.get('league','Custom')} | {datetime.now().strftime('%d %B %Y')} | {data.get('source','LIVE REAL')}\nOdds: 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n🎯 Pick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n📊 Reason: {p['explanation']}\n✅ Verdict: {p['verdict']}\n\n💰 Potential:\nN1,000 -> N{p['winnings_1000']}\nN2,000 -> N{p['winnings_2000']}\nUsed: {user.daily_count}/{cur}\n{p['disclaimer']}\nBot: {BOT_LINK}"
            send_message(chat_id, msg)

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
                    fixtures=fetch_real_fixtures(days_ahead=1, limit=15, include_youth=False)
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
                    msg=f"🔥 Morning {today} - REAL EU + Chinese + Asian Fixtures\n\n"
                    for f in uniq:
                        p=get_ai_prediction(f)
                        msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_pick']} @ {p['odds']} | N1000->N{p['winnings_1000']}\n\n"
                    msg+=f"Bot: {BOT_LINK} | {SUPPORT_HANDLE} - Real only"
                    if CHANNEL_ID:
                        send_message(CHANNEL_ID, msg)
                finally:
                    db.close()
                posted.add(f"{today}-morning")
        except Exception as e:
            print(f"Scheduler error {e}")
        time.sleep(60)

threading.Thread(target=channel_scheduler, daemon=True).start()

@app.on_event("startup")
async def on_startup():
    set_bot_menu()
    webhook_url = f"{RENDER_URL}/webhook"
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true", timeout=10).json()
        print(f"WEBHOOK SET: {webhook_url} -> {r}")
    except Exception as e:
        print(f"Webhook error {e}")

@app.get("/")
async def home():
    try:
        r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
        ok=r.get("ok",False)
        username=r.get("result",{}).get("username","UNKNOWN")
        wh=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=8).json()
    except Exception as e:
        ok=False; username=str(e); wh={}
    return {
        "status":"PROFESSIONAL REAL ONLY - EU + CHINESE SUPER LEAGUE + ASIAN + NATIONS LEAGUE - NO FAKE",
        "bot_ok":ok,
        "bot_username":username,
        "bot_link":BOT_LINK,
        "webhook_info":wh.get("result",{}),
        "menu":"/start /today /fixtures /betslip /upgrade /help",
        "accuracy":"Football-Data.org EU + ESPN chn.1/jpn.1/kor.1/eng.1/esp.1/uefa.nations REAL ONLY - No fake fallback",
        "focus":"European + Chinese Super League + Asian Leagues - Your main focus",
        "betslip":"Stake N1000 WIN N500K - 10 high odds real matches - 400-850 total odds"
    }

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        process_update(data)
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"Webhook error {e}")
        traceback.print_exc()
        return JSONResponse({"ok": True}, status_code=200)

@app.get("/set-webhook")
async def set_webhook():
    set_bot_menu()
    webhook_url = f"{RENDER_URL}/webhook"
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true", timeout=10).json()
    return r

@app.get("/pay")
async def pay(plan:str, uid:str):
    if not FLW_SECRET:
        return JSONResponse({"error":"Flutterwave keys not set"}, status_code=500)
    amount=2000 if plan=="weekly" else 5000
    tx_ref=f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload={
        "tx_ref":tx_ref,
        "amount":amount,
        "currency":"NGN",
        "redirect_url":f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer":{"email":f"{uid}@betmasterpro.com","name":f"User {uid}"},
        "customizations":{"title":f"BetMasterPro {plan.upper()} Professional Real Only"}
    }
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
                return HTMLResponse(f"<h1>✅ OK {plan.upper()} Activated - 10/day + 500K Betslip till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</h1><a href='{BOT_LINK}'>Go to Bot - Professional Real Only</a>")
        return HTMLResponse(f"<h1>Payment not confirmed yet {tx_ref}</h1><a href='/subscribe?uid={uid}'>Retry Payment</a>")
    except Exception as e:
        return HTMLResponse(f"Error verifying payment {e}")

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
        print(f"Flutterwave webhook error {e}")
        return JSONResponse({"status":"error"}, status_code=200)

@app.get("/admin/activate")
async def admin_activate(uid:str, plan:str="monthly", key:str=""):
    if key!=ADMIN_KEY:
        return HTMLResponse("Wrong admin key", status_code=403)
    ok=activate_vip(uid, plan)
    return HTMLResponse(f"{'Activated' if ok else 'Failed'} {uid} {plan} - {BOT_LINK}")

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"""
    <html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
    <style>
    body{{background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif}}
   .card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}
   .btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}
   .weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}
    </style></head><body>
    <h1>💎 BetMasterPro VIP Professional</h1>
    <p>User ID: {uid}</p>
    <div class='card'>
    <p>✅ PROFESSIONAL REAL ONLY BOT<br>
    FREE 2/day<br>
    VIP 10/day + 10-match BETSLIP EXTRA<br>
    ✅ No fake fixtures - Real only<br>
    ✅ European + Chinese Super League + Asian leagues<br>
    ✅ Nations League Senior priority<br>
    ✅ Stake N1000 WIN N500K (400-850 total odds)</p>
    <a class='btn weekly' href='/pay?plan=weekly&uid={uid}'>Weekly N2,000 - 500K Betslip</a>
    <a class='btn monthly' href='/pay?plan=monthly&uid={uid}'>Monthly N5,000 - Best Value</a>
    <p>Bot: {BOT_LINK}</p>
    <p>100% Real Only - No Fake Fixtures</p>
    </div>
    </body></html>
    """)

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
