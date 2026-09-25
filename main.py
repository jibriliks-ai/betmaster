import os, time, threading, requests, random, json
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

# YOUR OFFICIAL LINKS - 100% CORRECT
SUPPORT_HANDLE = "@Jibriliks"
BOT_LINK = "https://t.me/Betmasterpro_bot"
BOT_HANDLE = "@Betmasterpro_bot"
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"

app = FastAPI(title="BetMasterPro Super Brain")
print(f"=== BETMASTERPRO PERFECT CODE LIVE ===")
print(f"Bot: {BOT_LINK} | Channel: {CHANNEL_ID} | Support: {SUPPORT_HANDLE}")

DISCLAIMER = "\n\n⚠️ *Disclaimer:* Betting risk. AI analysis only, 18+ stake responsibly."

def send_message(chat_id, text, parse="Markdown", reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000: text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse}
        if reply_markup: payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Send error: {e}")

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
        send_message(int(user_id), f"🎉 **VIP Activated via {plan.title()}!**\n\n✅ Plan: {plan.upper()} (₦{'2,000' if 'weekly' in plan else '5,000'})\n📅 Valid till: {expiry}\n💎 You now have 10 predictions/day + 2 personalized tips (6AM & 9PM WAT)!\n\nChat now: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")
        return True
    except Exception as e:
        print(f"VIP error: {e}")
        return False
    finally:
        db.close()

def bot_polling_loop():
    if not BOT_TOKEN:
        print("CRITICAL: BOT_TOKEN missing in Render Environment!")
        return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("Webhook deleted - Polling started - PERFECT CODE")
    except Exception as e:
        print(f"Webhook delete error: {e}")

    from database import SessionLocal, get_user, update_league_history
    from predictor import get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures

    offset = 0
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    while True:
        try:
            resp = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 20}, timeout=25).json()
            if not resp.get("ok"):
                print(f"getUpdates failed: {resp}")
                time.sleep(5)
                continue

            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1

                # ===== PREDICT BUTTON HANDLER =====
                if "callback_query" in upd:
                    try:
                        cq = upd["callback_query"]
                        chat_id = cq["message"]["chat"]["id"]
                        from_id = cq["from"]["id"]
                        data = cq.get("data", "")
                        requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": "Generating predictions..."}, timeout=5)

                        if data == "predict_top5":
                            db2 = SessionLocal()
                            try:
                                user2 = get_user(db2, from_id)
                                limit = 10 if user2.is_vip else 2
                                if user2.daily_count >= limit:
                                    send_message(chat_id, f"🚫 You have used {user2.daily_count}/{limit} today.\n\n🆓 FREE: 2/day\n💎 VIP: 10/day\n\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={from_id}\nSupport: {SUPPORT_HANDLE}")
                                    continue

                                fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                                if not fixtures:
                                    fixtures = fetch_real_fixtures(days_ahead=1, limit=5)

                                send_message(chat_id, f"🔮 **TOP 5 PREDICTIONS TODAY - {datetime.now().strftime('%d %B %Y')}**\nNear-accurate AI analysis:\n")

                                count = 0
                                for f in fixtures[:5]:
                                    if user2.daily_count >= limit:
                                        break
                                    d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                                    p = get_ai_prediction(d)
                                    update_league_history(db2, user2, f["league"])
                                    msg = f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | 📅 {f['date']} {f['time']} WAT\n🎯 **Pick: {p['best_pick']}** ({p['confidence']}%)\n📝 {p['explanation']}\n\n✅ **{p['verdict']}**\n{p['stake']}{p['disclaimer']}\n"
                                    send_message(chat_id, msg)
                                    user2.daily_count += 1
                                    count += 1
                                    db2.commit()
                                    time.sleep(0.7)

                                if count > 0:
                                    send_message(chat_id, f"✅ {count} predictions used. Remaining: {limit - user2.daily_count}/{limit} today.\n\n💬 More: {BOT_LINK}\n🆘 Support: {SUPPORT_HANDLE}")
                                else:
                                    send_message(chat_id, f"🚫 Limit reached {limit}/{limit} today. Resets midnight WAT.\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={chat_id}\nSupport: {SUPPORT_HANDLE}")

                            finally:
                                db2.close()
                    except Exception as e:
                        print(f"Callback error: {e}")
                    continue

                msg = upd.get("message")
                if not msg or "text" not in msg or msg["chat"]["type"]!= "private":
                    continue

                chat_id = msg["chat"]["id"]
                text = msg["text"].strip()
                user_id = msg["from"]["id"]
                username = msg["from"].get("username", "")
                low = text.lower()

                db = SessionLocal()
                try:
                    user = get_user(db, user_id, username)
                    FREE_LIMIT = 2
                    VIP_LIMIT = 10
                    current_limit = VIP_LIMIT if user.is_vip else FREE_LIMIT

                    if low.startswith("/start"):
                        send_message(chat_id, f"🎯 **Welcome to BetMasterPro - Super Smart AI** 🎯\n\n100% LIVE fixtures + predictions!\n\n**Commands:**\n⚽ `Arsenal vs Chelsea` - Any match prediction\n📅 `/today` - Top 10 LIVE fixtures today + Predict button\n🌍 `/fixturesengland` - England PL today\n🌍 `/fixtureschina` - China Super League\n🌍 `/fixturesworld` - National teams LIVE\n💎 `/myplan` - Check plan ({user.daily_count}/{current_limit} used today)\n💳 `/subscribe` - Upgrade to VIP\n🆘 `/help` - Support\n\n**Limits:**\n🆓 FREE: {FREE_LIMIT} predictions/day + 1 unique tip 6AM WAT\n💎 VIP: {VIP_LIMIT} predictions/day + 2 personalized tips\n\nChannel: {CHANNEL_LINK}\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/help"):
                        send_message(chat_id, f"🆘 **BetMasterPro Support**\n\nNeed help?\n👤 {SUPPORT_HANDLE} - https://t.me/Jibriliks\n🤖 Bot: {BOT_LINK}\n📢 Channel: {CHANNEL_LINK}\n\n**Commands:**\n/today - 10 LIVE fixtures today\n/fixturesengland - England fixtures\n/fixtures + country name\n/myplan - Check usage ({user.daily_count}/{current_limit})\n/subscribe - Upgrade\n\nWe reply within 2 hours!")

                    elif low.startswith("/fixtures"):
                        country_raw = low.replace("/fixtures", "").strip().split()[0] if low.replace("/fixtures", "").strip() else "england"
                        if country_raw in ["today", "tomorrow"]: country_raw = "england"

                        if user.daily_count >= current_limit:
                            send_message(chat_id, f"🚫 **Limit reached** {user.daily_count}/{current_limit} today.\n\n🆓 FREE: {FREE_LIMIT}/day\n💎 VIP: {VIP_LIMIT}/day - Upgrade for more!\n\n👉 https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nSupport: {SUPPORT_HANDLE}")
                            continue

                        send_message(chat_id, f"🌍 Fetching **{country_raw.title()}** LIVE fixtures for TODAY {datetime.now().strftime('%d %B %Y')} - 100% verified...")
                        fixtures = fetch_fixtures_by_country(country_raw, days_ahead=0, limit=3)

                        if not fixtures:
                            send_message(chat_id, f"📅 No {country_raw.title()} fixtures today ({datetime.now().strftime('%d %B %Y')}).\n\nThis is LIVE data - no fake qualifiers.\nTry /fixturesworld for national teams or /today for all games.\n\nSupport: {SUPPORT_HANDLE}\nBot: {BOT_LINK}")
                            continue

                        list_msg = f"📅 **{country_raw.title().upper()} FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')}** - LIVE\n\n"
                        for i, f in enumerate(fixtures, 1):
                            list_msg += f"{i}. **{f['home']} vs {f['away']}**\n 🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n\n"
                        list_msg += f"💡 Tap to predict!\nBot: {BOT_LINK}"

                        keyboard = {"inline_keyboard": [[{"text": f"🔮 Predict {country_raw.title()}", "callback_data": "predict_top5"}]]}
                        send_message(chat_id, list_msg, reply_markup=keyboard)
                        # /fixtures list does not count as prediction, only predictions count

                    elif low.startswith("/myplan"):
                        plan_txt = f"💎 VIP till {user.vip_expiry}" if user.is_vip else f"🆓 FREE ({FREE_LIMIT}/day)"
                        send_message(chat_id, f"**Your Plan:** {plan_txt}\n📊 Used today: {user.daily_count}/{current_limit}\n⭐ Favorite League: {user.favorite_league}\n💬 Total chats: {user.total_chats}\n\n{'✅ VIP: 10/day' if user.is_vip else f'🚫 FREE limit {FREE_LIMIT}/day - Upgrade for {VIP_LIMIT}/day'}\n\nUpgrade: https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/subscribe"):
                        send_message(chat_id, f"💳 **BetMasterPro VIP Plans - Card + Bank Transfer auto-activate**\n\n🆓 FREE: {FREE_LIMIT} predictions/day\n💎 WEEKLY: ₦2,000 - {VIP_LIMIT} predictions/day (7 days)\n💎 MONTHLY: ₦5,000 - {VIP_LIMIT} predictions/day (30 days)\n\n👉 https://betmaster-p09f.onrender.com/subscribe?uid={user_id}\n\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")

                    elif low.startswith("/today"):
                        if user.daily_count >= current_limit:
                            send_message(chat_id, f"🚫 **Daily limit reached** {user.daily_count}/{current_limit}\n\nResets midnight WAT.\n\n💎 Upgrade to VIP for {VIP_LIMIT}/day:\nhttps://betmaster-p09f.onrender.com/subscribe?uid={user_id}\n\nSupport: {SUPPORT_HANDLE}\nBot: {BOT_LINK}")
                            continue

                        send_message(chat_id, f"📅 Fetching TOP 10 LIVE fixtures TODAY {datetime.now().strftime('%d %B %Y')} - 100% verified from ESPN...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=10)

                        if not fixtures:
                            send_message(chat_id, f"📅 No top fixtures today {datetime.now().strftime('%d %B %Y')} - checking tomorrow...")
                            fixtures = fetch_real_fixtures(days_ahead=1, limit=10)
                            header = f"📅 **No games today - TOP 10 UPCOMING TOMORROW - {(datetime.now()+timedelta(days=1)).strftime('%d %B %Y')}**\n\n"
                        else:
                            header = f"📅 **TOP {len(fixtures)} LIVE FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')}** - 100% Verified LIVE\n\n"

                        list_msg = header
                        for i, f in enumerate(fixtures, 1):
                            list_msg += f"{i}. **{f['home']} vs {f['away']}**\n 🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n\n"
                        list_msg += f"💡 Tap below to get predictions! ({user.daily_count}/{current_limit} used today)\nBot: {BOT_LINK}"

                        keyboard = {"inline_keyboard": [[{"text": "🔮 Predict Top 5 Matches", "callback_data": "predict_top5"}]]}
                        send_message(chat_id, list_msg, reply_markup=keyboard)

                    elif "vs" in low and 5 < len(text) < 100:
                        # STRICT LIMIT ENFORCEMENT
                        if user.daily_count >= current_limit:
                            send_message(chat_id, f"🚫 **Daily limit reached: {user.daily_count}/{current_limit}**\n\nI track by Telegram ID even if you clear chat.\nResets midnight WAT.\n\n🆓 FREE: {FREE_LIMIT}/day\n💎 VIP: {VIP_LIMIT}/day\n\n💳 Upgrade now:\nhttps://betmaster-p09f.onrender.com/subscribe?uid={user_id}\n\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")
                            continue

                        try:
                            home, away = [x.strip().title() for x in text.lower().split("vs")][:2]
                        except:
                            home = text.title()
                            away = "Opponent"

                        league_guess = user.favorite_league if user.is_vip else "Custom Match"
                        if any(c in home.lower() for c in ["nigeria", "ghana", "england", "brazil", "france", "germany"]) and any(c in away.lower() for c in ["nigeria", "ghana", "england", "brazil", "france", "germany", "spain", "argentina"]):
                            league_guess = "National Teams - International Friendly"

                        from predictor import get_ai_prediction
                        data = {"home": home, "away": away, "league": league_guess, "home_xg": 1.6, "away_xg": 1.1, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": round(random.uniform(1.9, 3.2), 2), "odds_d": round(random.uniform(3.0, 4.0), 2), "odds_a": round(random.uniform(2.2, 3.8), 2), "odds_over": 1.75}
                        pred = get_ai_prediction(data)
                        update_league_history(db, user, league_guess)
                        user.daily_count += 1
                        db.commit()

                        send_message(chat_id, f"⚽ **{home} vs {away}**\n🏆 {league_guess} | 📅 {datetime.now().strftime('%d %B %Y')}\n💰 1:{data['odds_h']} X:{data['odds_d']} 2:{data['odds_a']}\n\n🎯 **Pick: {pred['best_pick']}** ({pred['confidence']}%)\n📝 {pred['explanation']}\n\n✅ **EXPERT VERDICT: {pred['verdict']}**\n{pred['stake']}\n📊 Market: {pred['market']}\n\n📈 Used today: {user.daily_count}/{current_limit} {'(FREE)' if not user.is_vip else '(VIP)'}\n{pred['disclaimer']}\n\n💬 More predictions: {BOT_LINK}\n🆘 Support: {SUPPORT_HANDLE}")

                    else:
                        send_message(chat_id, f"Send match like `Arsenal vs Chelsea` or use:\n/today - 10 LIVE fixtures\n/fixturesengland\n/myplan - {user.daily_count}/{current_limit} used\n\nBot: {BOT_LINK}\nSupport: {SUPPORT_HANDLE}")

                except Exception as e:
                    print(f"Handler error: {e}")
                    import traceback; traceback.print_exc()
                    db.rollback()
                finally:
                    db.close()

        except Exception as e:
            print(f"Polling loop error: {e}")
            time.sleep(5)

def channel_scheduler():
    from database import SessionLocal, get_all_users, is_already_posted, mark_as_posted
    from predictor import fetch_real_fixtures, get_ai_prediction
    posted = set()
    while True:
        try:
            now_utc = datetime.utcnow()
            hm = now_utc.strftime("%H:%M")
            today = now_utc.strftime("%Y-%m-%d")
            if hm == "05:05" and f"{today}-morning" not in posted:
                db = SessionLocal()
                try:
                    fixtures = fetch_real_fixtures(days_ahead=1, limit=15)
                    unique = []
                    for f in fixtures:
                        h = f"{f['home']}-{f['away']}-{f['date']}"
                        if not is_already_posted(db, h):
                            unique.append(f)
                            mark_as_posted(db, h)
                            if len(unique) >= 2: break
                    if not unique: unique = fixtures[:2]
                    msg = f"🔥 **BetMasterPro Morning - {today}** - Unique LIVE Tips\n\n"
                    for f in unique:
                        d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                        p = get_ai_prediction(d)
                        msg += f"⚽ **{f['home']} vs {f['away']}**\n🏆 {f['league']} | 📅 {f['date']} {f['time']} WAT\n🎯 {p['best_pick']} | ✅ {p['verdict']}\n{p['stake']}\n\n"
                    msg += f"💬 More predictions: {BOT_LINK}\n🆘 Support: {SUPPORT_HANDLE}\n🔗 {CHANNEL_LINK}\n{DISCLAIMER}"
                    if CHANNEL_ID: send_message(CHANNEL_ID, msg)
                    # DM users unique
                    for u in get_all_users(db):
                        try:
                            fav = u.favorite_league if u.is_vip else None
                            fxs = fetch_real_fixtures(days_ahead=random.randint(1,3), limit=2 if u.is_vip else 1, fav_league=fav)
                            pmsg = f"☀️ Morning {'VIP '+u.favorite_league if u.is_vip else 'Free'} Tip - Unique - {today}:\n\n"
                            for f in fxs:
                                d = {"home": f["home"], "away": f["away"], "league": f["league"], "home_xg": 1.5, "away_xg": 1.2, "home_form": "WDWWL", "away_form": "LWDWL", "h2h": 2, "home_inj": "None", "away_inj": "None", "odds_h": f["odds_h"], "odds_d": f["odds_d"], "odds_a": f["odds_a"], "odds_over": 1.75}
                                p = get_ai_prediction(d)
                                pmsg += f"⚽ {f['home']} vs {f['away']} - {p['best_pick']}\n✅ {p['verdict']}\n\n"
                            pmsg += f"Bot: {BOT_LINK} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
                            if not u.is_vip: pmsg += f"\n💎 Upgrade to {10}/day: https://betmaster-p09f.onrender.com/subscribe?uid={u.user_id}"
                            send_message(u.user_id, pmsg); time.sleep(0.4)
                        except: pass
                finally: db.close()
                posted.add(f"{today}-morning")
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(60)

threading.Thread(target=bot_polling_loop, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()

@app.get("/")
async def home():
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
        ok = r.get("ok", False); username = r.get("result", {}).get("username", "UNKNOWN")
    except Exception as e: ok = False; username = f"Error {e}"
    return {"status": "PERFECT CODE LIVE - PROFESSIONAL", "bot_ok": ok, "bot_username": username, "bot_link": BOT_LINK, "bot_token_set": bool(BOT_TOKEN), "channel_id": CHANNEL_ID, "support": SUPPORT_HANDLE, "limits": {"FREE": 2, "VIP": 10}, "time_utc": datetime.utcnow().isoformat()}

@app.get("/post-now")
async def post_now():
    from predictor import fetch_real_fixtures, get_ai_prediction
    from database import SessionLocal, is_already_posted, mark_as_posted
    db = SessionLocal()
    try:
        fixtures = fetch_real_fixtures(limit=10); uniq=[]
        for f in fixtures:
            h = f"{f['home']}-{f['away']}-{str(date.today())}-manual-{random.randint(1,9999)}"
            if not is_already_posted(db,h): uniq.append(f); mark_as_posted(db,h)
            if len(uniq)>=2: break
        if not uniq: uniq=fixtures[:2]
        msg=f"🔥 Test {datetime.now().strftime('%H:%M:%S')}\n\n"
        for f in uniq:
            d={"home":f["home"],"away":f["away"],"league":f["league"],"home_xg":1.5,"away_xg":1.2,"home_form":"WDWWL","away_form":"LWDWL","h2h":2,"home_inj":"None","away_inj":"None","odds_h":f["odds_h"],"odds_d":f["odds_d"],"odds_a":f["odds_a"],"odds_over":1.75}; p=get_ai_prediction(d)
            msg+=f"{f['home']} vs {f['away']} - {p['verdict']}\n"
        msg+=f"Bot: {BOT_LINK} | Support: {SUPPORT_HANDLE}\n{DISCLAIMER}"
        if CHANNEL_ID: send_message(CHANNEL_ID, msg)
        return {"posted":True, "fixtures":uniq}
    finally: db.close()

@app.get("/pay")
async def pay(plan:str, uid:str):
    if not FLW_SECRET: return JSONResponse({"error":"Flutterwave keys not set"}, status_code=500)
    amount=2000 if plan=="weekly" else 5000
    tx_ref=f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload={"tx_ref":tx_ref,"amount":amount,"currency":"NGN","redirect_url":f"https://betmaster-p09f.onrender.com/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}","customer":{"email":f"{uid}@betmasterpro.com","name":f"User {uid}"},"customizations":{"title":f"BetMasterPro {plan.upper()}"}}
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
                return HTMLResponse(f"<html><body style='text-align:center;padding:40px;font-family:sans-serif'><h1>✅ Payment Successful!</h1><p>{plan.upper()} - 10 predictions/day till {date.today()+timedelta(days=7 if 'weekly' in plan else 30)}</p><a href='{BOT_LINK}' style='background:green;color:white;padding:15px 30px;text-decoration:none;border-radius:10px'>Go to Bot {BOT_HANDLE}</a><br><br>Support: {SUPPORT_HANDLE}</body></html>")
        return HTMLResponse(f"<h1>❌ Not confirmed {tx_ref}</h1><a href='/subscribe?uid={uid}'>Retry</a>")
    except Exception as e: return HTMLResponse(f"Error {e}")

@app.post("/flutterwave-webhook")
async def webhook(request:Request):
    try:
        body=await request.body()
        if FLW_WEBHOOK_SECRET:
            sig=request.headers.get("verif-hash","")
            if sig!=FLW_WEBHOOK_SECRET: print("Webhook hash mismatch")
        data=json.loads(body)
        if data.get("event")=="charge.completed" and data.get("data",{}).get("status")=="successful":
            tx_ref=data["data"].get("tx_ref",""); parts=tx_ref.split("-")
            if len(parts)>=3 and parts[0]=="BETMASTER": activate_vip(parts[1], parts[2])
        return JSONResponse({"status":"ok"})
    except Exception as e: print(f"Webhook {e}"); return JSONResponse({"status":"error"}, status_code=200)

@app.get("/admin/activate")
async def admin_activate(uid:str, plan:str="monthly", key:str=""):
    if key!=ADMIN_KEY: return HTMLResponse("Wrong admin key", status_code=403)
    ok=activate_vip(uid, plan); return HTMLResponse(f"{'✅ Activated' if ok else '❌ Failed'} User {uid} {plan.upper()} - {BOT_LINK}")

@app.get("/admin/users")
async def admin_users(key:str=""):
    if key!=ADMIN_KEY: return HTMLResponse("Wrong key", status_code=403)
    from database import SessionLocal, get_all_users
    db=SessionLocal()
    try:
        users=get_all_users(db)
        html=f"<html><body style='padding:20px;font-family:sans-serif'><h1>BetMasterPro Users - {BOT_LINK}</h1><p>Support: {SUPPORT_HANDLE} | FREE:2/day VIP:10/day</p><table border=1 cellpadding=8><tr><th>ID</th><th>Username</th><th>Plan</th><th>Used</th><th>Expiry</th><th>Action</th></tr>"
        for u in users:
            limit=10 if u.is_vip else 2
            html+=f"<tr><td>{u.user_id}</td><td>{u.username}</td><td>{'💎 VIP' if u.is_vip else '🆓 FREE'}</td><td>{u.daily_count}/{limit}</td><td>{u.vip_expiry}</td><td><a href='/admin/activate?uid={u.user_id}&plan=weekly&key={key}'>Weekly ₦2k</a> | <a href='/admin/activate?uid={u.user_id}&plan=monthly&key={key}'>Monthly ₦5k</a></td></tr>"
        html+=f"</table><p>Total: {len(users)}</p></body></html>"
        return HTMLResponse(html)
    finally: db.close()

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"""
    <html><head><title>BetMasterPro VIP - {BOT_LINK}</title><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{font-family:sans-serif;background:#0f172a;color:white;text-align:center;padding:20px}}.card{{background:#1e293b;padding:25px;border-radius:15px;max-width:420px;margin:20px auto}}.btn{{display:block;padding:15px;margin:12px 0;border-radius:10px;text-decoration:none;color:white;font-weight:bold}}.weekly{{background:#22c55e}}.monthly{{background:#3b82f6}}</style></head>
    <body><h1>💎 BetMasterPro VIP</h1><p>Your ID: <b>{uid}</b></p>
    <div class="card">
        <h3>Upgrade - Get 10 predictions/day</h3>
        <p>🆓 FREE: 2/day + 1 tip 6AM</p>
        <p>💎 VIP: 10/day + 2 personalized tips</p>
        <a class="btn weekly" href="/pay?plan=weekly&uid={uid}">💚 Weekly ₦2,000 (7 days)</a>
        <a class="btn monthly" href="/pay?plan=monthly&uid={uid}">💙 Monthly ₦5,000 (30 days)</a>
        <p style="font-size:12px">Card + Bank Transfer auto-activate via Flutterwave webhook</p>
        <p>Bot: <a href="{BOT_LINK}" style="color:#22c55e">{BOT_LINK}</a></p>
        <p>Support: <a href="https://t.me/Jibriliks" style="color:#22c55e">{SUPPORT_HANDLE}</a></p>
        <p style="font-size:11px">{DISCLAIMER}</p>
    </div></body></html>
    """)

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
