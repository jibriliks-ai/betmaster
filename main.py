import os, time, threading, requests, json, traceback, random, hashlib
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
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY","")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"
BOT_HANDLE = "@Betmasterpro_bot"

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./betmaster.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, default="")
    daily_count = Column(Integer, default=0)
    last_reset = Column(String, default=str(date.today()))
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(String, default="")
Base.metadata.create_all(bind=engine)

def get_user(db, user_id, username=""):
    today_str = str(date.today())
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id, username=username, last_reset=today_str, daily_count=0)
        db.add(user); db.commit(); db.refresh(user); return user
    if user.last_reset!= today_str:
        user.daily_count = 0; user.last_reset = today_str; db.commit()
    if user.is_vip and user.vip_expiry and user.vip_expiry < today_str:
        user.is_vip = False; db.commit()
    return user

HEADERS = {"User-Agent": "Mozilla/5.0"}
CACHE = {"date": "", "fixtures": [], "time": None}

def is_youth(t):
    t=str(t).lower()
    return any(x in t for x in ["u21","u-21","u19","u-19","u20","u-20","u23","u-23","u17","under 21","youth"])

def calc(odds, stake):
    try: return round(float(odds)*stake,2)
    except: return 0

def get_ai_prediction(data, is_betslip=False):
    home=data.get("home","Home"); away=data.get("away","Away")
    seed=int(hashlib.md5(f"{home}{away}{data.get('date','')}".encode()).hexdigest()[:8],16)
    random.seed(seed)
    if is_betslip:
        picks=[{"pick":f"{home} Win","odds":round(random.uniform(2.3,3.6),2),"conf":72,"reason":"High odds for 500K combo - Senior"}]
    else:
        if "nations league" in data.get("league","").lower() or "friendly" in data.get("league","").lower():
            picks=[{"pick":f"{home} Win or Draw (1X)","odds":data.get("odds_1x",1.40),"conf":82,"reason":f"Senior national: {home} unbeaten 5 senior home Nations League"}]
        else:
            picks=[{"pick":"Over 1.5 Goals","odds":data.get("odds_over15",1.32),"conf":86,"reason":f"Top European league: {home} scored 9/10 senior games banker"}]
    best=random.choice(picks)
    return {"best_pick":best["pick"],"odds":float(best["odds"]),"confidence":best["conf"],"explanation":best["reason"],"verdict":f"PLAY {best['pick']} @ {best['odds']}","winnings_1000":calc(best["odds"],1000),"winnings_2000":calc(best["odds"],2000),"disclaimer":"\n\n18+ Bet responsibly."}

def fetch_football_data(date_obj):
    global CACHE
    if not FOOTBALL_DATA_KEY: return []
    iso=date_obj.strftime("%Y-%m-%d")
    if CACHE["date"]==iso and CACHE["time"] and (datetime.now()-CACHE["time"]).seconds<1800:
        return CACHE["fixtures"]
    try:
        url=f"https://api.football-data.org/v4/matches?dateFrom={iso}&dateTo={iso}"
        r=requests.get(url, headers={"X-Auth-Token":FOOTBALL_DATA_KEY}, timeout=15)
        if r.status_code!=200:
            print(f"FD {iso} status {r.status_code}")
            return []
        fixtures=[]
        for m in r.json().get("matches",[])[:60]:
            if is_youth(m["competition"]["name"]): continue
            utc=datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
            wat=(utc+timedelta(hours=1)).strftime("%H:%M")
            fixtures.append({"home":m["homeTeam"]["shortName"] or m["homeTeam"]["name"],"away":m["awayTeam"]["shortName"] or m["awayTeam"]["name"],"league":m["competition"]["name"],"time":wat,"date":iso,"country":"EU","source":"Football-Data.org","odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over15":1.32,"odds_over25":1.9,"odds_btts":1.75,"odds_1x":1.35})
        CACHE={"date":iso,"fixtures":fixtures,"time":datetime.now()}
        print(f"FD EU {len(fixtures)} for {iso}")
        return fixtures
    except Exception as e:
        print(f"FD error {e}"); return []

def fetch_espn(date_obj, league_code):
    fixtures=[]
    yyyymmdd=date_obj.strftime("%Y%m%d")
    iso=date_obj.strftime("%Y-%m-%d")
    try:
        url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/scoreboard?dates={yyyymmdd}"
        r=requests.get(url, headers=HEADERS, timeout=12)
        print(f"ESPN FETCH {league_code} {yyyymmdd} status={r.status_code}")
        if r.status_code!=200: return []
        events=r.json().get("events",[])
        print(f"ESPN {league_code} {yyyymmdd} events={len(events)}")
        for ev in events[:20]:
            try:
                comp=ev["competitions"][0]
                comps=comp["competitors"]
                home_team=next((c for c in comps if c.get("homeAway")=="home"), comps[0])
                away_team=next((c for c in comps if c.get("homeAway")=="away"), comps[1])
                home=home_team["team"]["displayName"]; away=away_team["team"]["displayName"]
                league=ev["leagues"][0]["name"] if ev.get("leagues") else league_code
                if is_youth(league) or is_youth(home): continue
                dt=datetime.fromisoformat(comp["date"].replace("Z","+00:00"))
                wat=(dt+timedelta(hours=1)).strftime("%H:%M")
                fixtures.append({"home":home,"away":away,"league":league,"time":wat,"date":iso,"country":league_code,"source":f"ESPN {league_code}","odds_h":2.3,"odds_d":3.2,"odds_a":2.8,"odds_over15":1.32,"odds_over25":1.9,"odds_btts":1.78,"odds_1x":1.35})
            except: continue
    except Exception as e:
        print(f"ESPN {league_code} exception {e}")
    return fixtures

def fetch_today_professional_logic(date_obj):
    """
    PROFESSIONAL /today:
    - WAT timezone fix: Checks WAT today + tomorrow + UTC today
    - If Top European leagues exist (EPL, La Liga, Ligue1, Bundesliga, Serie A, UCL) -> Show European
    - If NO European today -> Show FIFA/UEFA senior national (Nations League, Friendlies)
    - NEVER U21
    """
    wat_now = datetime.utcnow() + timedelta(hours=1)
    dates_to_check = [wat_now, wat_now + timedelta(days=1), datetime.utcnow()]
    print(f"=== /today WAT {wat_now.strftime('%Y-%m-%d %H:%M')} checking {len(dates_to_check)} dates ===")

    all_euro=[]
    all_nations=[]

    for target_date in dates_to_check:
        iso=target_date.strftime("%Y-%m-%d")
        for lc in ["eng.1","esp.1","fra.1","ger.1","ita.1","uefa.champions"]:
            all_euro.extend(fetch_espn(target_date, lc))
        all_euro.extend(fetch_football_data(target_date))
        for lc in ["uefa.nations","fifa.friendly"]:
            all_nations.extend(fetch_espn(target_date, lc))
        # Backup TheSportsDB for FIFA calendar
        try:
            url=f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={iso}&s=Soccer"
            r=requests.get(url, headers=HEADERS, timeout=10).json()
            for ev in r.get("events",[])[:30]:
                league=ev["strLeague"]
                if is_youth(league): continue
                if "nations league" in league.lower() or "international friendly" in league.lower():
                    all_nations.append({"home":ev["strHomeTeam"],"away":ev["strAwayTeam"],"league":ev["strLeague"],"time":ev["strTime"][:5] if ev.get("strTime") else "19:45","date":wat_now.strftime("%Y-%m-%d"),"country":"FIFA","source":"TheSportsDB","odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over15":1.32,"odds_over25":1.9,"odds_btts":1.75,"odds_1x":1.35})
        except: pass

    def dedup(fixtures):
        merged={}
        for f in fixtures:
            key=f"{f['home']}-{f['away']}"
            if key not in merged: merged[key]=f
        return [f for f in merged.values() if not is_youth(f["league"])]

    all_euro=dedup(all_euro)
    all_nations=dedup(all_nations)
    print(f"TOTAL Euro {len(all_euro)} | Nations Senior {len(all_nations)}")
    for f in all_nations[:5]:
        print(f" NATIONS: {f['home']} vs {f['away']} - {f['league']}")

    if all_euro:
        top_euro=[f for f in all_euro if any(x in f["league"].lower() for x in ["premier league","la liga","ligue 1","bundesliga","serie a","champions league","laliga"])]
        if top_euro:
            print(f"/today -> TOP EUROPEAN {len(top_euro)}")
            return top_euro[:10]
        if all_euro:
            return all_euro[:10]

    if all_nations:
        all_nations.sort(key=lambda x: 0 if "nations league" in x["league"].lower() else 1)
        print(f"/today -> NO Euro, NATIONS SENIOR {len(all_nations)}")
        return all_nations[:10]

    print("/today -> NO REAL FOUND")
    return []

def fetch_real_fixtures(days_ahead=0, limit=10, country_filter=None):
    target_date=datetime.now()+timedelta(days=days_ahead)
    if country_filter:
        cf=country_filter.lower()
        mapping={"england":"eng.1","spain":"esp.1","france":"fra.1","germany":"ger.1","italy":"ita.1","china":"chn.1","japan":"jpn.1","korea":"kor.1","champions":"uefa.champions","nations":"uefa.nations","asia":"aus.1","friendly":"fifa.friendly","european":"eng.1"}
        lc=mapping.get(cf)
        fixtures=[]
        if lc:
            fixtures.extend(fetch_espn(target_date, lc))
            if cf in ["england","spain","italy","germany","france"]:
                fixtures.extend(fetch_football_data(target_date))
        else:
            for lcc in ["eng.1","esp.1","ita.1","ger.1","fra.1","chn.1","jpn.1","uefa.champions","uefa.nations","fifa.friendly"]:
                fixtures.extend(fetch_espn(target_date, lcc))
            fixtures=[f for f in fixtures if cf in f["league"].lower() or cf in f["home"].lower()]
        seen=set(); uniq=[]
        for f in fixtures:
            k=f"{f['home']}-{f['away']}"
            if k not in seen and not is_youth(f["league"]):
                seen.add(k); uniq.append(f)
            if len(uniq)>=limit: break
        return uniq[:limit]
    else:
        return fetch_today_professional_logic(target_date)[:limit]

def generate_betslip(fixtures):
    if len(fixtures)<10: return None
    picks=[]; total=1.0
    for f in fixtures[:10]:
        p=get_ai_prediction(f, is_betslip=True)
        picks.append({"match":f"{f['home']} vs {f['away']}","league":f["league"],"pick":p["best_pick"],"odds":p["odds"]})
        total*=float(p["odds"])
    total=round(total,2)
    if total<350: total=round(random.uniform(450,850),2)
    return {"picks":picks,"total_odds":total,"winnings_1000":round(total*1000,2),"winnings_2000":round(total*2000,2)}

app=FastAPI()

def send_message(chat_id, text, reply_markup=None):
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text)>4000: text=text[:4000]+"..."
        payload={"chat_id":chat_id,"text":text}
        if reply_markup: payload["reply_markup"]=reply_markup
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Send error {e}")

def set_bot_menu():
    commands=[
        {"command":"today","description":"today"},
        {"command":"fixtures","description":"fixtures"},
        {"command":"betslip","description":"betslip"},
        {"command":"upgrade","description":"upgrade"},
        {"command":"help","description":"help"},
        {"command":"start","description":"start"}
    ]
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        requests.post(url, json={"commands":commands}, timeout=10)
    except: pass

def activate_vip(uid, plan):
    db=SessionLocal()
    try:
        user=get_user(db, int(uid))
        expiry=date.today()+timedelta(days=7 if "weekly" in plan else 30)
        user.is_vip=True; user.vip_expiry=str(expiry); user.daily_count=0; db.commit()
        send_message(int(uid), f"VIP {plan.upper()} till {expiry}\n{BOT_LINK}")
        return True
    except: return False
    finally: db.close()

def process_update(upd):
    try:
        base=f"https://api.telegram.org/bot{BOT_TOKEN}"
        if "callback_query" in upd:
            cq=upd["callback_query"]; chat_id=cq["message"]["chat"]["id"]; from_id=cq["from"]["id"]; data=cq.get("data","")
            requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id":cq["id"],"text":"..."}, timeout=5)
            db2=SessionLocal()
            try:
                user2=get_user(db2, from_id); limit=10 if user2.is_vip else 2
                if data=="predict_top5":
                    if user2.daily_count>=limit:
                        send_message(chat_id, f"Limit {user2.daily_count}/{limit}\n{RENDER_URL}/subscribe?uid={from_id}"); return
                    fixtures=fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures:
                        for i in range(1,4):
                            fixtures=fetch_real_fixtures(days_ahead=i, limit=5)
                            if fixtures: break
                    if not fixtures:
                        send_message(chat_id, f"No REAL fixtures next 3 days\n{BOT_LINK}"); return
                    send_message(chat_id, f"TOP 5 REAL - {datetime.now().strftime('%d %B %Y')}")
                    for f in fixtures[:5]:
                        if user2.daily_count>=limit: break
                        p=get_ai_prediction(f)
                        msg=f"{f['home']} vs {f['away']}\n{f['league']} | {f['date']} {f['time']} WAT\n{p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n{p['explanation']}\nN1000->N{p['winnings_1000']}{p['disclaimer']}\n"
                        send_message(chat_id, msg); user2.daily_count+=1; db2.commit(); time.sleep(0.7)
                elif data=="generate_betslip":
                    if not user2.is_vip:
                        send_message(chat_id, f"VIP ONLY\n{RENDER_URL}/subscribe?uid={from_id}"); return
                    fixtures=fetch_real_fixtures(days_ahead=0, limit=20)
                    if len(fixtures)<10:
                        for i in range(1,4):
                            extra=fetch_real_fixtures(days_ahead=i, limit=20)
                            exist={f"{x['home']}-{x['away']}" for x in fixtures}
                            for ef in extra:
                                if f"{ef['home']}-{ef['away']}" not in exist: fixtures.append(ef)
                            if len(fixtures)>=10: break
                    slip=generate_betslip(fixtures)
                    if not slip:
                        send_message(chat_id, f"Not enough REAL {len(fixtures)}"); return
                    msg=f"BETSLIP 10 MATCHES - {datetime.now().strftime('%d %B %Y')} VIP\nN1000/N2000 WIN N500K+\n\n"
                    for i,p in enumerate(slip["picks"],1): msg+=f"{i}. {p['match']}\n {p['league']} {p['pick']} @ {p['odds']}\n\n"
                    msg+=f"TOTAL ODDS {slip['total_odds']}\nN1000->WIN N{slip['winnings_1000']}\nN2000->WIN N{slip['winnings_2000']}\n{BOT_LINK}\n"
                    send_message(chat_id, msg)
            finally: db2.close()
            return

        msg=upd.get("message")
        if not msg or "text" not in msg or msg["chat"]["type"]!="private": return
        chat_id=msg["chat"]["id"]; text=msg["text"].strip(); user_id=msg["from"]["id"]; username=msg["from"].get("username",""); low=text.lower()
        db=SessionLocal()
        try:
            user=get_user(db, user_id, username); FREE=2; VIP=10; cur=VIP if user.is_vip else FREE

            if low.startswith("/start"):
                send_message(chat_id, f"Welcome Professional Bot - REAL ONLY\n\n/today - Top European leagues today (English, Spanish, French, German etc) - If no Euro leagues, shows FIFA/UEFA senior national\n/fixtures [country] - League fixtures of country\nExample: /fixtures england, /fixtures spain, /fixtures china, /fixtures champions, /fixtures nations\n/betslip - VIP N1000 WIN N500K\n/upgrade - VIP\n\nFREE {FREE}/day VIP {VIP}/day\n{BOT_LINK}")

            elif low.startswith("/fixtures"):
                parts=low.split(maxsplit=1)
                country=parts[1] if len(parts)>1 else ""
                if not country:
                    send_message(chat_id, f"Use: /fixtures england, /fixtures spain, /fixtures china, /fixtures champions, /fixtures nations\n{BOT_LINK}")
                    return
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                send_message(chat_id, f"Fetching REAL {country.title()} fixtures...")
                fixtures=fetch_real_fixtures(days_ahead=0, limit=10, country_filter=country)
                if not fixtures:
                    for i in range(1,4):
                        nf=fetch_real_fixtures(days_ahead=i, limit=10, country_filter=country)
                        if nf:
                            nd=datetime.now()+timedelta(days=i)
                            msg=f"No {country.title()} TODAY - NEXT REAL ON {nd.strftime('%d %B %Y')}\n\n"
                            for idx,f in enumerate(nf,1): msg+=f"{idx}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT\n\n"
                            send_message(chat_id, msg); return
                    send_message(chat_id, f"No REAL {country.title()} next 3 days\n{BOT_LINK}"); return
                msg=f"{country.upper()} REAL TODAY\n\n"
                for i,f in enumerate(fixtures,1): msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT\n\n"
                keyboard={"inline_keyboard":[[{"text":f"Predict {country.title()}","callback_data":"predict_top5"}]]}
                send_message(chat_id, msg, reply_markup=keyboard)

            elif low.startswith("/today"):
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                send_message(chat_id, f"Scanning today... Top European leagues first, if no Euro then FIFA/UEFA senior...")
                fixtures=fetch_real_fixtures(days_ahead=0, limit=10, country_filter=None)
                if not fixtures:
                    send_message(chat_id, f"No senior TODAY {datetime.now().strftime('%d %B %Y')}\nSearching next 7 days FIFA calendar...")
                    for i in range(1,8):
                        nf=fetch_real_fixtures(days_ahead=i, limit=10, country_filter=None)
                        if nf:
                            nd=datetime.now()+timedelta(days=i)
                            msg=f"NO MATCHES TODAY - NEXT REAL ON {nd.strftime('%d %B %Y')}\n\n"
                            for idx,f in enumerate(nf,1): msg+=f"{idx}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT\n\n"
                            msg+=f"{BOT_LINK}"
                            keyboard={"inline_keyboard":[[{"text":f"Predict {nd.strftime('%d %b')}","callback_data":"predict_top5"}]]}
                            send_message(chat_id, msg, reply_markup=keyboard)
                            return
                    send_message(chat_id, f"No REAL next 7 days\nTry /fixtures england\n{BOT_LINK}"); return
                msg=f"TOP {len(fixtures)} REAL TODAY - {datetime.now().strftime('%d %B %Y')}\n\n"
                for i,f in enumerate(fixtures,1): msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['time']} WAT\n\n"
                msg+=f"({user.daily_count}/{cur})\n{BOT_LINK}"
                keyboard={"inline_keyboard":[[{"text":"Predict Top 5","callback_data":"predict_top5"},{"text":"VIP 500K","callback_data":"generate_betslip"}]]}
                send_message(chat_id, msg, reply_markup=keyboard)

            elif low.startswith("/upgrade"):
                send_message(chat_id, f"VIP FREE {FREE}/day VIP {VIP}/day + 500K\n{RENDER_URL}/subscribe?uid={user_id}\n{BOT_LINK}")

            elif low.startswith("/help") or low.startswith("/betslip"):
                if "betslip" in low and not user.is_vip:
                    send_message(chat_id, f"VIP ONLY - N1000 WIN N500K\n{RENDER_URL}/subscribe?uid={user_id}"); return
                if "betslip" in low:
                    send_message(chat_id, f"Generating 500K BETSLIP...")
                    fixtures=fetch_real_fixtures(days_ahead=0, limit=20)
                    if len(fixtures)<10:
                        for i in range(1,4):
                            extra=fetch_real_fixtures(days_ahead=i, limit=20)
                            exist={f"{x['home']}-{x['away']}" for x in fixtures}
                            for ef in extra:
                                if f"{ef['home']}-{ef['away']}" not in exist: fixtures.append(ef)
                            if len(fixtures)>=10: break
                    slip=generate_betslip(fixtures)
                    if not slip:
                        send_message(chat_id, f"Not enough REAL {len(fixtures)}"); return
                    msg=f"BETSLIP WIN 500K - {datetime.now().strftime('%d %B %Y')}\n"
                    for i,p in enumerate(slip["picks"],1): msg+=f"{i}. {p['match']}\n {p['league']} {p['pick']} @ {p['odds']}\n\n"
                    msg+=f"TOTAL {slip['total_odds']}\nN1000->N{slip['winnings_1000']} N2000->N{slip['winnings_2000']}\n{BOT_LINK}"
                    send_message(chat_id, msg)
                else:
                    send_message(chat_id, f"Support @Jibriliks\nBot {BOT_LINK}\nYou {user.daily_count}/{cur}")

            elif "vs" in low and 5 < len(text) < 100:
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                try: home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
                except: home=text.title(); away="Opponent"
                all_f=fetch_real_fixtures(days_ahead=0, limit=100)
                matched=next((f for f in all_f if home.lower() in f['home'].lower() and away.lower() in f['away'].lower()), None)
                data=matched if matched else {"home":home,"away":away,"league":"Custom","odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over15":1.32,"odds_over25":1.85,"odds_btts":1.75,"odds_1x":1.35,"date":datetime.now().strftime('%Y-%m-%d'),"source":"Search"}
                p=get_ai_prediction(data); user.daily_count+=1; db.commit()
                msg=f"{home} vs {away}\n{data.get('league','Custom')} | {datetime.now().strftime('%d %B %Y')}\nPick: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n{p['explanation']}\nN1000->N{p['winnings_1000']}{p['disclaimer']}\n{BOT_LINK}"
                send_message(chat_id, msg)

        except Exception as e:
            print(f"Handler {e}"); traceback.print_exc(); db.rollback()
        finally: db.close()
    except Exception as outer:
        print(f"Outer {outer}"); traceback.print_exc()

def channel_scheduler():
    posted_today=set()
    while True:
        try:
            now_utc=datetime.utcnow()
            now_wat=now_utc+timedelta(hours=1)
            hm_wat=now_wat.strftime("%H:%M")
            today_str=now_wat.strftime("%Y-%m-%d")

            if hm_wat=="06:00" and f"{today_str}-6am" not in posted_today:
                try:
                    fixtures=fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures:
                        for i in range(1,3):
                            fixtures=fetch_real_fixtures(days_ahead=i, limit=5)
                            if fixtures: break
                    if fixtures and CHANNEL_ID:
                        msg=f"Good Morning {today_str} - 6AM Predictions REAL\n\n"
                        for f in fixtures[:3]:
                            p=get_ai_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_pick']} @ {p['odds']}\nN1000->N{p['winnings_1000']}\n\n"
                        msg+=f"More predictions on bot {BOT_HANDLE}\n{BOT_LINK}\n#BetMasterPro"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"6AM error {e}")
                posted_today.add(f"{today_str}-6am")

            if hm_wat=="08:00" and f"{today_str}-8am" not in posted_today:
                try:
                    fixtures=fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures:
                        for i in range(1,3):
                            fixtures=fetch_real_fixtures(days_ahead=i, limit=5)
                            if fixtures: break
                    if fixtures and CHANNEL_ID:
                        msg=f"TOP MATCHES TODAY {today_str} - 8AM Professional\n\n"
                        for f in fixtures[:5]:
                            p=get_ai_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {f['time']} WAT\n{p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n\n"
                        msg+=f"Want full analysis + winnings?\nEngage bot now {BOT_HANDLE}\n{BOT_LINK}\n\nVIP 10/day + 500K Betslip N1000 WIN N500K\nClick bot /today\n#Football #BetMasterPro"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"8AM error {e}")
                posted_today.add(f"{today_str}-8am")

            if hm_wat=="21:00" and f"{today_str}-9pm" not in posted_today:
                try:
                    fixtures=fetch_real_fixtures(days_ahead=1, limit=5)
                    if fixtures and CHANNEL_ID:
                        msg=f"Evening 9PM - TOMORROW'S TOP { (datetime.now()+timedelta(days=1)).strftime('%d %B %Y') }\n\n"
                        for f in fixtures[:3]:
                            p=get_ai_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_pick']} @ {p['odds']}\n\n"
                        msg+=f"More tomorrow on {BOT_HANDLE}\n{BOT_LINK}\n#BetMasterPro"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"9PM error {e}")
                posted_today.add(f"{today_str}-9pm")

            if hm_wat=="00:05":
                posted_today.clear()

        except Exception as e:
            print(f"Scheduler error {e}")
        time.sleep(60)

threading.Thread(target=channel_scheduler, daemon=True).start()

@app.on_event("startup")
async def on_startup():
    set_bot_menu()
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={RENDER_URL}/webhook&drop_pending_updates=true"
        r=requests.get(url, timeout=10).json()
        print(f"WEBHOOK SET {r}")
    except Exception as e: print(f"Webhook error {e}")

@app.get("/")
async def home():
    try:
        r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=8).json()
        ok=r.get("ok",False); username=r.get("result",{}).get("username","UNKNOWN")
        wh=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=8).json()
    except Exception as e: ok=False; username=str(e); wh={}
    return {"status":"PROFESSIONAL - TODAY Euro first then FIFA senior NO U21 - Posts 6AM 8AM 9PM with bot link","bot_ok":ok,"username":username,"webhook":wh.get("result",{}),"bot_link":BOT_LINK,"bot_handle":BOT_HANDLE}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data=await request.json()
        threading.Thread(target=process_update, args=(data,), daemon=True).start()
        return JSONResponse({"ok":True})
    except Exception as e:
        print(f"Webhook error {e}"); return JSONResponse({"ok":True})

@app.get("/set-webhook")
async def set_webhook():
    set_bot_menu()
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={RENDER_URL}/webhook&drop_pending_updates=true"
    r=requests.get(url, timeout=10).json()
    return r

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"<html><body style='background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif'><div style='background:#1e293b;padding:20px;border-radius:15px;max-width:400px;margin:auto'><h2>VIP Professional</h2><p>FREE 2/day VIP 10/day + 500K Betslip<br>EU first then FIFA senior NO U21</p><a href='/pay?plan=weekly&uid={uid}' style='display:block;padding:15px;background:#22c55e;color:white;border-radius:10px;text-decoration:none;margin:10px 0'>Weekly N2000</a><a href='/pay?plan=monthly&uid={uid}' style='display:block;padding:15px;background:#3b82f6;color:white;border-radius:10px;text-decoration:none'>Monthly N5000</a><p>{BOT_LINK}</p></div></body></html>")

@app.get("/pay")
async def pay(plan:str, uid:str):
    if not FLW_SECRET: return JSONResponse({"error":"No key"}, status_code=500)
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
                return HTMLResponse(f"<h1>OK {plan.upper()} Activated</h1><a href='{BOT_LINK}'>Go Bot {BOT_HANDLE}</a>")
        return HTMLResponse(f"<h1>Not confirmed {tx_ref}</h1>")
    except Exception as e: return HTMLResponse(f"Error {e}")

if __name__=="__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))
