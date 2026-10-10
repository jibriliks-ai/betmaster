"""
main.py — BetMaster Pro v8
VIP markets + proof page + league gating + team stats + interactive buttons
+ full user persistence + channel link branding.

Channel: Bet Master Pro (https://t.me/+IFK0qoDI2B5lYWI0)
Bot: @Betmasterpro_bot
"""

import os, time, threading, requests, json, traceback, random, hashlib, csv, io, re, math, html
from datetime import datetime, timedelta, date
from collections import defaultdict

import numpy as np
from scipy.stats import poisson
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ──
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()
if CHANNEL_ID and not CHANNEL_ID.startswith("-"):
    CHANNEL_ID = "-100" + CHANNEL_ID.lstrip("-")
FLW_SECRET = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
FLW_WEBHOOK_HASH = os.getenv("FLW_WEBHOOK_HASH", "")
THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"
BOT_HANDLE = "@Betmasterpro_bot"

# ── CHANNEL BRANDING ──
CHANNEL_LINK = "https://t.me/+IFK0qoDI2B5lYWI0"
CHANNEL_NAME = "Bet Master Pro"

ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "")
ADMIN_IDS = set()
for _aid in ADMIN_IDS_RAW.split(","):
    _aid = _aid.strip()
    if _aid:
        try: ADMIN_IDS.add(int(_aid))
        except: pass

def is_admin(uid):
    try: return int(uid) in ADMIN_IDS
    except: return False

HEADERS = {"User-Agent":"Mozilla/5.0"}
SB_HEADERS = {"User-Agent":"Mozilla/5.0","Accept":"application/json",
              "Content-Type":"application/json","Current-Country":"NG"}

# ── REGIONS ──
REGIONS = {
    "africa":   {"label":"🌍 Africa","emoji":"🌍"},
    "asia":     {"label":"🌏 Asia","emoji":"🌏"},
    "europe":   {"label":"🇪🇺 Europe","emoji":"🇪🇺"},
    "america":  {"label":"🇺🇸 America","emoji":"🇺🇸"},
    "national": {"label":"🏆 National","emoji":"🏆"},
}
REGION_KEYS = list(REGIONS.keys())
MAX_PREFERENCES = 3

# ── LEAGUE GATING ──
FREE_LEAGUE_KEYWORDS = ["premier league","la liga","serie a","bundesliga",
                         "ligue 1","champions league","uefa champions"]
PREMIUM_LEAGUE_KEYWORDS = ["chinese","j1 league","j.league","j-league","k league",
    "k-league","saudi","qatar","uae","thai","indonesia","malaysia","v.league",
    "indian super","a-league","mls","major league soccer","liga mx","brasileir",
    "argentina","colombia","chile","peru","uruguay","ecuador","paraguay",
    "venezuela","costa rica","south africa","egypt","morocco","nigeria","ghana",
    "kenya","tunisia","algeria","ivory coast","cameroon","eredivisie",
    "primeira liga","süper lig","scottish","belgian","greek","swiss","danish",
    "norwegian","swedish","russian","ukrainian","austrian","czech","polish",
    "romanian","croatian","serbian","europa league","conference league",
    "world cup","nations league","euro qualifier","afc asian","caf","concacaf","copa"]

def is_free_league(fixture):
    lg = (fixture.get("league") or "").lower()
    return any(k in lg for k in FREE_LEAGUE_KEYWORDS)

def is_premium_league(fixture):
    lg = (fixture.get("league") or "").lower()
    return any(k in lg for k in PREMIUM_LEAGUE_KEYWORDS)

# ── KEYBOARDS ──
BTN_TODAY = "⚽ Today's Fixtures"
BTN_N1M = "🚀 N1M Challenge"
BTN_EUROPE = "🇪🇺 European Leagues"
BTN_ASIA = "🌏 Asian Leagues"
BTN_AMERICA = "🇺🇸 American Leagues"
BTN_AFRICA = "🌍 African Leagues"
BTN_ACCUMULATOR = "🎫 Accumulator"
BTN_PREFERENCES = "⚙️ My Preferences"

def get_main_keyboard(is_admin_user=False):
    kb = [
        [{"text":BTN_TODAY},{"text":BTN_N1M}],
        [{"text":BTN_EUROPE},{"text":BTN_ASIA}],
        [{"text":BTN_AMERICA},{"text":BTN_AFRICA}],
        [{"text":BTN_ACCUMULATOR},{"text":BTN_PREFERENCES}],
    ]
    if is_admin_user: kb.append([{"text":"🔐 Admin Panel"}])
    return {"keyboard":kb,"resize_keyboard":True,"is_persistent":True,
            "input_field_placeholder":"Tap a button or send Team A vs Team B"}

def get_inline_menu(is_admin_user=False):
    rows = [
        [{"text":"🧠  Analyze Top 5 Matches","callback_data":"predict_top5"}],
        [{"text":"⚽ Today's Fixtures","callback_data":"menu_today"},
         {"text":"🎫  Accumulator","callback_data":"build_accumulator"}],
        [{"text":"🇪🇺 Europe","callback_data":"predict_europe"},
         {"text":"🌏 Asia","callback_data":"predict_asia"}],
        [{"text":"🇺🇸 America","callback_data":"predict_america"},
         {"text":"🌍 Africa","callback_data":"predict_africa"}],
        [{"text":"🏆 National","callback_data":"predict_national"},
         {"text":"✅ Sure 10 Picks","callback_data":"sure_10_all"}],
        [{"text":"🚀  N1M Challenge — ₦1,000 → ₦1,000,000","callback_data":"n1m_challenge"}],
        [{"text":"📊 Stats","callback_data":"menu_stats"},
         {"text":"🏆 Leaderboard","callback_data":"menu_leaderboard"}],
        [{"text":"👤 Profile","callback_data":"menu_profile"},
         {"text":"⚙️ Preferences","callback_data":"menu_prefs"}],
        [{"text":"🎁 Refer & Earn","callback_data":"menu_refer"},
         {"text":"💎 Upgrade","callback_data":"menu_upgrade"}],
        [{"text":"📢 Join Channel","url":CHANNEL_LINK}],
    ]
    if is_admin_user:
        rows.append([{"text":"🔐 Admin Panel","callback_data":"menu_admin"}])
    return {"inline_keyboard": rows}

def get_footer_menu_button():
    return [{"text":"🏠 Main Menu","callback_data":"menu_main"}]

def add_footer_button(kb=None):
    if kb is None: return {"inline_keyboard":[get_footer_menu_button()]}
    if "inline_keyboard" not in kb: kb = {"inline_keyboard":[]}
    for row in kb["inline_keyboard"]:
        if any(b.get("callback_data")=="menu_main" for b in row): return kb
    kb["inline_keyboard"].append(get_footer_menu_button())
    return kb

# ── DB ──
from sqlalchemy import (create_engine, Column, Integer, String, Boolean,
                        Float, DateTime, Text, func)
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./betmaster.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
try:
    engine = create_engine(DATABASE_URL,
        connect_args={"check_same_thread":False} if "sqlite" in DATABASE_URL else {},
        pool_pre_ping=True)
except:
    engine = create_engine("sqlite:///./betmaster.db",
        connect_args={"check_same_thread":False})

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, default="")
    first_name = Column(String, default="")
    daily_count = Column(Integer, default=0)
    last_reset = Column(String, default=str(date.today()))
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(String, default="")
    vip_plan = Column(String, default="")
    streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    total_predictions = Column(Integer, default=0)
    total_wins = Column(Integer, default=0)
    total_losses = Column(Integer, default=0)
    referral_code = Column(String, default="", index=True)
    referred_by = Column(String, default="")
    referral_count = Column(Integer, default=0)
    fav_leagues = Column(Text, default="")
    fav_markets = Column(Text, default="")
    preferred_regions = Column(Text, default="")
    preferences_set = Column(Boolean, default=False)
    notified_today = Column(String, default="")
    daily_notify_enabled = Column(Boolean, default=True)
    n1m_bankroll = Column(Float, default=0.0)
    n1m_best = Column(Float, default=0.0)
    bankroll = Column(Float, default=10000.0)
    preferred_plan = Column(String, default="")
    total_visits = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    match = Column(String)
    league = Column(String)
    market = Column(String)
    pick = Column(String)
    odds = Column(Float)
    confidence = Column(Float)
    result = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    match_date = Column(String)

class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, index=True)
    referred_id = Column(Integer, index=True)
    rewarded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Proof(Base):
    __tablename__ = "proofs"
    id = Column(Integer, primary_key=True)
    proof_date = Column(String, index=True)
    match = Column(String)
    league = Column(String, default="")
    pick = Column(String)
    odds = Column(Float)
    result = Column(String, default="WON")
    created_at = Column(DateTime, default=datetime.utcnow)

try: Base.metadata.create_all(bind=engine)
except Exception as e: print(f"DB init: {e}")

def ensure_schema():
    from sqlalchemy import text, inspect
    try:
        insp = inspect(engine)
        existing = {c["name"] for c in insp.get_columns("users")}
        migrations = [
            ("preferred_plan", "VARCHAR DEFAULT ''"),
            ("total_visits", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing:
                try:
                    with engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                        conn.commit()
                    print(f"[migrate] Added users.{col_name}")
                except Exception as e:
                    print(f"[migrate] {col_name}: {e}")
    except Exception as e:
        print(f"[migrate] {e}")

ensure_schema()

# ── DB HELPERS ──
def get_user(db, user_id, username="", first_name=""):
    today_str = str(date.today())
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            ref_code = hashlib.md5(f"BM{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
            user = User(user_id=user_id, username=username, first_name=first_name,
                        last_reset=today_str, daily_count=0, referral_code=ref_code,
                        last_seen=datetime.utcnow(), total_visits=1)
            db.add(user); db.commit(); db.refresh(user); return user
        if user.last_reset != today_str:
            user.daily_count = 0; user.last_reset = today_str; db.commit()
        if user.is_vip and user.vip_expiry and user.vip_expiry < today_str:
            user.is_vip = False; user.vip_plan = ""; db.commit()
        user.last_seen = datetime.utcnow()
        try: user.total_visits = (user.total_visits or 0) + 1
        except Exception: pass
        if username and user.username != username: user.username = username
        if first_name and user.first_name != first_name: user.first_name = first_name
        db.commit(); return user
    except Exception as e:
        print(f"get_user: {e}")
        class Dummy:
            user_id=user_id; daily_count=0; is_vip=False; vip_expiry=""; vip_plan=""
            streak=0; best_streak=0; total_predictions=0; total_wins=0; total_losses=0
            referral_code=""; referral_count=0; fav_leagues=""; fav_markets=""
            preferred_regions=""; preferences_set=False; notified_today=""
            daily_notify_enabled=True
            n1m_bankroll=0.0; n1m_best=0.0; bankroll=10000.0; is_banned=False
            preferred_plan=""; total_visits=0
            first_name=first_name; username=username
            created_at=datetime.utcnow(); last_seen=datetime.utcnow()
        return Dummy()

def get_user_prefs(user):
    raw = getattr(user, "preferred_regions", "") or ""
    return [r for r in raw.split(",") if r in REGIONS]

def activate_vip(uid, plan, silent=False):
    db = SessionLocal()
    try:
        user = get_user(db, int(uid))
        days = {"daily":1,"weekly":7,"monthly":30}.get(plan, 30)
        expiry = date.today() + timedelta(days=days)
        user.is_vip = True; user.vip_expiry = str(expiry)
        user.vip_plan = plan; user.daily_count = 0
        user.preferred_plan = plan
        db.commit()
        if not silent:
            send_message(int(uid), (
                f"🎉 *VIP {plan.upper()} ACTIVATED!*\n\n"
                f"Valid until: *{expiry}*\n\n"
                f"*Unlocked:*\n"
                f"✅ 10 predictions/day\n"
                f"✅ 🎯 Correct Score + Handicap markets\n"
                f"✅ 🎫 20-match Betslip with real booking codes\n"
                f"✅ 🌏 All Asian / 🇺🇸 American / 🌍 African leagues\n"
                f"✅ 🚀 N1M Challenge\n"
                f"✅ Full 13-market probabilities + bankroll advisor\n\n"
                f"Welcome to the winning side. 💎\n\n"
                f"📢 *Join our channel:* {CHANNEL_LINK}"
            ), reply_markup=get_main_keyboard(is_admin(int(uid))), parse_mode="Markdown")
        return True
    except Exception as e:
        print(f"activate_vip: {e}"); return False
    finally: db.close()

def revoke_vip(uid):
    db = SessionLocal()
    try:
        user = get_user(db, int(uid))
        user.is_vip = False; user.vip_expiry = ""; user.vip_plan = ""
        db.commit(); return True
    except: return False
    finally: db.close()

def award_referral(db, referrer_code, new_user_id):
    try:
        referrer = db.query(User).filter(User.referral_code == referrer_code).first()
        if not referrer: return
        existing = db.query(Referral).filter(
            Referral.referrer_id == referrer.user_id,
            Referral.referred_id == new_user_id).first()
        if existing: return
        db.add(Referral(referrer_id=referrer.user_id, referred_id=new_user_id, rewarded=True))
        referrer.referral_count = (referrer.referral_count or 0) + 1
        if referrer.is_vip and referrer.vip_expiry:
            try:
                current = datetime.strptime(referrer.vip_expiry, "%Y-%m-%d").date()
                new_expiry = current + timedelta(days=7)
            except: new_expiry = date.today() + timedelta(days=7)
        else:
            referrer.is_vip = True; new_expiry = date.today() + timedelta(days=7)
        referrer.vip_expiry = str(new_expiry); db.commit()
        send_message(referrer.user_id,
                     f"🎁 Referral Reward! +7 VIP days. Valid until {new_expiry}",
                     reply_markup=get_main_keyboard(is_admin(referrer.user_id)))
    except Exception as e: print(f"Referral: {e}")

# ── BRAIN ──
HISTORICAL_STATS = {}
H2H_CACHE = {}
ODDS_CACHE = {"time":None,"data":{}}
LEAGUE_AVG_GOALS = {}
SB_EVENTS_CACHE = {"time":None,"data":[]}

TOP_LEAGUES = ["premier league","la liga","serie a","bundesliga","ligue 1",
               "champions league","eredivisie","primeira","mls","brasileir",
               "liga mx","chinese super","j1 league","k league","saudi pro"]

def is_youth(t):
    t = str(t).lower()
    return any(x in t for x in ["u21","u-21","u19","u-20","u23","u17","youth",
                                 "under 21","women","wfc"])

def calc(o, s):
    try: return round(float(o)*s, 2)
    except: return 0

def load_brain():
    global HISTORICAL_STATS, LEAGUE_AVG_GOALS
    codes = ["E0","SP1","D1","I1","F1","E1","E2","E3","SP2","D2","I2","F2",
             "N1","B1","P1","T1","G1","SC0"]
    for code in codes:
        try:
            url = f"https://www.football-data.co.uk/mmz4281/2526/{code}.csv"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            reader = csv.DictReader(io.StringIO(r.text))
            rows = list(reader)[-120:]
            lg_goals = []
            for row in rows:
                home = row.get("HomeTeam",""); away = row.get("AwayTeam","")
                if not home or not away: continue
                for team in [home, away]:
                    if team not in HISTORICAL_STATS:
                        HISTORICAL_STATS[team] = {"games":0,"scored":0,"conceded":0,
                            "wins":0,"draws":0,"losses":0,"form":[],"btts":0,
                            "over15":0,"over25":0,"over35":0,"clean":0,
                            "failed_score":0,"league":code}
                try:
                    fthg = int(row.get("FTHG",0) or 0); ftag = int(row.get("FTAG",0) or 0)
                except: continue
                lg_goals.append(fthg+ftag)
                HISTORICAL_STATS[home]["games"] += 1
                HISTORICAL_STATS[away]["games"] += 1
                HISTORICAL_STATS[home]["scored"] += fthg
                HISTORICAL_STATS[home]["conceded"] += ftag
                HISTORICAL_STATS[away]["scored"] += ftag
                HISTORICAL_STATS[away]["conceded"] += fthg
                if fthg>0 and ftag>0:
                    HISTORICAL_STATS[home]["btts"] += 1
                    HISTORICAL_STATS[away]["btts"] += 1
                else:
                    if fthg==0: HISTORICAL_STATS[home]["failed_score"] += 1
                    if ftag==0: HISTORICAL_STATS[away]["failed_score"] += 1
                    if ftag==0: HISTORICAL_STATS[home]["clean"] += 1
                    if fthg==0: HISTORICAL_STATS[away]["clean"] += 1
                if fthg+ftag>1:
                    HISTORICAL_STATS[home]["over15"] += 1
                    HISTORICAL_STATS[away]["over15"] += 1
                if fthg+ftag>2:
                    HISTORICAL_STATS[home]["over25"] += 1
                    HISTORICAL_STATS[away]["over25"] += 1
                if fthg+ftag>3:
                    HISTORICAL_STATS[home]["over35"] += 1
                    HISTORICAL_STATS[away]["over35"] += 1
                if fthg>ftag:
                    HISTORICAL_STATS[home]["wins"] += 1
                    HISTORICAL_STATS[home]["form"].append("W")
                    HISTORICAL_STATS[away]["losses"] += 1
                    HISTORICAL_STATS[away]["form"].append("L")
                elif fthg==ftag:
                    HISTORICAL_STATS[home]["draws"] += 1
                    HISTORICAL_STATS[home]["form"].append("D")
                    HISTORICAL_STATS[away]["draws"] += 1
                    HISTORICAL_STATS[away]["form"].append("D")
                else:
                    HISTORICAL_STATS[home]["losses"] += 1
                    HISTORICAL_STATS[home]["form"].append("L")
                    HISTORICAL_STATS[away]["wins"] += 1
                    HISTORICAL_STATS[away]["form"].append("W")
                hk = f"{home}_vs_{away}"
                if hk not in H2H_CACHE: H2H_CACHE[hk] = []
                H2H_CACHE[hk].append({"home":home,"away":away,"fthg":fthg,"ftag":ftag,
                    "result":"H" if fthg>ftag else "A" if ftag>fthg else "D",
                    "total":fthg+ftag,"btts":1 if fthg>0 and ftag>0 else 0})
            if lg_goals: LEAGUE_AVG_GOALS[code] = sum(lg_goals)/len(lg_goals)
            for k in HISTORICAL_STATS:
                if len(HISTORICAL_STATS[k]["form"])>5:
                    HISTORICAL_STATS[k]["form"] = HISTORICAL_STATS[k]["form"][-5:]
        except Exception as e: print(f"Brain {code}: {e}")
    for code in codes:
        if code not in LEAGUE_AVG_GOALS: LEAGUE_AVG_GOALS[code] = 2.65
    print(f"BRAIN: {len(HISTORICAL_STATS)} teams")

# ── DIXON-COLES ──
def estimate_team_strengths(team_name, league_code="E0"):
    stats = HISTORICAL_STATS.get(team_name)
    league_avg = LEAGUE_AVG_GOALS.get(league_code, 2.65)/2.0
    if not stats or stats["games"]<3:
        return {"attack":1.0,"defense":1.0,"games":0,"source":"neutral"}
    games = stats["games"]
    attack = max(0.4, min(2.5, (stats["scored"]/games)/league_avg))
    defense = max(0.4, min(2.5, (stats["conceded"]/games)/league_avg))
    return {"attack":round(attack,3),"defense":round(defense,3),"games":games,
            "avg_scored":round(stats["scored"]/games,2),
            "avg_conceded":round(stats["conceded"]/games,2),"source":"historical"}

def dixon_coles_predict(home_team, away_team, league_code="E0",
                        home_advantage=0.20, rho=-0.05, max_goals=6):
    h = estimate_team_strengths(home_team, league_code)
    a = estimate_team_strengths(away_team, league_code)
    lpt = LEAGUE_AVG_GOALS.get(league_code, 2.65)/2.0
    hx = max(0.3, min(4.5, h["attack"]*a["defense"]*lpt*math.exp(home_advantage)))
    ax = max(0.3, min(4.5, a["attack"]*h["defense"]*lpt))
    probs = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson.pmf(i, hx) * poisson.pmf(j, ax)
            if i<=1 and j<=1:
                if i==0 and j==0: p *= (1 - hx*ax*rho)
                elif i==0 and j==1: p *= (1 + hx*rho)
                elif i==1 and j==0: p *= (1 + ax*rho)
                elif i==1 and j==1: p *= (1 - rho)
            probs[i][j] = max(0, p)
    total = probs.sum()
    if total<=0:
        return {"home_win":33.3,"draw":33.3,"away_win":33.3,"home_xg":round(hx,2),
                "away_xg":round(ax,2),"top_scorelines":[],"btts":50.0,
                "over15":50.0,"over25":50.0,"over35":50.0,"top_cs":"1-0",
                "home_strength":h,"away_strength":a}
    probs /= total
    home_win = float(np.tril(probs,-1).sum())*100
    draw = float(np.trace(probs))*100
    away_win = float(np.triu(probs,1).sum())*100
    btts = float(probs[1:,1:].sum())*100
    over25 = sum(probs[i][j] for i in range(max_goals) for j in range(max_goals) if i+j>=3)*100
    over15 = sum(probs[i][j] for i in range(max_goals) for j in range(max_goals) if i+j>=2)*100
    over35 = sum(probs[i][j] for i in range(max_goals) for j in range(max_goals) if i+j>=4)*100
    scores = [(f"{i}-{j}", round(float(probs[i][j])*100,2))
              for i in range(max_goals) for j in range(max_goals)]
    scores.sort(key=lambda x: x[1], reverse=True)
    return {"home_win":round(home_win,1),"draw":round(draw,1),"away_win":round(away_win,1),
            "home_xg":round(hx,2),"away_xg":round(ax,2),"btts":round(btts,1),
            "over15":round(over15,1),"over25":round(over25,1),"over35":round(over35,1),
            "top_scorelines":scores[:5],"top_cs":scores[0][0] if scores else "1-0",
            "home_strength":h,"away_strength":a}

def compute_handicap(p):
    hxg = p["dc"]["home_xg"]; axg = p["dc"]["away_xg"]
    diff = hxg - axg
    hw = p["dc"]["home_win"]; aw = p["dc"]["away_win"]
    if diff >= 1.5:
        return {"pick":"Home -1","odds":1.85,"conf":min(85,int(hw*0.95)),
                "reason":f"Home xG +{diff:.2f}"}
    elif diff >= 0.75:
        return {"pick":"Home -0.5","odds":1.70,"conf":min(80,int(hw*0.90)),
                "reason":"Home dominant by xG"}
    elif diff <= -1.5:
        return {"pick":"Away -1","odds":2.05,"conf":min(85,int(aw*0.95)),
                "reason":f"Away xG +{abs(diff):.2f}"}
    elif diff <= -0.75:
        return {"pick":"Away -0.5","odds":1.90,"conf":min(80,int(aw*0.90)),
                "reason":"Away dominant by xG"}
    elif diff > 0:
        return {"pick":"Home +0.5","odds":1.45,"conf":min(75,int((hw+50)*0.85)),
                "reason":"Close match, home edge"}
    elif diff < 0:
        return {"pick":"Away +0.5","odds":1.50,"conf":min(75,int((aw+50)*0.85)),
                "reason":"Close match, away edge"}
    else:
        return {"pick":"Draw No Bet — Home","odds":1.60,"conf":65,
                "reason":"Neutral xG"}

def predict_match(data):
    home = data.get("home","Home"); away = data.get("away","Away")
    league_code = data.get("country","E0")
    if league_code not in LEAGUE_AVG_GOALS: league_code = "E0"
    dc = dixon_coles_predict(home, away, league_code)
    hk = f"{home}_vs_{away}"; hr = f"{away}_vs_{home}"
    h2h = H2H_CACHE.get(hk,[]) + H2H_CACHE.get(hr,[])
    hw = len([g for g in h2h if (g["home"]==home and g["result"]=="H") or (g["away"]==home and g["result"]=="A")])
    aw = len([g for g in h2h if (g["home"]==away and g["result"]=="H") or (g["away"]==away and g["result"]=="A")])
    hd = len([g for g in h2h if g["result"]=="D"])
    hb = len([g for g in h2h if g["btts"]==1])
    h_avg = (sum(g["total"] for g in h2h)/len(h2h)) if h2h else 0
    dh, dd, da = dc["home_win"], dc["draw"], dc["away_win"]
    if h2h and len(h2h)>=3:
        w = 0.20
        dh = dh*(1-w) + (hw/len(h2h)*100)*w
        dd = dd*(1-w) + (hd/len(h2h)*100)*w
        da = da*(1-w) + (aw/len(h2h)*100)*w
    tot = dh+dd+da
    if tot>0: dh,dd,da = dh/tot*100, dd/tot*100, da/tot*100
    p1,pX,p2 = round(dh,1), round(dd,1), round(da,1)
    p1X,pX2,p12 = round(p1+pX,1), round(pX+p2,1), round(p1+p2,1)
    pBTTS_y = round(dc["btts"],1); pBTTS_n = round(100-pBTTS_y,1)
    pO15,pO25,pO35 = round(dc["over15"],1), round(dc["over25"],1), round(dc["over35"],1)
    pU15,pU25,pU35 = round(100-pO15,1), round(100-pO25,1), round(100-pO35,1)
    mt = {"1":p1,"X":pX,"2":p2,"1X":p1X,"X2":pX2,"12":p12,
          "BTTS Yes":pBTTS_y,"BTTS No":pBTTS_n,
          "Over 1.5":pO15,"Over 2.5":pO25,"Over 3.5":pO35,
          "Under 1.5":pU15,"Under 2.5":pU25,"Under 3.5":pU35}
    oh = float(data.get("odds_h",0) or 0) or round(100/max(p1,5),2)
    od = float(data.get("odds_d",0) or 0) or round(100/max(pX,5),2)
    oa = float(data.get("odds_a",0) or 0) or round(100/max(p2,5),2)
    ob_y = float(data.get("odds_btts",0) or 0) or round(100/max(pBTTS_y,5),2)
    ob_n = round(100/max(pBTTS_n,5),2)
    oo25 = float(data.get("odds_over25",0) or 0) or round(100/max(pO25,5),2)
    ou25 = round(100/max(pU25,5),2)
    o1X = round(100/max(p1X,5),2); oX2 = round(100/max(pX2,5),2); o12 = round(100/max(p12,5),2)
    oo15 = round(100/max(pO15,5),2); oo35 = round(100/max(pO35,5),2)
    ou15 = round(100/max(pU15,5),2); ou35 = round(100/max(pU35,5),2)
    cands = []
    def add(m, pick, prob, odds, reason):
        if prob<8 or prob>95 or not odds or odds<=1.01: return
        implied = 100.0/odds; edge = round(prob-implied,2)
        cands.append({"market":m,"pick":pick,"prob":round(prob,1),
                      "conf":round(prob,1),"odds":round(odds,2),"edge":edge,"reason":reason})
    add("1X2", f"{home} Win (1)", p1, oh, f"{home} win {p1}%")
    add("1X2", "Draw (X)", pX, od, f"Draw {pX}%")
    add("1X2", f"{away} Win (2)", p2, oa, f"{away} win {p2}%")
    add("DC", f"{home} or Draw (1X)", p1X, o1X, f"1X {p1X}%")
    add("DC", f"Draw or {away} (X2)", pX2, oX2, f"X2 {pX2}%")
    add("DC", f"{home} or {away} (12)", p12, o12, f"12 {p12}%")
    add("BTTS", "BTTS Yes", pBTTS_y, ob_y, f"BTTS Y {pBTTS_y}%")
    add("BTTS", "BTTS No", pBTTS_n, ob_n, f"BTTS N {pBTTS_n}%")
    add("O/U", "Over 1.5 Goals", pO15, oo15, f"O1.5 {pO15}%")
    add("O/U", "Over 2.5 Goals", pO25, oo25, f"O2.5 {pO25}%")
    add("O/U", "Over 3.5 Goals", pO35, oo35, f"O3.5 {pO35}%")
    add("O/U", "Under 1.5 Goals", pU15, ou15, f"U1.5 {pU15}%")
    add("O/U", "Under 2.5 Goals", pU25, ou25, f"U2.5 {pU25}%")
    add("O/U", "Under 3.5 Goals", pU35, ou35, f"U3.5 {pU35}%")
    seen = set(); uniq = []
    for c in cands:
        if c["pick"] not in seen: seen.add(c["pick"]); uniq.append(c)
    cands = uniq; cands.sort(key=lambda x: x["conf"], reverse=True)
    safe_pool = [c for c in cands if c["odds"]>=1.15] or cands
    best = max(safe_pool, key=lambda x: (x["conf"], x["edge"]))
    value_pool = sorted([c for c in cands if c["edge"]>2 and c["odds"]>=1.30],
                        key=lambda x: x["edge"], reverse=True)[:3]
    hf = "".join(HISTORICAL_STATS.get(home,{}).get("form",[])[:5]) or "N/A"
    af = "".join(HISTORICAL_STATS.get(away,{}).get("form",[])[:5]) or "N/A"
    h2h_str = "No H2H data"
    if h2h:
        h2h_str = (f"H2H {len(h2h)}: {home} {hw}W {hd}D {aw}W | BTTS {hb}/{len(h2h)} | "
                   f"Avg {h_avg:.1f} goals")
    expl = best["reason"]
    if value_pool: expl += f"\n💎 VALUE: {value_pool[0]['pick']} @ {value_pool[0]['odds']} (+{value_pool[0]['edge']}%)"
    return {"best_market":best["market"],"best_pick":best["pick"],"odds":float(best["odds"]),
            "confidence":best["conf"],"edge":best.get("edge",0),"explanation":expl,
            "verdict":f"{best['market']} — {best['pick']} @ {best['odds']} ({best['conf']}%)",
            "all_markets":cands,"top_markets":cands[:8],"value_bets":value_pool,
            "market_table":mt,"h2h":h2h_str,
            "form":f"Form: {home} [{hf}] | {away} [{af}]",
            "standings":f"xG: {home} {dc['home_xg']} — {away} {dc['away_xg']}",
            "live_odds_source":data.get("source","Model"),
            "winnings_1000":calc(best["odds"],1000),"dc":dc,
            "disclaimer":"\n18+ Bet responsibly."}

def stake_advice(conf, bankroll=10000.0):
    if conf>=90: pct=5.0
    elif conf>=80: pct=4.0
    elif conf>=70: pct=3.0
    elif conf>=60: pct=2.0
    else: pct=1.0
    return {"percent":pct,"amount":round(bankroll*pct/100,2)}

# ── TEAM STATS + INTERACTIVE ──
def find_team_in_brain(team_name):
    if not team_name: return None, None
    t = team_name.strip().lower()
    for k, v in HISTORICAL_STATS.items():
        if k.lower() == t: return k, v
    for k, v in HISTORICAL_STATS.items():
        if t in k.lower(): return k, v
    for k, v in HISTORICAL_STATS.items():
        if any(w == t for w in k.lower().split()): return k, v
    return None, None

def handle_team_stats(chat_id, team_name, user=None):
    key, stats = find_team_in_brain(team_name)
    if not stats:
        send_message(chat_id, (
            f"⚠️ *Team not found:* `{team_name}`\n\n"
            f"My historical brain covers teams from:\n"
            f"• Premier League, La Liga, Serie A, Bundesliga, Ligue 1\n"
            f"• Championship, Eredivisie, Primeira, Süper Lig, Scottish\n"
            f"• And more European leagues.\n\n"
            f"💡 Try: `/stats Arsenal`, `/stats Barcelona`, `/stats Real Madrid`"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
        return
    games = max(stats["games"], 1)
    wins = stats["wins"]; draws = stats["draws"]; losses = stats["losses"]
    scored = stats["scored"]; conceded = stats["conceded"]
    avg_scored = scored / games; avg_conceded = conceded / games
    win_rate = round(wins / games * 100, 1)
    btts_rate = round(stats["btts"] / games * 100, 1)
    over15_rate = round(stats["over15"] / games * 100, 1)
    over25_rate = round(stats["over25"] / games * 100, 1)
    over35_rate = round(stats["over35"] / games * 100, 1)
    clean_rate = round(stats["clean"] / games * 100, 1)
    fail_score_rate = round(stats["failed_score"] / games * 100, 1)
    form = "".join(stats.get("form", [])[:5]) or "N/A"
    form_display = "".join({"W":"✅","D":"➖","L":"❌"}.get(c,"·") for c in form)
    league_map = {"E0":"Premier League","E1":"Championship","E2":"League One",
        "E3":"League Two","SP1":"La Liga","SP2":"Segunda División",
        "D1":"Bundesliga","D2":"2. Bundesliga","I1":"Serie A","I2":"Serie B",
        "F1":"Ligue 1","F2":"Ligue 2","N1":"Eredivisie","B1":"Belgian Pro League",
        "P1":"Primeira Liga","T1":"Süper Lig","G1":"Super League Greece",
        "SC0":"Scottish Premiership"}
    league_name = league_map.get(stats.get("league",""), stats.get("league","—"))
    msg = (
        f"📊 *{key}* — Team Statistics\n"
        f"🏆 {league_name} · Based on last {games} matches\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏅 *Record*\n"
        f"   ✅ {wins}W  ➖ {draws}D  ❌ {losses}L\n"
        f"   📈 Win rate: *{win_rate}%*\n"
        f"   🎯 Form (last 5): {form_display}  ({form})\n\n"
        f"⚽ *Goals*\n"
        f"   🥅 Scored: {scored} ({avg_scored:.2f}/game)\n"
        f"   🛡 Conceded: {conceded} ({avg_conceded:.2f}/game)\n"
        f"   📊 Goal diff: {scored - conceded:+d}\n\n"
        f"📈 *Goals Market*\n"
        f"   Over 1.5: *{over15_rate}%*\n"
        f"   Over 2.5: *{over25_rate}%*\n"
        f"   Over 3.5: *{over35_rate}%*\n\n"
        f"🎯 *Other Rates*\n"
        f"   BTTS: *{btts_rate}%*\n"
        f"   Clean sheets: {clean_rate}%\n"
        f"   Failed to score: {fail_score_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Tips: {'BTTS likely' if btts_rate >= 60 else 'Low-scoring possible' if btts_rate <= 35 else 'Balanced'} · "
        f"{'High-scoring team' if over25_rate >= 65 else 'Defensive side' if over25_rate <= 40 else 'Moderate goals'}"
    )
    send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")

def handle_h2h_callback(chat_id, home, away):
    hk = f"{home}_vs_{away}"; hr = f"{away}_vs_{home}"
    games = H2H_CACHE.get(hk, []) + H2H_CACHE.get(hr, [])
    if not games:
        send_message(chat_id, (
            f"📈 *Head-to-Head*\n\n*{home}* vs *{away}*\n\n"
            f"No direct H2H history in my brain for these two teams.\n\n"
            f"💡 This can happen when teams have never met in loaded leagues.\n\n"
            f"The bot still uses form + xG for its prediction."
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
        return
    home_wins = 0; away_wins = 0; draws = 0
    for g in games:
        if g["home"] == home:
            if g["result"] == "H": home_wins += 1
            elif g["result"] == "A": away_wins += 1
            else: draws += 1
        else:
            if g["result"] == "H": away_wins += 1
            elif g["result"] == "A": home_wins += 1
            else: draws += 1
    btts_count = sum(1 for g in games if g["btts"])
    over25_count = sum(1 for g in games if g["total"] > 2)
    total_goals = sum(g["total"] for g in games)
    n = len(games)
    avg_goals = total_goals / n if n else 0
    btts_rate = round(btts_count / n * 100, 1) if n else 0
    over25_rate = round(over25_count / n * 100, 1) if n else 0
    recent_lines = []
    for g in games[-5:]:
        recent_lines.append(f"   {g['home'][:18]} {g['fthg']}-{g['ftag']} {g['away'][:18]}")
    recent_block = "\n".join(recent_lines) if recent_lines else "   No recent matches"
    msg = (
        f"📈 *Head-to-Head Record*\n*{home}* vs *{away}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏅 *Overall ({n} matches)*\n"
        f"   {home}: *{home_wins}W*\n"
        f"   Draws: *{draws}*\n"
        f"   {away}: *{away_wins}W*\n\n"
        f"⚽ *Goals*\n"
        f"   Avg per match: {avg_goals:.2f}\n"
        f"   Over 2.5 rate: *{over25_rate}%*\n"
        f"   BTTS rate: *{btts_rate}%*\n\n"
        f"📅 *Last 5 meetings*\n{recent_block}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {'Tight contest, expect goals' if over25_rate >= 60 else 'Low-scoring meetings' if over25_rate <= 40 else 'Balanced H2H'}"
    )
    send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")

def handle_form_callback(chat_id, home, away):
    def block(name):
        key, stats = find_team_in_brain(name)
        if not stats: return f"*{name}*\n   No historical data\n"
        form = "".join(stats.get("form", [])[:5]) or "N/A"
        form_disp = "".join({"W":"✅","D":"➖","L":"❌"}.get(c,"·") for c in form)
        g = max(stats["games"], 1)
        avg_sc = stats["scored"] / g; avg_cd = stats["conceded"] / g
        return (f"*{key}*\n"
                f"   Form: {form_disp}  ({form})\n"
                f"   Record: {stats['wins']}W-{stats['draws']}D-{stats['losses']}L\n"
                f"   Goals: {avg_sc:.2f} scored / {avg_cd:.2f} conceded\n")
    msg = (
        f"📊 *Current Form*\n*{home}* vs *{away}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏠 {block(home)}\n"
        f"✈️ {block(away)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ = Win  ·  ➖ = Draw  ·  ❌ = Loss\n"
        f"(Last 5 matches, most recent on the right)"
    )
    send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")

def handle_odds_callback(chat_id, home, away, model_probs=None):
    live = None
    try:
        om = fetch_the_odds_api(datetime.utcnow())
        live = om.get(f"{home}_vs_{away}") or om.get(f"{away}_vs_{home}")
    except: pass
    if not live:
        send_message(chat_id, (
            f"💰 *Odds Comparison*\n\n*{home}* vs *{away}*\n\n"
            f"No live odds data available right now.\n\n"
            f"💡 Odds are pulled from Bet365, Pinnacle and 20+ bookmakers.\n"
            f"Try again closer to kickoff for the best comparison."
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
        return
    oh = live.get("odds_h", 0) or 0
    od = live.get("odds_d", 0) or 0
    oa = live.get("odds_a", 0) or 0
    ob = live.get("odds_btts", 0) or 0
    oo25 = live.get("odds_over25", 0) or 0
    src = live.get("source", "Bookmaker")
    def impl(o): return round(100.0/o, 1) if o and o > 1.01 else 0
    msg = (f"💰 *Odds Comparison*\n*{home}* vs *{away}*\n"
           f"📡 Source: {src}\n━━━━━━━━━━━━━━━━━━━━━━\n\n")
    if oh: msg += f"🏠 Home Win  @ *{oh}*  (implied {impl(oh)}%)\n"
    if od: msg += f"🤝 Draw      @ *{od}*  (implied {impl(od)}%)\n"
    if oa: msg += f"✈️ Away Win  @ *{oa}*  (implied {impl(oa)}%)\n"
    if ob: msg += f"\n⚽ BTTS Yes  @ *{ob}*  (implied {impl(ob)}%)\n"
    if oo25: msg += f"🥅 Over 2.5  @ *{oo25}*  (implied {impl(oo25)}%)\n"
    if model_probs:
        msg += "\n━━━━━━━━━━━━━━━━━━━━━━\n💎 *Best value:*\n"
        edges = []
        if oh and model_probs.get("1"): edges.append(("Home Win", oh, model_probs["1"]))
        if od and model_probs.get("X"): edges.append(("Draw", od, model_probs["X"]))
        if oa and model_probs.get("2"): edges.append(("Away Win", oa, model_probs["2"]))
        best_edge = None
        for name, odd, prob in edges:
            imp = 100.0 / odd if odd else 0
            e = prob - imp
            if best_edge is None or e > best_edge[2]:
                best_edge = (name, odd, e)
        if best_edge and best_edge[2] > 0:
            msg += f"   • {best_edge[0]} @ {best_edge[1]} (+{best_edge[2]:.1f}% edge)\n"
        else:
            msg += "   No positive edge detected against current prices.\n"
    msg += f"\n💡 Odds shown are the best across 20+ bookmakers."
    send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")

# ── ODDS ──
def fetch_the_odds_api(date_obj):
    global ODDS_CACHE
    if not THE_ODDS_API_KEY: return {}
    if ODDS_CACHE["time"] and (datetime.now()-ODDS_CACHE["time"]).seconds<600 and ODDS_CACHE["data"]:
        return ODDS_CACHE["data"]
    iso = date_obj.strftime("%Y-%m-%d"); om = {}
    for sport in ["soccer_epl","soccer_spain_la_liga","soccer_germany_bundesliga",
                  "soccer_italy_serie_a","soccer_france_ligue_one",
                  "soccer_uefa_champs_league","soccer_china_superleague","soccer_usa_mls"]:
        try:
            r = requests.get(f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                params={"apiKey":THE_ODDS_API_KEY,"regions":"eu,uk",
                        "markets":"h2h,totals,btts","oddsFormat":"decimal",
                        "dateFormat":"iso"}, timeout=15)
            if r.status_code != 200: continue
            for game in r.json():
                try:
                    h = game["home_team"]; a = game["away_team"]
                    if game["commence_time"][:10] != iso: continue
                    bh=bd=ba=bo25=obb=0
                    for bk in game.get("bookmakers",[])[:6]:
                        for m in bk.get("markets",[]):
                            if m["key"]=="h2h":
                                for o in m["outcomes"]:
                                    if o["name"]==h: bh=max(bh,o["price"])
                                    elif o["name"]==a: ba=max(ba,o["price"])
                                    elif o["name"]=="Draw": bd=max(bd,o["price"])
                            elif m["key"]=="totals":
                                for o in m["outcomes"]:
                                    if o["name"]=="Over" and o.get("point")==2.5:
                                        bo25=max(bo25,o["price"])
                            elif m["key"]=="btts":
                                for o in m["outcomes"]:
                                    if o["name"]=="Yes": obb=max(obb,o["price"])
                    om[f"{h}_vs_{a}"] = {"home":h,"away":a,"league":game.get("sport_title",""),
                        "odds_h":bh or 0,"odds_d":bd or 0,"odds_a":ba or 0,
                        "odds_over25":bo25 or 0,"odds_btts":obb or 0,
                        "source":"LIVE (Bet365/Pinnacle)"}
                except: continue
        except: continue
    ODDS_CACHE = {"time":datetime.now(),"data":om}; return om

def enrich_with_odds(fixtures, date_obj):
    om = fetch_the_odds_api(date_obj)
    for f in fixtures:
        k = f"{f['home']}_vs_{f['away']}"; rv = f"{f['away']}_vs_{f['home']}"
        live = om.get(k) or om.get(rv)
        if live:
            f.update({"odds_h":live["odds_h"] or f.get("odds_h",0),
                      "odds_d":live["odds_d"] or f.get("odds_d",0),
                      "odds_a":live["odds_a"] or f.get("odds_a",0),
                      "odds_over25":live["odds_over25"] or f.get("odds_over25",0),
                      "odds_btts":live["odds_btts"] or f.get("odds_btts",0),
                      "source":live["source"]})
        else:
            for kk in ["odds_h","odds_d","odds_a","odds_over25","odds_btts"]:
                f.setdefault(kk, 0)
            f.setdefault("source","Model")
    return fixtures

# ── FETCHER IMPORTS ──
from fetcher import (fetch_today_fixtures, fetch_by_region, fetch_espn,
                     fetch_thesportsdb, fetch_openfootball_national, deduplicate)

REGION_TO_FETCHER_KEY = {"europe":"european","asia":"asian","america":"american",
                          "national":"national","africa":"african"}

def fetch_region_fixtures(region_key, days_ahead=0, limit=15):
    fk = REGION_TO_FETCHER_KEY.get(region_key, region_key)
    target = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=days_ahead)).date()
    try: fixtures = fetch_by_region(target, fk, limit=limit)
    except: fixtures = []
    if not fixtures and days_ahead==0:
        for i in range(1, 8):
            t2 = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=i)).date()
            try: fixtures = fetch_by_region(t2, fk, limit=limit)
            except: fixtures = []
            if fixtures: break
    return enrich_with_odds(fixtures, target)

def fetch_all_fixtures(limit=15, preferred=None):
    pool = []
    keys = preferred if preferred else list(REGIONS.keys())
    per = max(3, limit // max(len(keys),1) + 1)
    for k in keys: pool.extend(fetch_region_fixtures(k, limit=per))
    seen = set(); uniq = []
    for f in pool:
        key = f"{f['home']}-{f['away']}"
        if key in seen: continue
        seen.add(key); uniq.append(f)
    return uniq[:limit]

def fetch_real_fixtures(days_ahead=0, limit=10, region=None):
    target = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=days_ahead)).date()
    if region: fixtures = fetch_by_region(target, region, limit=limit)
    else: fixtures = fetch_today_fixtures(target, limit=limit)
    if not fixtures and days_ahead==0:
        for i in range(1, 8):
            t2 = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=i)).date()
            if region: fixtures = fetch_by_region(t2, region, limit=limit)
            else: fixtures = fetch_today_fixtures(t2, limit=limit)
            if fixtures: break
    return enrich_with_odds(fixtures, target)

# ── SPORTYBET ──
def sb_fetch_events(timeline_hours=48, page_size=100):
    global SB_EVENTS_CACHE
    if (SB_EVENTS_CACHE["time"] and
        (datetime.now()-SB_EVENTS_CACHE["time"]).seconds<300 and SB_EVENTS_CACHE["data"]):
        return SB_EVENTS_CACHE["data"]
    try:
        r = requests.get("https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents",
            params={"sportId":"sr:sport:1","marketId":"1,18,10,29",
                    "pageSize":min(page_size,100),"pageNum":1,
                    "timeline":min(timeline_hours,720),
                    "_t":int(time.time()*1000)}, headers=SB_HEADERS, timeout=15)
        if r.status_code != 200: return []
        tournaments = r.json().get("data",{}).get("tournaments",[]) or []
        events = []
        for t in tournaments:
            lg = t.get("name","")
            for ev in t.get("events",[]) or []:
                h = ev.get("homeTeamName",""); a = ev.get("awayTeamName","")
                if not h or not a or is_youth(h) or is_youth(a): continue
                oh=od=oa=oo25=ob=0
                for m in ev.get("markets",[]) or []:
                    mid = str(m.get("id",""))
                    if mid=="1":
                        for o in m.get("outcomes",[]) or []:
                            oid = str(o.get("id",""))
                            try: price=float(o.get("odds",0) or 0)
                            except: price=0
                            if oid=="1": oh=price
                            elif oid=="2": od=price
                            elif oid=="3": oa=price
                    elif mid=="18":
                        for o in m.get("outcomes",[]) or []:
                            if o.get("specifier")=="total=2.5" and str(o.get("id"))=="12":
                                try: oo25=float(o.get("odds",0) or 0)
                                except: pass
                    elif mid=="29":
                        for o in m.get("outcomes",[]) or []:
                            if str(o.get("id"))=="1":
                                try: ob=float(o.get("odds",0) or 0)
                                except: pass
                km = ev.get("estimateStartTime",0) or 0
                ko = datetime.utcfromtimestamp(km/1000) if km else datetime.utcnow()
                wat = ko + timedelta(hours=1)
                events.append({"eventId":ev.get("eventId",""),"home":h,"away":a,
                    "league":lg,"date":wat.strftime("%Y-%m-%d"),
                    "time":wat.strftime("%H:%M"),"country":"E0",
                    "odds_h":oh,"odds_d":od,"odds_a":oa,
                    "odds_over25":oo25,"odds_btts":ob,"source":"SportyBet LIVE"})
        SB_EVENTS_CACHE = {"time":datetime.now(),"data":events}
        return events
    except Exception as e:
        print(f"[SportyBet] {e}"); return []

def sb_book_bet(selections):
    try:
        r = requests.post("https://www.sportybet.com/api/ng/orders/share",
            json={"selections":selections}, headers=SB_HEADERS, timeout=20)
        if r.status_code != 200: return None
        d = r.json()
        if d.get("bizCode") != 10000: return None
        dd = d.get("data",{})
        return {"shareCode":dd.get("shareCode",""),"shareURL":dd.get("shareURL","")}
    except Exception as e:
        print(f"[SB book] {e}"); return None

def market_to_sb_selection(pick_data, event_id):
    p = pick_data.get("pick","").lower()
    if "home win" in p or "(1)" in p: return {"eventId":event_id,"marketId":"1","outcomeId":"1"}
    if "draw (x)" in p or p=="draw": return {"eventId":event_id,"marketId":"1","outcomeId":"2"}
    if "away win" in p or "(2)" in p: return {"eventId":event_id,"marketId":"1","outcomeId":"3"}
    if "(1x)" in p: return {"eventId":event_id,"marketId":"10","outcomeId":"1"}
    if "(12)" in p: return {"eventId":event_id,"marketId":"10","outcomeId":"2"}
    if "(x2)" in p: return {"eventId":event_id,"marketId":"10","outcomeId":"3"}
    if "btts yes" in p: return {"eventId":event_id,"marketId":"29","outcomeId":"1"}
    if "btts no" in p: return {"eventId":event_id,"marketId":"29","outcomeId":"2"}
    for line in ["1.5","2.5","3.5"]:
        if f"over {line}" in p:
            return {"eventId":event_id,"marketId":"18","outcomeId":"12","specifier":f"total={line}"}
        if f"under {line}" in p:
            return {"eventId":event_id,"marketId":"18","outcomeId":"13","specifier":f"total={line}"}
    return None

def sportybet_load_url(c):
    return f"https://www.sportybet.com/ng/#/share/booking/{c}" if c else "https://www.sportybet.com/ng/sport/football"

def football_com_load_url(c):
    return f"https://www.football.com/en-ng/sports#/booking/{c}" if c else "https://www.football.com/en-ng/sports"

def convert_sb_to_football(code):
    if not code: return None
    try:
        r = requests.post("https://betrelay.com.ng/api/convert",
            json={"from":"sportybet","to":"football","code":code}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            c = d.get("code") or d.get("converted_code") or d.get("result")
            if c: return c
    except: pass
    return None

# ── ACCUMULATOR ──
def safety_score(fixture, pred):
    score = pred.get("confidence",0) + pred.get("edge",0)*0.5
    odds = pred.get("odds",2)
    if 1.5<=odds<=2.5: score += 6
    elif 1.3<=odds<1.5: score += 3
    elif odds>3.5: score -= 8
    lg = fixture.get("league","").lower()
    if any(k in lg for k in TOP_LEAGUES): score += 8
    return score

def build_accumulator(fixtures, target_matches=20, min_odds=1.20, max_odds=3.50):
    scored = []
    for f in fixtures:
        try:
            pred = predict_match(f)
            best = pred["all_markets"][0] if pred["all_markets"] else None
            if not best: continue
            if best["odds"]<min_odds or best["odds"]>max_odds:
                alt = next((m for m in pred["all_markets"]
                            if min_odds<=m["odds"]<=max_odds and m["conf"]>=55), None)
                if not alt: continue
                best = alt
            sc = safety_score(f, {**pred, **best, "confidence":best["conf"]})
            scored.append({"fixture":f,"pred":pred,"pick":best,"safety":sc})
        except: continue
    scored.sort(key=lambda x: x["safety"], reverse=True)
    selected = []; lg_count = defaultdict(int); used = set()
    for item in scored:
        if len(selected) >= target_matches: break
        f = item["fixture"]; lg = f.get("league",""); h = f["home"]; a = f["away"]
        if h in used or a in used: continue
        if lg_count[lg] >= 3: continue
        selected.append(item); lg_count[lg] += 1; used.add(h); used.add(a)
    return selected

# ── CONVERSION CTA ──
def build_upgrade_cta(user, hidden_count=8, context="daily", region_label=None, locked_markets=None):
    rtxt = f" in {region_label}" if region_label else ""
    market_lock = ""
    if locked_markets:
        market_lock = "\n🔒 *LOCKED VIP MARKETS:*\n" + "\n".join(f"   • {m}" for m in locked_markets) + "\n"
    return (
        f"🔒 *{hidden_count} MORE WINNING PICKS{rtxt.upper()} ARE LOCKED*\n\n"
        f"💎 VIP members are already profiting from these picks today.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *What VIP members are seeing RIGHT NOW:*\n"
        f"✅ All 10 predictions/day (you get 2)\n"
        f"✅ 🎯 Correct Score predictions\n"
        f"✅ ⚖️ Handicap picks\n"
        f"✅ 🎫 20-match Betslip with real booking codes\n"
        f"✅ 🌏 Asian / 🇺🇸 American / 🌍 African leagues\n"
        f"✅ 🚀 N1M Challenge — ₦1,000 → ₦1,000,000\n"
        f"✅ Value-bet alerts before kickoff\n"
        f"{market_lock}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 *JOIN 5,000+ WINNING VIP MEMBERS*\n\n"
        f"VIP users win *3x more* than free users.\n"
        f"Don't leave money on the table.\n\n"
        f"⏰ *First week for ₦1,600 (20% OFF)*\n\n"
        f"📢 *Also join our channel:* {CHANNEL_LINK}"
    )

def upgrade_buttons(uid):
    return {"inline_keyboard": [
        [{"text":"💎 Weekly VIP — ₦2,000 (Best Start)",
          "url": f"{RENDER_URL}/subscribe?uid={uid}"}],
        [{"text":"💰 Monthly VIP — ₦5,000 (Save ₦3,000)",
          "url": f"{RENDER_URL}/subscribe?uid={uid}"}],
        [{"text":"⚡ 24h Trial — ₦500",
          "url": f"{RENDER_URL}/subscribe?uid={uid}"}],
        [{"text":f"📢 Join {CHANNEL_NAME}","url":CHANNEL_LINK}],
        get_footer_menu_button(),
    ]}

def send_upgrade_cta(chat_id, user, hidden_count=8, context="daily",
                     region_label=None, locked_markets=None):
    text = build_upgrade_cta(user, hidden_count, context, region_label, locked_markets)
    send_message(chat_id, text, reply_markup=upgrade_buttons(user.user_id), parse_mode="Markdown")

# ── TELEGRAM ──
app = FastAPI()

def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000: text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup: payload["reply_markup"] = reply_markup
        if parse_mode: payload["parse_mode"] = parse_mode
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200: return r.json()
        print(f"[send] {r.status_code}: {r.text[:200]}")
        if parse_mode:
            payload.pop("parse_mode", None)
            payload["text"] = text.replace("*","").replace("_"," ").replace("`","")
            r2 = requests.post(url, json=payload, timeout=15)
            if r2.status_code == 200: return r2.json()
        return r.json() if r.content else None
    except Exception as e:
        print(f"[send] {e}"); return None

def set_bot_menu():
    cmds = [
        {"command":"start","description":"🏠 Main menu"},
        {"command":"menu","description":"📱 Open menu"},
        {"command":"remember","description":"🧠 What I remember about you"},
        {"command":"preferences","description":"⚙️ Set preferences"},
        {"command":"today","description":"⚽ Today's fixtures"},
        {"command":"accumulator","description":"🎫 20-match accumulator"},
        {"command":"million","description":"🚀 N1M challenge"},
        {"command":"stats","description":"📊 Your stats or /stats Arsenal"},
        {"command":"europeanleagues","description":"🇪🇺 European leagues"},
        {"command":"asianleagues","description":"🌏 Asian leagues"},
        {"command":"americanleagues","description":"🇺🇸 American leagues"},
        {"command":"africanleagues","description":"🌍 African leagues"},
        {"command":"national","description":"🏆 National teams"},
        {"command":"upgrade","description":"💎 Upgrade to VIP"},
        {"command":"help","description":"❓ Help"},
    ]
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
                      json={"commands":cmds}, timeout=10)
    except: pass

# ── PREFERENCES ──
def get_preference_keyboard(user):
    prefs = set(get_user_prefs(user))
    rows = []; row = []
    for key in REGION_KEYS:
        info = REGIONS[key]; check = "✅" if key in prefs else "⚪"
        row.append({"text":f"{check} {info['label']}","callback_data":f"pref_toggle_{key}"})
        if len(row)==2: rows.append(row); row=[]
    if row: rows.append(row)
    n = len(prefs)
    confirm = "✅ Confirm (Pick up to 3)" if n==0 else f"✅ Confirm ({n}/3 chosen)"
    rows.append([{"text":confirm,"callback_data":"pref_confirm"}])
    rows.append([{"text":"🔄 Reset","callback_data":"pref_reset"}])
    return {"inline_keyboard": rows}

def get_preferences_intro_text(user):
    prefs = get_user_prefs(user)
    if prefs:
        labs = ", ".join(REGIONS[k]["label"] for k in prefs)
        tail = f"\n\n*Currently selected:* {labs}"
    else: tail = "\n\n_You haven't chosen yet._"
    return (f"⚙️ *SELECT YOUR BETTING PREFERENCES*\n\n"
            f"Choose up to *3 regions* you want predictions from.\n"
            f"Your daily picks and accumulators will be personalized.{tail}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n👇 *Tap to select / deselect regions*")

def handle_preferences_menu(chat_id, user, db, edit_msg_id=None):
    text = get_preferences_intro_text(user); kb = get_preference_keyboard(user)
    if edit_msg_id:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                json={"chat_id":chat_id,"message_id":edit_msg_id,"text":text,
                      "reply_markup":kb,"parse_mode":"Markdown"}, timeout=15); return
        except: pass
    send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

def handle_pref_toggle(chat_id, user, db, region_key, msg_id=None):
    if region_key not in REGIONS: return
    prefs = get_user_prefs(user)
    if region_key in prefs: prefs.remove(region_key)
    else:
        if len(prefs) >= MAX_PREFERENCES:
            send_message(chat_id, f"⚠️ Max {MAX_PREFERENCES} preferences. Deselect one first.")
            handle_preferences_menu(chat_id, user, db, edit_msg_id=msg_id); return
        prefs.append(region_key)
    user.preferred_regions = ",".join(prefs); db.commit()
    text = get_preferences_intro_text(user); kb = get_preference_keyboard(user)
    if msg_id:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                json={"chat_id":chat_id,"message_id":msg_id,"text":text,
                      "reply_markup":kb,"parse_mode":"Markdown"}, timeout=15); return
        except: pass
    send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

def handle_pref_reset(chat_id, user, db, msg_id=None):
    user.preferred_regions = ""; user.preferences_set = False; db.commit()
    text = get_preferences_intro_text(user); kb = get_preference_keyboard(user)
    if msg_id:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                json={"chat_id":chat_id,"message_id":msg_id,"text":text,
                      "reply_markup":kb,"parse_mode":"Markdown"}, timeout=15); return
        except: pass
    send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

def handle_pref_confirm(chat_id, user, db, msg_id=None):
    prefs = get_user_prefs(user)
    if not prefs:
        send_message(chat_id, "⚠️ Please select at least 1 region."); return
    user.preferences_set = True; db.commit()
    labs = ", ".join(REGIONS[k]["label"] for k in prefs)
    conf = (f"✅ *PREFERENCES SAVED!*\n\nYour betting preferences:\n{labs}\n\n"
            f"🎯 Your daily picks and accumulators will now be personalized.\n"
            f"📬 You'll get a daily push at *09:00 WAT* with picks from your regions.\n\n"
            f"📢 *Join our channel:* {CHANNEL_LINK}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n👇 *Now let's find you some winners*")
    if msg_id:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                json={"chat_id":chat_id,"message_id":msg_id,"text":conf,
                      "reply_markup":get_inline_menu(is_admin(user.user_id)),
                      "parse_mode":"Markdown"}, timeout=15); return
        except: pass
    send_message(chat_id, conf, reply_markup=get_inline_menu(is_admin(user.user_id)),
                 parse_mode="Markdown")

# ── MAIN MENU ──
def send_main_menu(chat_id, user, db):
    admin = is_admin(user.user_id)
    limit = 999 if admin else (10 if user.is_vip else 2)
    tier = "🔐 ADMIN" if admin else ("💎 VIP" if user.is_vip else "🆓 FREE")
    prefs = get_user_prefs(user)
    plabels = " · ".join(REGIONS[k]["emoji"] for k in prefs) if prefs else "Not set"
    if user.is_vip or admin:
        status = f"💎 *VIP ACTIVE* until {user.vip_expiry}"
    else:
        status = (f"🆓 *FREE TIER* — you're missing 8 winning picks today\n"
                  f"💎 *Upgrade to unlock everything* 👇")
    text = (
        f"🏆 *{CHANNEL_NAME.upper()}* — AI Betting Intelligence\n\n"
        f"🧠 Dixon-Coles AI engine · 13 markets\n"
        f"🌍 Africa · Asia · Europe · America · National\n"
        f"📊 Team stats · H2H · Odds compare\n"
        f"🎯 Correct Score + Handicap (VIP)\n"
        f"🎫 20-match Betslip with real booking codes (VIP)\n"
        f"🚀 N1M Challenge — ₦1,000 → ₦1,000,000\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *{user.first_name or user.username or 'Trader'}*\n"
        f"🏅 Tier: {tier}\n"
        f"📊 Daily used: {user.daily_count}/{limit}\n"
        f"🎯 Preferences: {plabels}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{status}\n\n👇 *Tap a button to begin*"
    )
    send_message(chat_id, text, reply_markup=get_inline_menu(admin), parse_mode="Markdown")
    send_message(chat_id, "⚡ Quick access buttons below", reply_markup=get_main_keyboard(admin))

def send_start_message(chat_id, user, db):
    admin = is_admin(user.user_id)
    visits = getattr(user, "total_visits", 0) or 0
    has_history = (
        user.preferences_set or
        (user.total_predictions or 0) > 0 or
        user.is_vip or
        visits >= 2
    )
    if has_history and not admin:
        tier = "💎 VIP" if user.is_vip else "🆓 FREE"
        prefs = get_user_prefs(user)
        pref_labels = " · ".join(REGIONS[k]["label"] for k in prefs) if prefs else "Not set"
        last_seen_txt = "—"
        try:
            if user.last_seen:
                days_ago = (datetime.utcnow() - user.last_seen).days
                if days_ago == 0: last_seen_txt = "Today"
                elif days_ago == 1: last_seen_txt = "Yesterday"
                else: last_seen_txt = f"{days_ago} days ago"
        except Exception: pass
        vip_line = ""
        if user.is_vip and user.vip_expiry:
            vip_line = f"💎 VIP active until *{user.vip_expiry}*\n"
        msg = (
            f"👋 *Welcome back, {user.first_name or user.username or 'champion'}!*\n\n"
            f"I remembered you. 🧠\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏅 Tier: *{tier}*\n"
            f"{vip_line}"
            f"🎯 Preferences: {pref_labels}\n"
            f"📊 Predictions received: *{user.total_predictions or 0}*\n"
            f"🔥 Current streak: *{user.streak or 0}*\n"
            f"👁 Last visit: {last_seen_txt}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 *Channel:* {CHANNEL_NAME} — {CHANNEL_LINK}\n\n"
            f"👇 *Ready to find today's winners?*"
        )
        send_message(chat_id, msg, reply_markup=get_inline_menu(admin), parse_mode="Markdown")
        send_message(chat_id, "⚡ Quick access buttons below", reply_markup=get_main_keyboard(admin))
        return
    if not user.preferences_set and not admin:
        send_message(chat_id, (
            f"🏆 *WELCOME TO {CHANNEL_NAME.upper()}!*\n\n"
            f"You're joining *5,000+ winners* who use AI to dominate the bookies.\n\n"
            f"🧠 Dixon-Coles AI engine · 13 markets\n"
            f"📊 Team stats · H2H · Odds compare\n"
            f"🌍 Africa · Asia · Europe · America · National\n"
            f"🎯 Correct Score + Handicap markets (VIP)\n"
            f"🎫 20-match Betslip with real booking codes (VIP)\n"
            f"🚀 N1M Challenge — ₦1,000 → ₦1,000,000\n\n"
            f"📢 *Follow our channel:* {CHANNEL_LINK}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*First, let's set up your preferences.*\n"
            f"Pick up to *3 regions* you want predictions from."
        ), parse_mode="Markdown")
        time.sleep(0.5)
        handle_preferences_menu(chat_id, user, db)
        return
    send_main_menu(chat_id, user, db)

def handle_remember(chat_id, user, db):
    prefs = get_user_prefs(user)
    pref_labels = " · ".join(REGIONS[k]["label"] for k in prefs) if prefs else "Not set"
    tier = "🔐 ADMIN" if is_admin(user.user_id) else ("💎 VIP" if user.is_vip else "🆓 FREE")
    exp = user.vip_expiry if user.is_vip else "—"
    joined = user.created_at.strftime("%d %b %Y") if user.created_at else "—"
    last = user.last_seen.strftime("%d %b %Y %H:%M") if user.last_seen else "—"
    msg = (
        f"🧠 *What {CHANNEL_NAME} Remembers About You*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: `{user.user_id}`\n"
        f"👤 Name: {user.first_name or user.username or 'Anon'}\n"
        f"📅 Member since: {joined}\n"
        f"👁 Last seen: {last}\n"
        f"📊 Total visits: {getattr(user, 'total_visits', 0) or 0}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏅 Tier: {tier}\n"
        f"💎 VIP until: {exp}\n"
        f"💳 Preferred plan: *{user.preferred_plan or 'Not set'}*\n"
        f"🎯 Preferences: {pref_labels}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Total predictions: {user.total_predictions or 0}\n"
        f"🔥 Current streak: {user.streak or 0} (best: {user.best_streak or 0})\n"
        f"🎁 Referrals: {user.referral_count or 0}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ *Your account is permanently stored.*\n"
        f"Even if you clear your Telegram history or reinstall the app, "
        f"just send /start — I'll remember everything.\n\n"
        f"To reset your preferences: /preferences"
    )
    send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")

# ── REGION HANDLER ──
REGION_LABELS = {
    "europe": ("🇪🇺 *EUROPEAN FIXTURES*","Europe"),
    "asia": ("🌏 *ASIAN FIXTURES*","Asia"),
    "america": ("🇺🇸 *AMERICAN FIXTURES*","America"),
    "africa": ("🌍 *AFRICAN FIXTURES*","Africa"),
    "national": ("🏆 *NATIONAL TEAMS*","National"),
}

def handle_region(chat_id, user, db, region_key, min_fixtures=15):
    header, label = REGION_LABELS.get(region_key, ("FIXTURES","Region"))
    admin = is_admin(user.user_id)
    send_message(chat_id, f"🔎 Scanning {label} fixtures...",
                 reply_markup=get_main_keyboard(admin))
    fixtures = fetch_region_fixtures(region_key, limit=min_fixtures)
    if len(fixtures) < min_fixtures:
        extra = fetch_all_fixtures(limit=min_fixtures*2)
        exist = {f"{f['home']}-{f['away']}" for f in fixtures}
        for ef in extra:
            if f"{ef['home']}-{ef['away']}" not in exist: fixtures.append(ef)
            if len(fixtures) >= min_fixtures: break
    if not (admin or user.is_vip):
        free_fixtures = [f for f in fixtures if is_free_league(f) and not is_premium_league(f)]
        if len(free_fixtures) < 2:
            send_message(chat_id, (
                f"🔒 *{label.upper()} IS VIP-EXCLUSIVE*\n\n"
                f"Free users get: EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL\n\n"
                f"💎 *VIP unlocks:*\n"
                f"✅ All Asian leagues (CSL, J1, K League, Saudi Pro)\n"
                f"✅ All American leagues (MLS, Liga MX, Brasileirão)\n"
                f"✅ All African leagues\n"
                f"✅ 🎯 Correct Score + Handicap markets\n"
                f"✅ 🎫 20-match Betslip with real booking codes\n\n"
                f"⏰ *First week for ₦1,600 (20% OFF)*"
            ), reply_markup=upgrade_buttons(user.user_id), parse_mode="Markdown"); return
        fixtures = free_fixtures
    if not fixtures:
        send_message(chat_id, f"No {label} fixtures available right now.\n{BOT_LINK}",
                     reply_markup=add_footer_button()); return
    fixtures = fixtures[:min_fixtures]
    msg = f"{header}\n📅 {fixtures[0].get('date','Today')}\n\n"
    for i, f in enumerate(fixtures, 1):
        lock = "🔒 " if (is_premium_league(f) and not (admin or user.is_vip)) else ""
        msg += (f"{i}. {lock}*{f['home']} vs {f['away']}*\n"
                f"   🏆 {f.get('league','')}\n"
                f"   🕐 {f.get('time','')} WAT\n\n")
    msg += f"*{len(fixtures)} matches loaded* — tap below"
    kb = {"inline_keyboard": [
        [{"text":f"🧠 Analyze Top 10 {label} Matches",
          "callback_data":f"analyze10_{region_key}"}],
        [{"text":f"✅ Sure 10 {label} Predictions",
          "callback_data":f"sure10_{region_key}"}],
        [{"text":"🎫 20-Match Accumulator (VIP)","callback_data":"build_accumulator"}],
        get_footer_menu_button(),
    ]}
    send_message(chat_id, msg, reply_markup=kb, parse_mode="Markdown")

# ── PREDICTION FORMATTER ──
def format_full_prediction(chat_id, fixture, show_all_markets=True):
    p = predict_match(fixture)
    mt = p.get("market_table", {})
    sa = stake_advice(p["confidence"])
    home = fixture["home"]; away = fixture["away"]
    msg = (
        f"⚽ *{home} vs {away}*\n"
        f"🏆 {fixture.get('league','')} · {fixture.get('time','')} WAT\n\n"
        f"📊 {p['form']}\n"
        f"📈 {p['h2h']}\n\n"
        f"🏆 *SAFEST PICK*\n"
        f"✅ *{p['best_pick']}*\n"
        f"   @ {p['odds']} · {p['confidence']}% conf"
    )
    if p.get("edge", 0) > 0: msg += f" · +{p['edge']}% edge"
    msg += f"\n   💰 Stake: {sa['percent']}% (N{sa['amount']} of N10,000)\n"
    if show_all_markets:
        msg += (
            "\n📋 *ALL MARKET PROBABILITIES*\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏠 Home: {mt.get('1',0):.1f}%  |  🤝 Draw: {mt.get('X',0):.1f}%  |  ✈️ Away: {mt.get('2',0):.1f}%\n"
            f"🎯 1X: {mt.get('1X',0):.1f}%  |  X2: {mt.get('X2',0):.1f}%  |  12: {mt.get('12',0):.1f}%\n"
            f"⚽ BTTS Y: {mt.get('BTTS Yes',0):.1f}%  |  N: {mt.get('BTTS No',0):.1f}%\n"
            f"🥅 O1.5: {mt.get('Over 1.5',0):.1f}%  |  O2.5: {mt.get('Over 2.5',0):.1f}%  |  O3.5: {mt.get('Over 3.5',0):.1f}%\n"
        )
        top_scores = p["dc"].get("top_scorelines", [])[:3]
        if top_scores:
            msg += "\n🎯 *CORRECT SCORE (VIP)*\n"
            for sc, pct in top_scores: msg += f"   {sc}  →  {pct}%\n"
        hcp = compute_handicap(p)
        msg += (f"\n⚖️ *HANDICAP (VIP)*\n"
                f"   ✅ *{hcp['pick']}* @ {hcp['odds']} ({hcp['conf']}%)\n")
    else:
        msg += (
            "\n🔒 *VIP MARKETS LOCKED*\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "   🎯 Correct Score predictions\n"
            "   ⚖️ Handicap picks\n"
            "   🎫 20-match Betslip + real booking codes\n"
            "   📋 Full 13-market probability table\n\n"
            "💎 *Upgrade to unlock:* /upgrade"
        )
    if p.get("value_bets"):
        msg += "\n💎 *VALUE BETS:*\n"
        for v in p["value_bets"][:2]:
            msg += f"   • {v['pick']} @ {v['odds']} (+{v['edge']}% edge)\n"
    h_short = home[:20].replace("|","")
    a_short = away[:20].replace("|","")
    kb = {"inline_keyboard": [
        [
            {"text": "📈 H2H", "callback_data": f"h2h|{h_short}|{a_short}"},
            {"text": "📊 Form", "callback_data": f"frm|{h_short}|{a_short}"},
            {"text": "💰 Odds Compare", "callback_data": f"odd|{h_short}|{a_short}"},
        ],
        get_footer_menu_button(),
    ]}
    send_message(chat_id, msg, reply_markup=kb, parse_mode="Markdown")

# ── ANALYZE TOP 10 ──
def handle_analyze_top10(chat_id, user, db, region_key=None):
    admin = is_admin(user.user_id)
    limit = 999 if admin else (10 if user.is_vip else 2)
    label = REGION_LABELS.get(region_key, ("","All"))[1] if region_key else "All"
    if not admin and user.daily_count >= limit:
        send_message(chat_id, f"🚫 Daily limit {user.daily_count}/{limit}",
                     reply_markup=upgrade_buttons(user.user_id)); return
    if region_key: fixtures = fetch_region_fixtures(region_key, limit=15)
    else: fixtures = fetch_all_fixtures(limit=20, preferred=get_user_prefs(user) or None)
    if not (admin or user.is_vip):
        free_fixtures = [f for f in fixtures if is_free_league(f) and not is_premium_league(f)]
        if len(free_fixtures) < 2:
            send_message(chat_id, (
                f"🔒 *{label.upper()} PICKS ARE VIP-EXCLUSIVE*\n\n"
                f"Free users get EPL, La Liga, Serie A, Bundesliga, Ligue 1.\n\n"
                f"💎 VIP unlocks Asian / American / African leagues, "
                f"Correct Score, Handicap and 20-match Betslip."
            ), reply_markup=upgrade_buttons(user.user_id), parse_mode="Markdown"); return
        fixtures = free_fixtures
    if not fixtures:
        send_message(chat_id, f"No fixtures available.\n{BOT_LINK}",
                     reply_markup=add_footer_button()); return
    ranked = []
    for f in fixtures[:20]:
        try:
            pred = predict_match(f); ranked.append((safety_score(f, pred), f, pred))
        except: continue
    ranked.sort(key=lambda x: x[0], reverse=True); ranked = ranked[:10]
    if not ranked:
        send_message(chat_id, "Couldn't analyze matches.",
                     reply_markup=add_footer_button()); return
    is_vip = user.is_vip or admin
    visible = 10 if is_vip else 2
    hidden = len(ranked) - visible
    send_message(chat_id, f"🧠 *Analyzing Top {len(ranked)} {label} matches...*",
                 parse_mode="Markdown", reply_markup=get_main_keyboard(admin))
    for i, (_, f, _) in enumerate(ranked[:visible], 1):
        send_message(chat_id, f"━━━ *#{i}* of {len(ranked)} ━━━", parse_mode="Markdown")
        format_full_prediction(chat_id, f, show_all_markets=is_vip)
        user.daily_count += 1; db.commit()
        time.sleep(0.6)
    if not is_vip and hidden > 0:
        send_upgrade_cta(chat_id, user, hidden_count=hidden, region_label=label,
                         locked_markets=["Correct Score","Handicap",
                                          "20-match Betslip + booking codes",
                                          "Full 13-market table"])
    else:
        send_message(chat_id, f"✅ All {len(ranked)} analyzed.",
                     reply_markup=add_footer_button())

# ── SURE 10 ──
def handle_sure_10(chat_id, user, db, region_key=None):
    admin = is_admin(user.user_id)
    limit = 999 if admin else (10 if user.is_vip else 2)
    label = REGION_LABELS.get(region_key, ("","All"))[1] if region_key else "Global"
    if not admin and user.daily_count >= limit:
        send_message(chat_id, f"🚫 Daily limit {user.daily_count}/{limit}",
                     reply_markup=upgrade_buttons(user.user_id)); return
    send_message(chat_id, f"🎯 *Building your Sure 10 {label} predictions...*",
                 parse_mode="Markdown", reply_markup=get_main_keyboard(admin))
    if region_key: pool = fetch_region_fixtures(region_key, limit=40)
    else: pool = fetch_all_fixtures(limit=40, preferred=get_user_prefs(user) or None)
    if len(pool) < 10: pool.extend(fetch_all_fixtures(limit=40))
    pool = pool[:60]
    if not (admin or user.is_vip):
        pool = [f for f in pool if is_free_league(f) and not is_premium_league(f)]
    if len(pool) < 5:
        send_message(chat_id, f"Not enough eligible fixtures today.",
                     reply_markup=add_footer_button()); return
    scored = []
    for f in pool:
        try:
            p = predict_match(f)
            safe_picks = [m for m in p["all_markets"]
                          if m["conf"] >= 55 and 1.25 <= m["odds"] <= 3.00]
            if not safe_picks: continue
            best = max(safe_picks, key=lambda m: (m["conf"] + m.get("edge",0)*0.3))
            combined = best["conf"] + best.get("edge",0)*0.5
            scored.append({"fixture":f,"pred":p,"pick":best,"score":combined})
        except: continue
    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = []; lg_count = defaultdict(int); used = set()
    for item in scored:
        if len(selected) >= 10: break
        f = item["fixture"]; lg = f.get("league","")
        if f["home"] in used or f["away"] in used: continue
        if lg_count[lg] >= 2: continue
        selected.append(item); lg_count[lg] += 1
        used.add(f["home"]); used.add(f["away"])
    if not selected:
        send_message(chat_id, "Couldn't build Sure 10 today.",
                     reply_markup=add_footer_button()); return
    is_vip = user.is_vip or admin
    visible = len(selected) if is_vip else 2
    hidden = len(selected) - visible
    total_odds = 1.0
    for item in selected: total_odds *= item["pick"]["odds"]
    total_odds = round(total_odds, 2)
    header = (f"✅ *SURE 10 {label.upper()} PICKS*\n"
              f"📅 {datetime.now().strftime('%d %b %Y')}\n\n"
              f"🎯 10 highest-confidence predictions across {label}\n"
              f"💰 Combined odds if all 10 hit: *{total_odds}*\n"
              f"🔥 Recommended: Play as *Single Bets* — stake 2% per pick\n\n"
              f"━━━━━━━━━━━━━━━━━━━━━━")
    send_message(chat_id, header, parse_mode="Markdown")
    for i, item in enumerate(selected[:visible], 1):
        f = item["fixture"]; pk = item["pick"]; sa = stake_advice(pk["conf"])
        msg = (f"*#{i}. {f['home']} vs {f['away']}*\n"
               f"🏆 {f.get('league','')} · {f.get('time','')}\n\n"
               f"✅ *{pk['pick']}* @ *{pk['odds']}*\n"
               f"   🎯 Confidence: {pk['conf']}%")
        if pk.get("edge",0) > 0: msg += f" · +{pk['edge']}% edge"
        msg += f"\n   💰 Stake: {sa['percent']}% (N{sa['amount']})"
        send_message(chat_id, msg, parse_mode="Markdown")
        user.daily_count += 1; db.commit()
        time.sleep(0.5)
    if not is_vip and hidden > 0:
        send_upgrade_cta(chat_id, user, hidden_count=hidden, region_label=label,
                         locked_markets=["Correct Score","Handicap",
                                          "20-match Betslip + booking codes"])
    else:
        send_message(chat_id, f"✅ All 10 sent. Good luck!",
                     reply_markup=add_footer_button())

# ── ACCUMULATOR ──
def handle_accumulator(chat_id, user, db):
    admin = is_admin(user.user_id)
    if not user.is_vip and not admin:
        send_message(chat_id, (
            f"🎫 *Betslip 500K — VIP Only*\n\n"
            f"Build the smartest 20-match betslip:\n"
            f"✅ Personalized to *your* preferred regions\n"
            f"✅ *Real SportyBet + Football.com booking codes*\n"
            f"✅ One-tap load — no manual entry needed\n"
            f"✅ Bankroll advisor per leg\n"
            f"✅ Target: N1,000 → N500,000+\n\n"
            f"*You're missing out.* VIP users win 3x more."
        ), reply_markup=upgrade_buttons(user.user_id), parse_mode="Markdown"); return
    send_message(chat_id, "🎫 Building your 20-match betslip...\n~30 seconds.")
    prefs = get_user_prefs(user)
    pool = sb_fetch_events(timeline_hours=72, page_size=100)
    if not pool or len(pool) < 15: pool = fetch_all_fixtures(limit=80, preferred=prefs or None)
    if len(pool) < 10:
        send_message(chat_id, "Not enough fixtures right now.",
                     reply_markup=add_footer_button()); return
    selected = build_accumulator(pool, target_matches=20)
    if len(selected) < 5:
        send_message(chat_id, "Couldn't build safe betslip today.",
                     reply_markup=add_footer_button()); return
    msg_parts = [f"🎫 *YOUR 20-MATCH BETSLIP*", f"📅 {datetime.now().strftime('%d %b %Y')}"]
    if prefs:
        labs = " · ".join(REGIONS[k]["emoji"]+" "+REGIONS[k]["label"].split()[-1] for k in prefs)
        msg_parts.append(f"🎯 Personalized: {labs}")
    msg_parts.append("")
    total_odds = 1.0; sb_sel = []; picks = []
    for i, item in enumerate(selected, 1):
        f = item["fixture"]; pk = item["pick"]
        total_odds *= float(pk["odds"]); sa = stake_advice(pk["conf"])
        msg_parts.append(
            f"{i}. *{f['home']} vs {f['away']}*\n"
            f"   🏆 {f.get('league','')} · {f.get('time','')}\n"
            f"   ✅ {pk['pick']} @ {pk['odds']} ({pk['conf']}%)\n"
            f"   💰 Stake: {sa['percent']}%"
        )
        if f.get("eventId"):
            sel = market_to_sb_selection(pk, f["eventId"])
            if sel: sb_sel.append(sel)
        picks.append({"match":f"{f['home']} vs {f['away']}","league":f.get("league",""),
                      "pick":pk["pick"],"odds":pk["odds"],"conf":pk["conf"]})
    total_odds = round(total_odds, 2); win = round(total_odds * 1000, 2)
    msg_parts.append("")
    msg_parts.append(f"📊 *TOTAL ODDS:* {total_odds}")
    msg_parts.append(f"💰 N1,000 → N{win:,.0f}")
    msg_parts.append("")
    sb_code = sb_url = fb_code = None
    if sb_sel and len(sb_sel) >= 2:
        booking = sb_book_bet(sb_sel[:20])
        if booking and booking.get("shareCode"):
            sb_code = booking["shareCode"]
            sb_url = booking.get("shareURL") or sportybet_load_url(sb_code)
    if sb_code: fb_code = convert_sb_to_football(sb_code)
    msg_parts.append("🎟 *LOAD YOUR BETSLIP INSTANTLY*")
    msg_parts.append("━━━━━━━━━━━━━━━━━━━━━━")
    if sb_code:
        msg_parts.append(f"🟢 *SPORTYBET*\n   Code: `{sb_code}`\n   👉 {sb_url}")
    else:
        msg_parts.append("🟢 SPORTYBET: code unavailable — use list above")
    if fb_code:
        msg_parts.append(f"\n🔵 *FOOTBALL.COM*\n   Code: `{fb_code}`\n   👉 {football_com_load_url(fb_code)}")
    elif sb_code:
        msg_parts.append(f"\n🔵 *FOOTBALL.COM*\n   Convert `{sb_code}` at:\n   https://betrelay.com.ng/sportybet-to-football")
    msg_parts.append(f"\n🟡 *BETKING*\n   👉 https://www.betking.com/sports")
    msg_parts.append(f"\n🔴 *1XBET*\n   👉 https://1xbet.ng/en/line/football")
    msg_parts.append("\n⚠️ High-odds betslip. Bet responsibly. 18+")
    full_msg = "\n".join(msg_parts)
    footer_kb = {"inline_keyboard":[]}
    if sb_url: footer_kb["inline_keyboard"].append([{"text":"🟢 Load on SportyBet","url":sb_url}])
    if fb_code: footer_kb["inline_keyboard"].append([{"text":"🔵 Load on Football.com","url":football_com_load_url(fb_code)}])
    footer_kb["inline_keyboard"].append([{"text":"🟡 BetKing","url":"https://www.betking.com/sports"},
                                          {"text":"🔴 1xBet","url":"https://1xbet.ng/en/line/football"}])
    add_footer_button(footer_kb)
    if len(full_msg) > 3500:
        idx = full_msg.find("🎟 *LOAD YOUR BETSLIP INSTANTLY*")
        if idx > 0:
            send_message(chat_id, full_msg[:idx].strip(), parse_mode="Markdown")
            time.sleep(0.5)
            send_message(chat_id, full_msg[idx:].strip(),
                         reply_markup=footer_kb, parse_mode="Markdown")
        else:
            send_message(chat_id, full_msg, reply_markup=footer_kb, parse_mode="Markdown")
    else:
        send_message(chat_id, full_msg, reply_markup=footer_kb, parse_mode="Markdown")
    try:
        for sp in picks:
            db.add(Prediction(user_id=user.user_id, match=sp["match"], league=sp["league"],
                              market="BETSLIP", pick=sp["pick"], odds=sp["odds"],
                              confidence=sp["conf"], match_date=str(date.today())))
        db.commit()
    except: pass

# ── N1M ──
def handle_n1m(chat_id, user, db):
    admin = is_admin(user.user_id)
    if not user.is_vip and not admin:
        send_message(chat_id, f"🚀 *N1M Challenge — VIP Only*\n\n"
                     f"Turn ₦1,000 into ₦1,000,000 with one accumulator.",
                     reply_markup=upgrade_buttons(user.user_id), parse_mode="Markdown"); return
    send_message(chat_id, "🚀 Building your N1M slip...", reply_markup=get_main_keyboard(admin))
    prefs = get_user_prefs(user)
    pool = sb_fetch_events(timeline_hours=72) or fetch_all_fixtures(limit=80, preferred=prefs or None)
    if len(pool) < 8:
        send_message(chat_id, f"Not enough fixtures ({len(pool)}).",
                     reply_markup=add_footer_button()); return
    selected = build_accumulator(pool, target_matches=20)
    picks = []; total_odds = 1.0
    for item in selected:
        f = item["fixture"]; p = item["pick"]
        total_odds *= float(p["odds"])
        picks.append({"match":f"{f['home']} vs {f['away']}","pick":p["pick"],
                      "odds":p["odds"],"conf":p["conf"]})
    total_odds = round(total_odds, 2); win = round(1000*total_odds, 2)
    user.n1m_bankroll = 1000
    if win > (user.n1m_best or 0): user.n1m_best = win
    db.commit()
    msg = (f"🚀 *N1M CHALLENGE*\n\n"
           f"💰 Stake: N1,000\n🎯 Target: N1,000,000\n"
           f"📊 Odds: {total_odds}\n💵 Potential: N{win:,.0f}\n\n")
    for i, p in enumerate(picks[:20], 1):
        msg += f"{i}. {p['match']}\n   {p['pick']} @ {p['odds']} ({p['conf']}%)\n"
    msg += f"\n⚠️ High-risk. Bet responsibly."
    send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")

# ── ADMIN ──
def handle_admin_panel(chat_id, user):
    db = SessionLocal()
    try:
        tu = db.query(User).count(); tv = db.query(User).filter(User.is_vip==True).count()
        tp = db.query(Prediction).count(); pr = db.query(Proof).count()
    except: tu=tv=tp=pr=0
    finally: db.close()
    send_message(chat_id, (
        f"🔐 *ADMIN PANEL*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Users: {tu} (💎 VIP: {tv})\n"
        f"📈 Predictions: {tp}\n"
        f"🏆 Proofs: {pr}\n"
        f"🧠 Brain: {len(HISTORICAL_STATS)} teams\n"
        f"🎫 SB cache: {len(SB_EVENTS_CACHE.get('data',[]))}\n\n"
        f"*User Mgmt:*\n"
        f"/admin_stats /admin_users /admin_user `<uid>`\n"
        f"/admin_grant `<uid>` `<plan>` /admin_revoke `<uid>`\n"
        f"/admin_broadcast `<msg>` /admin_channels\n\n"
        f"*Proof Page:*\n"
        f"/admin_addproof `<date>` | `<match>` | `<pick>` | `<odds>` | `<WON/LOST>`\n"
        f"/admin_proofs /admin_delproof `<id>`\n\n"
        f"Admin ID: `{user.user_id}`"
    ), reply_markup=add_footer_button(), parse_mode="Markdown")

def handle_admin_stats(chat_id):
    db = SessionLocal()
    try:
        tu = db.query(User).count(); tv = db.query(User).filter(User.is_vip==True).count()
        tp = db.query(Prediction).count()
        wa = datetime.utcnow() - timedelta(days=7)
        nw = db.query(User).filter(User.created_at >= wa).count()
        send_message(chat_id, (
            f"📊 *GLOBAL STATS*\n\nUsers: {tu} (VIP: {tv})\n"
            f"New (7d): {nw}\nPredictions: {tp}\nBrain: {len(HISTORICAL_STATS)}"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
    except Exception as e: send_message(chat_id, f"Error: {e}")
    finally: db.close()

def handle_admin_users(chat_id, page=0):
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.last_seen.desc()).offset(page*20).limit(20).all()
        if not users:
            send_message(chat_id, "No users.", reply_markup=add_footer_button()); return
        msg = f"👥 *USERS (page {page+1})*\n\n"
        for u in users:
            tier = "💎" if u.is_vip else "🆓"
            name = (u.first_name or u.username or f"User{u.user_id}")[:20]
            msg += f"{tier} {name} · `{u.user_id}` · {u.daily_count}/day\n"
        kb = {"inline_keyboard": [[
            {"text":"⬅️ Prev","callback_data":f"admin_users_{max(0,page-1)}"},
            {"text":"Next ➡️","callback_data":f"admin_users_{page+1}"}]]}
        add_footer_button(kb)
        send_message(chat_id, msg, reply_markup=kb, parse_mode="Markdown")
    except Exception as e: send_message(chat_id, f"Error: {e}")
    finally: db.close()

def handle_admin_user_lookup(chat_id, uid):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.user_id == uid).first()
        if not u:
            send_message(chat_id, f"❌ {uid} not found.", reply_markup=add_footer_button()); return
        prefs = get_user_prefs(u)
        send_message(chat_id, (
            f"🔍 *USER {uid}*\n\nName: {u.first_name or '—'}\n"
            f"Username: @{u.username or '—'}\n"
            f"Tier: {'VIP' if u.is_vip else 'FREE'}\n"
            f"VIP until: {u.vip_expiry or '—'}\n"
            f"Preferred plan: {u.preferred_plan or '—'}\n"
            f"Visits: {u.total_visits or 0}\n"
            f"Predictions: {u.total_predictions or 0}\n"
            f"Referrals: {u.referral_count or 0}\n"
            f"Prefs: {', '.join(prefs) if prefs else '—'}"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
    except Exception as e: send_message(chat_id, f"Error: {e}")
    finally: db.close()

def handle_admin_grant(chat_id, uid, plan):
    if plan not in ("daily","weekly","monthly"):
        send_message(chat_id, f"❌ Invalid plan: {plan}", reply_markup=add_footer_button()); return
    if activate_vip(uid, plan, silent=False):
        send_message(chat_id, f"✅ Granted {plan} to {uid}", reply_markup=add_footer_button())
    else: send_message(chat_id, f"❌ Failed", reply_markup=add_footer_button())

def handle_admin_revoke(chat_id, uid):
    if revoke_vip(uid):
        send_message(chat_id, f"✅ Revoked {uid}", reply_markup=add_footer_button())
    else: send_message(chat_id, f"❌ Failed", reply_markup=add_footer_button())

def handle_admin_broadcast(chat_id, message):
    db = SessionLocal()
    try: users = db.query(User).all()
    finally: db.close()
    send_message(chat_id, f"📢 Broadcasting to {len(users)}...")
    sent = 0
    for u in users:
        try:
            r = send_message(u.user_id, f"📢 *ANNOUNCEMENT*\n\n{message}", parse_mode="Markdown")
            if r and r.get("ok"): sent += 1
            time.sleep(0.05)
        except: pass
    send_message(chat_id, f"✅ Sent to {sent}/{len(users)}", reply_markup=add_footer_button())

def handle_admin_test_channel(chat_id):
    if not CHANNEL_ID:
        send_message(chat_id, "❌ CHANNEL_ID not set.", reply_markup=add_footer_button()); return
    r = send_message(CHANNEL_ID, f"🧪 Test from {CHANNEL_NAME}\n{BOT_LINK}")
    send_message(chat_id, f"Sent: {bool(r and r.get('ok'))}", reply_markup=add_footer_button())

def handle_admin_addproof(chat_id, args_text):
    try:
        parts = [p.strip() for p in args_text.split("|")]
        if len(parts) < 4:
            send_message(chat_id, (
                "❌ Format:\n`/admin_addproof YYYY-MM-DD | Match | Pick | Odds | WON/LOST`\n\n"
                "Example:\n`/admin_addproof 2026-10-06 | Arsenal vs Chelsea | 1X | 1.25 | WON`"
            ), reply_markup=add_footer_button(), parse_mode="Markdown"); return
        proof_date = parts[0]; match = parts[1]; pick = parts[2]
        odds = float(parts[3]); result = parts[4].upper() if len(parts) >= 5 else "WON"
        if result not in ("WON","LOST"): result = "WON"
        db = SessionLocal()
        try:
            p = Proof(proof_date=proof_date, match=match, pick=pick,
                      odds=odds, result=result)
            db.add(p); db.commit(); proof_id = p.id
        finally: db.close()
        send_message(chat_id, (
            f"✅ *Proof added* (ID: {proof_id})\n\n📅 {proof_date}\n⚽ {match}\n✅ {pick} @ {odds}\n🏆 {result}"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
    except Exception as e:
        send_message(chat_id, f"❌ Error: {e}", reply_markup=add_footer_button())

def handle_admin_proofs(chat_id):
    db = SessionLocal()
    try:
        proofs = db.query(Proof).order_by(Proof.proof_date.desc()).limit(20).all()
        if not proofs:
            send_message(chat_id, "No proofs yet. Add with /admin_addproof",
                         reply_markup=add_footer_button()); return
        wins = sum(1 for p in proofs if p.result == "WON")
        msg = f"🏆 *RECENT PROOFS* ({wins}/{len(proofs)} won)\n\n"
        for p in proofs:
            emoji = "✅" if p.result == "WON" else "❌"
            msg += f"{emoji} `{p.id}` · {p.proof_date}\n   {p.match}\n   {p.pick} @ {p.odds}\n\n"
        send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")
    finally: db.close()

def handle_admin_delproof(chat_id, proof_id):
    db = SessionLocal()
    try:
        p = db.query(Proof).filter(Proof.id == proof_id).first()
        if not p:
            send_message(chat_id, f"❌ Proof {proof_id} not found.",
                         reply_markup=add_footer_button()); return
        db.delete(p); db.commit()
        send_message(chat_id, f"✅ Deleted proof {proof_id}",
                     reply_markup=add_footer_button())
    except Exception as e:
        send_message(chat_id, f"Error: {e}", reply_markup=add_footer_button())
    finally: db.close()

# ── MENU CALLBACKS ──
def handle_menu_callback(chat_id, user, db, action, msg_id=None):
    if action == "menu_main": send_main_menu(chat_id, user, db)
    elif action == "menu_today": handle_region(chat_id, user, db, "europe", min_fixtures=15)
    elif action == "menu_stats":
        total = user.total_predictions or 0; wins = user.total_wins or 0; losses = user.total_losses or 0
        wr = round(wins/total*100,1) if total>0 else 0
        admin_line = "\n🔐 ADMIN" if is_admin(user.user_id) else ""
        send_message(chat_id, (
            f"📊 *Your Stats*{admin_line}\n\n"
            f"🔥 Streak: {user.streak} (best {user.best_streak})\n"
            f"🎯 Predictions: {total}\n"
            f"✅ {wins}W / ❌ {losses}L\n"
            f"📈 Win rate: {wr}%\n\n"
            f"💰 Bankroll: N{user.bankroll:.0f}\n"
            f"🎁 Referrals: {user.referral_count or 0}\n"
            f"🚀 N1M: N{user.n1m_bankroll:.0f}\n\n"
            f"💡 *Tip:* Try `/stats Arsenal` for team-level stats"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
    elif action == "menu_leaderboard":
        try:
            top = db.query(User).filter(User.total_predictions >= 5)\
                .order_by(User.total_wins.desc()).limit(10).all()
        except: top = []
        msg = "🏆 *Leaderboard*\n\n"
        if not top: msg += "No stats yet."
        else:
            for i, u in enumerate(top, 1):
                medal = ["🥇","🥈","🥉"][i-1] if i<=3 else f"{i}."
                name = u.first_name or u.username or f"User{u.user_id}"
                rate = round(u.total_wins/max(u.total_predictions,1)*100,0)
                msg += f"{medal} {name} — {u.total_wins}W · {rate:.0f}%\n"
        send_message(chat_id, msg, reply_markup=add_footer_button(), parse_mode="Markdown")
    elif action == "menu_profile":
        tier = "🔐 ADMIN" if is_admin(user.user_id) else ("💎 VIP" if user.is_vip else "🆓 FREE")
        exp = user.vip_expiry if user.is_vip else "—"
        prefs = get_user_prefs(user)
        plabels = ", ".join(REGIONS[k]["label"] for k in prefs) if prefs else "Not set"
        limit = 999 if is_admin(user.user_id) else (10 if user.is_vip else 2)
        send_message(chat_id, (
            f"👤 *Your Profile*\n\nName: {user.first_name or user.username or 'Anon'}\n"
            f"Tier: {tier}\nVIP until: {exp}\n"
            f"Daily used: {user.daily_count}/{limit}\n\n"
            f"⚙️ Preferences: {plabels}\n"
            f"💳 Preferred plan: {user.preferred_plan or 'Not set'}\n"
            f"📊 Total visits: {getattr(user, 'total_visits', 0) or 0}"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
    elif action == "menu_prefs": handle_preferences_menu(chat_id, user, db)
    elif action == "menu_refer":
        ref_link = f"https://t.me/Betmasterpro_bot?start=ref_{user.referral_code}"
        send_message(chat_id, (
            f"🎁 *Refer Friends, Earn VIP*\n\nYour link:\n`{ref_link}`\n\n"
            f"✅ You get 7 free VIP days per paying referral\n"
            f"✅ They get 20% off their first month\n\n"
            f"Referrals: {user.referral_count or 0}"
        ), reply_markup=add_footer_button({"inline_keyboard":[[
            {"text":"📤 Share Link","url":f"https://t.me/share/url?url={ref_link}&text=Join%20{CHANNEL_NAME.replace(' ','%20')}"}]]}),
        parse_mode="Markdown")
    elif action == "menu_upgrade":
        if is_admin(user.user_id):
            send_message(chat_id, "🔐 ADMIN — full access.", reply_markup=add_footer_button()); return
        send_message(chat_id, (
            f"💎 *VIP Benefits*\n\n"
            f"✅ 10 predictions/day (vs FREE 2)\n"
            f"✅ 🎯 *Correct Score predictions*\n"
            f"✅ ⚖️ *Handicap picks*\n"
            f"✅ 🎫 *20-match Betslip with real booking codes*\n"
            f"✅ 🌏 All Asian leagues (CSL, J1, K League, Saudi)\n"
            f"✅ 🇺🇸 All American leagues (MLS, Liga MX, Brasileirão)\n"
            f"✅ 🌍 All African leagues\n"
            f"✅ 🚀 N1M Challenge — ₦1,000 → ₦1,000,000\n"
            f"✅ Full 13-market probabilities + bankroll advisor\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 *JOIN 5,000+ WINNING VIP MEMBERS*\n\n"
            f"*Plans:*\n• Daily — ₦500\n• Weekly — ₦2,000\n• Monthly — ₦5,000\n\n"
            f"📢 *Channel:* {CHANNEL_NAME} — {CHANNEL_LINK}"
        ), reply_markup=upgrade_buttons(user.user_id), parse_mode="Markdown")
    elif action == "menu_help":
        admin_line = ("\n🔐 Admin:\n/admin /admin_stats /admin_users\n"
                      "/admin_grant /admin_revoke /admin_broadcast\n"
                      "/admin_addproof /admin_proofs /admin_delproof\n") if is_admin(user.user_id) else ""
        send_message(chat_id, (
            f"📖 *Help*\n\n"
            f"*VIP:* /accumulator /million\n"
            f"*Leagues:* /europeanleagues /asianleagues /americanleagues /africanleagues /national\n"
            f"*Team Stats:* /stats Arsenal — form, goals, BTTS, Over 2.5\n"
            f"*Memory:* /remember — see everything I know about you\n"
            f"*Account:* /stats /leaderboard /refer /profile /preferences /upgrade\n"
            f"*Or send:* `Arsenal vs Chelsea` for instant analysis\n\n"
            f"💡 *After any prediction you get interactive buttons:*\n"
            f"📈 H2H  ·  📊 Form  ·  💰 Odds Compare\n"
            f"📢 *Channel:* {CHANNEL_NAME} — {CHANNEL_LINK}\n"
            f"{admin_line}\nFREE 2/day · VIP 10/day\n{BOT_LINK}"
        ), reply_markup=add_footer_button(), parse_mode="Markdown")
    elif action == "menu_admin" and is_admin(user.user_id):
        handle_admin_panel(chat_id, user)

# ── BUTTON ROUTER ──
def map_button_to_command(text, admin):
    low = text.strip().lower()
    if "today" in low and "fixture" in low: return "/today"
    if "n1m" in low or "challenge" in low: return "/million"
    if "european" in low: return "/europeanleagues"
    if "asian" in low: return "/asianleagues"
    if "american" in low: return "/americanleagues"
    if "african" in low: return "/africanleagues"
    if "national" in low: return "/national"
    if "accumulator" in low: return "/accumulator"
    if "preference" in low: return "/preferences"
    if admin and "admin" in low and "panel" in low: return "/admin"
    return None

# ── UPDATE PROCESSOR ──
def process_update(upd):
    try:
        base = f"https://api.telegram.org/bot{BOT_TOKEN}"
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            msg_id = cq["message"].get("message_id")
            from_id = cq["from"]["id"]
            data = cq.get("data","")
            admin = is_admin(from_id)
            requests.post(f"{base}/answerCallbackQuery",
                json={"callback_query_id":cq["id"],"text":"Working..."}, timeout=5)
            if data.startswith("admin_users_") and admin:
                try: page = int(data.replace("admin_users_",""))
                except: page = 0
                handle_admin_users(chat_id, page); return
            db2 = SessionLocal()
            try:
                user2 = get_user(db2, from_id, cq["from"].get("username",""),
                                 cq["from"].get("first_name",""))
                if data.startswith("pref_toggle_"):
                    handle_pref_toggle(chat_id, user2, db2, data.replace("pref_toggle_",""), msg_id=msg_id); return
                if data == "pref_reset": handle_pref_reset(chat_id, user2, db2, msg_id=msg_id); return
                if data == "pref_confirm": handle_pref_confirm(chat_id, user2, db2, msg_id=msg_id); return
                if data.startswith("h2h|"):
                    try:
                        _, h, a = data.split("|", 2)
                        handle_h2h_callback(chat_id, h, a)
                    except Exception as e: print(f"[h2h cb] {e}")
                    return
                if data.startswith("frm|"):
                    try:
                        _, h, a = data.split("|", 2)
                        handle_form_callback(chat_id, h, a)
                    except Exception as e: print(f"[frm cb] {e}")
                    return
                if data.startswith("odd|"):
                    try:
                        _, h, a = data.split("|", 2)
                        handle_odds_callback(chat_id, h, a)
                    except Exception as e: print(f"[odd cb] {e}")
                    return
                if data.startswith("predict_"):
                    rm = {"predict_europe":"europe","predict_asia":"asia",
                          "predict_america":"america","predict_africa":"africa",
                          "predict_national":"national","predict_top5":None}
                    handle_analyze_top10(chat_id, user2, db2, rm.get(data)); return
                if data.startswith("analyze10_"):
                    handle_analyze_top10(chat_id, user2, db2, data.replace("analyze10_","")); return
                if data.startswith("sure10_"):
                    handle_sure_10(chat_id, user2, db2, data.replace("sure10_","")); return
                if data == "sure_10_all": handle_sure_10(chat_id, user2, db2, None); return
                if data == "build_accumulator": handle_accumulator(chat_id, user2, db2); return
                if data in ("n1m_challenge","n1m_regen"): handle_n1m(chat_id, user2, db2); return
                if data.startswith("menu_"):
                    handle_menu_callback(chat_id, user2, db2, data, msg_id=msg_id); return
            finally: db2.close()
            return

        msg = upd.get("message")
        if not msg or "text" not in msg or msg["chat"]["type"] != "private": return
        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        user_id = msg["from"]["id"]
        username = msg["from"].get("username","")
        first_name = msg["from"].get("first_name","")
        low = text.lower()
        admin = is_admin(user_id)
        main_kb = get_main_keyboard(admin)
        mapped = map_button_to_command(text, admin)
        if mapped: low = mapped.lower(); text = mapped

        db = SessionLocal()
        try:
            user = get_user(db, user_id, username, first_name)
            FREE, VIP = 2, 10
            cur = 999999 if admin else (VIP if user.is_vip else FREE)

            if low.startswith("/admin") and admin:
                parts = text.split(maxsplit=2)
                sub = parts[0].lower()
                if sub == "/admin" or low.strip() == "/admin": handle_admin_panel(chat_id, user)
                elif sub == "/admin_stats": handle_admin_stats(chat_id)
                elif sub == "/admin_users": handle_admin_users(chat_id, 0)
                elif sub == "/admin_user" and len(parts) >= 2:
                    try: handle_admin_user_lookup(chat_id, int(parts[1]))
                    except: send_message(chat_id, "Usage: /admin_user `<uid>`",
                                         reply_markup=add_footer_button(), parse_mode="Markdown")
                elif sub == "/admin_grant" and len(parts) >= 3:
                    try: handle_admin_grant(chat_id, int(parts[1]), parts[2].lower())
                    except: send_message(chat_id, "Usage: /admin_grant `<uid> <plan>`",
                                         reply_markup=add_footer_button(), parse_mode="Markdown")
                elif sub == "/admin_revoke" and len(parts) >= 2:
                    try: handle_admin_revoke(chat_id, int(parts[1]))
                    except: send_message(chat_id, "Usage: /admin_revoke `<uid>`",
                                         reply_markup=add_footer_button(), parse_mode="Markdown")
                elif sub == "/admin_broadcast":
                    bmsg = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
                    if bmsg: threading.Thread(target=handle_admin_broadcast,
                                              args=(chat_id, bmsg), daemon=True).start()
                    else: send_message(chat_id, "Usage: /admin_broadcast `<msg>`",
                                       reply_markup=add_footer_button(), parse_mode="Markdown")
                elif sub == "/admin_addproof":
                    arg = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
                    handle_admin_addproof(chat_id, arg)
                elif sub == "/admin_proofs": handle_admin_proofs(chat_id)
                elif sub == "/admin_delproof" and len(parts) >= 2:
                    try: handle_admin_delproof(chat_id, int(parts[1]))
                    except: send_message(chat_id, "Usage: /admin_delproof `<id>`",
                                         reply_markup=add_footer_button(), parse_mode="Markdown")
                elif sub == "/admin_channels": handle_admin_test_channel(chat_id)
                else: send_message(chat_id, "Unknown admin cmd. /admin",
                                   reply_markup=add_footer_button())
                return
            if low.startswith("/admin"):
                send_message(chat_id, "⛔ Admin access required.", reply_markup=add_footer_button()); return

            if low.startswith("/start") and "ref_" in low:
                try:
                    rc = text.split("ref_")[1].split()[0].strip()
                    if rc and user.referred_by != rc: user.referred_by = rc; db.commit()
                except: pass

            if low.startswith("/start") or low.startswith("/menu"):
                send_start_message(chat_id, user, db)
            elif low.startswith("/preferences"):
                handle_preferences_menu(chat_id, user, db)
            elif low.startswith("/remember"):
                handle_remember(chat_id, user, db)
            elif low.startswith("/help"):
                handle_menu_callback(chat_id, user, db, "menu_help")
            elif low.startswith("/channel"):
                send_message(chat_id, (
                    f"📢 *{CHANNEL_NAME}*\n\n"
                    f"Join our official channel for daily free picks, "
                    f"VIP previews and community discussion.\n\n"
                    f"👉 {CHANNEL_LINK}"
                ), reply_markup=add_footer_button(), parse_mode="Markdown")
            elif low.startswith("/europeanleagues"):
                handle_region(chat_id, user, db, "europe")
            elif low.startswith("/asianleagues"):
                handle_region(chat_id, user, db, "asia")
            elif low.startswith("/americanleagues"):
                handle_region(chat_id, user, db, "america")
            elif low.startswith("/africanleagues"):
                handle_region(chat_id, user, db, "africa")
            elif low.startswith("/national"):
                handle_region(chat_id, user, db, "national")
            elif low.startswith("/accumulator"):
                handle_accumulator(chat_id, user, db)
            elif low.startswith("/million") or low.startswith("/m1"):
                handle_n1m(chat_id, user, db)
            elif low.startswith("/today"):
                handle_region(chat_id, user, db, "europe", min_fixtures=15)
            elif low.startswith("/betslip"):
                if not user.is_vip and not admin:
                    send_message(chat_id, f"💎 VIP only.",
                                 reply_markup=upgrade_buttons(user_id)); return
                handle_accumulator(chat_id, user, db)
            elif low.startswith("/stats"):
                parts = text.split(maxsplit=1)
                if len(parts) >= 2 and parts[1].strip():
                    handle_team_stats(chat_id, parts[1].strip(), user)
                else:
                    handle_menu_callback(chat_id, user, db, "menu_stats")
            elif low.startswith("/leaderboard"):
                handle_menu_callback(chat_id, user, db, "menu_leaderboard")
            elif low.startswith("/refer"):
                handle_menu_callback(chat_id, user, db, "menu_refer")
            elif low.startswith("/profile"):
                handle_menu_callback(chat_id, user, db, "menu_profile")
            elif low.startswith("/upgrade"):
                handle_menu_callback(chat_id, user, db, "menu_upgrade")
            elif " vs " in low and 5 < len(text) < 100:
                if not admin and user.daily_count >= cur:
                    send_message(chat_id, f"🚫 Limit {user.daily_count}/{cur}",
                                 reply_markup=upgrade_buttons(user_id)); return
                try:
                    parts = re.split(r"\s+vs\s+", text, flags=re.IGNORECASE)
                    home = parts[0].strip().title(); away = parts[1].strip().title()
                except:
                    send_message(chat_id, "Format: Team A vs Team B",
                                 reply_markup=add_footer_button()); return
                all_f = fetch_all_fixtures(limit=100, preferred=get_user_prefs(user) or None)
                matched = next((f for f in all_f
                                if home.lower() in f["home"].lower()
                                and away.lower() in f["away"].lower()), None)
                if not matched:
                    matched = next((f for f in all_f
                                    if away.lower() in f["home"].lower()
                                    and home.lower() in f["away"].lower()), None)
                data = matched or {"home":home,"away":away,"league":"Custom",
                    "date":datetime.now().strftime("%Y-%m-%d"),
                    "odds_h":0,"odds_d":0,"odds_a":0,"odds_over25":0,
                    "odds_btts":0,"source":"Model"}
                format_full_prediction(chat_id, data, show_all_markets=(user.is_vip or admin))
                user.daily_count += 1; db.commit()
            else:
                send_message(chat_id, f"Unknown command. /help\n{BOT_LINK}",
                             reply_markup=add_footer_button())
        except Exception as e:
            print(f"Handler: {e}"); traceback.print_exc(); db.rollback()
        finally: db.close()
    except Exception as outer:
        print(f"Outer: {outer}"); traceback.print_exc()

# ── DAILY NOTIFICATION ──
def send_daily_notification(user, db):
    try:
        prefs = get_user_prefs(user)
        if not prefs: return
        admin = is_admin(user.user_id)
        is_vip = user.is_vip or admin
        pool = []
        for k in prefs: pool.extend(fetch_region_fixtures(k, limit=8))
        if not pool: return
        ranked = []
        for f in pool[:30]:
            try:
                p = predict_match(f); ranked.append((safety_score(f, p), f, p))
            except: continue
        ranked.sort(key=lambda x: x[0], reverse=True)
        if not ranked: return
        visible = 5 if is_vip else 2
        hidden = min(10, len(ranked)) - visible
        pref_labels = " · ".join(REGIONS[k]["emoji"] for k in prefs)
        greeting = "☀️ Good morning" if 5 <= datetime.utcnow().hour <= 11 else "🌙 Daily picks"
        send_message(user.user_id, (
            f"{greeting}, *{user.first_name or 'Trader'}!*\n"
            f"📅 {datetime.now().strftime('%A %d %b')}\n"
            f"🎯 For: {pref_labels}\n\n"
            f"*Today's top picks from your preferred leagues*"
        ), parse_mode="Markdown")
        for i, (_, f, p) in enumerate(ranked[:visible], 1):
            sa = stake_advice(p["confidence"])
            msg = (f"*#{i}. {f['home']} vs {f['away']}*\n"
                   f"🏆 {f.get('league','')} · {f.get('time','')} WAT\n"
                   f"✅ *{p['best_pick']}* @ *{p['odds']}*\n"
                   f"   🎯 {p['confidence']}% confidence")
            if p.get("edge",0) > 0: msg += f" · +{p['edge']}% edge"
            msg += f"\n   💰 Stake: {sa['percent']}% (N{sa['amount']})"
            send_message(user.user_id, msg, parse_mode="Markdown")
            time.sleep(0.4)
        if not is_vip and hidden > 0:
            send_upgrade_cta(user.user_id, user, hidden_count=hidden,
                             locked_markets=["Correct Score","Handicap","20-match Betslip"])
        else:
            send_message(user.user_id, "✅ Want more? Tap below 👇",
                         reply_markup=get_inline_menu(admin))
    except Exception as e:
        print(f"[daily_notify] {e}")

def daily_notification_loop():
    while True:
        try:
            now_wat = datetime.utcnow() + timedelta(hours=1)
            if now_wat.hour == 9 and now_wat.minute < 5:
                today_str = str(date.today())
                db = SessionLocal()
                try:
                    users = db.query(User).filter(
                        User.preferences_set == True,
                        User.daily_notify_enabled == True,
                        User.is_banned == False).all()
                finally: db.close()
                sent = 0
                for u in users:
                    if u.notified_today == today_str: continue
                    if not get_user_prefs(u): continue
                    try:
                        db2 = SessionLocal()
                        fresh = db2.query(User).filter(User.user_id == u.user_id).first()
                        if fresh and fresh.notified_today != today_str:
                            send_daily_notification(fresh, db2)
                            fresh.notified_today = today_str; db2.commit(); sent += 1
                        db2.close()
                    except Exception as e: print(f"[notify {u.user_id}] {e}")
                    time.sleep(0.3)
                if sent: print(f"[daily_notify] sent to {sent}")
            time.sleep(300)
        except Exception as e:
            print(f"[daily_loop] {e}"); time.sleep(300)

# ── CHANNEL SCHEDULER ──
def channel_scheduler():
    posted_today = set()
    while True:
        try:
            now_wat = datetime.utcnow() + timedelta(hours=1)
            hm = now_wat.strftime("%H:%M"); today_str = now_wat.strftime("%Y-%m-%d")
            if hm == "08:00" and f"{today_str}-8am" not in posted_today and CHANNEL_ID:
                try:
                    pool = sb_fetch_events(timeline_hours=24, page_size=60) or fetch_all_fixtures(limit=40)
                    if pool:
                        ranked = []
                        for f in pool[:30]:
                            try:
                                p = predict_match(f); ranked.append((safety_score(f, p), f, p))
                            except: continue
                        ranked.sort(key=lambda x: x[0], reverse=True)
                        msg = (
                            f"🏆 *{CHANNEL_NAME.upper()}* — Daily Predictions\n"
                            f"📅 {today_str}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"🎯 *TOP 2 FREE PICKS*\n\n"
                        )
                        for i, (_, f, p) in enumerate(ranked[:2], 1):
                            msg += (f"*{i}. {f['home']} vs {f['away']}*\n"
                                    f"   🏆 {f.get('league','')} · {f.get('time','')}\n"
                                    f"   ✅ {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n\n")
                        msg += (
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🔒 *8 MORE PICKS + VIP MARKETS*\n\n"
                            f"💎 *JOIN 5,000+ WINNERS TODAY*\n"
                            f"✅ Correct Score + Handicap\n"
                            f"✅ 20-match Betslip with real booking codes\n"
                            f"✅ Asian / American / African leagues\n\n"
                            f"👉 *Unlock on the bot:* {BOT_LINK}\n"
                            f"📢 *Channel:* {CHANNEL_NAME} — {CHANNEL_LINK}\n\n"
                            f"{BOT_HANDLE}"
                        )
                        send_message(CHANNEL_ID, msg, parse_mode="Markdown")
                except Exception as e: print(f"[8am] {e}")
                posted_today.add(f"{today_str}-8am")
            if hm == "00:05": posted_today.clear()
        except Exception as e: print(f"[sched] {e}")
        time.sleep(60)

# ── STARTUP ──
threading.Thread(target=load_brain, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()
threading.Thread(target=daily_notification_loop, daemon=True).start()

@app.on_event("startup")
async def on_startup():
    set_bot_menu()
    print(f"[startup] Admins: {ADMIN_IDS}")
    print(f"[startup] Channel: {CHANNEL_NAME} — {CHANNEL_LINK}")
    print(f"[startup] DB: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL[:40]}")
    try:
        url = (f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
               f"?url={RENDER_URL}/webhook&drop_pending_updates=true")
        r = requests.get(url, timeout=10).json()
        print(f"WEBHOOK SET: {r}")
    except Exception as e: print(f"Webhook: {e}")

# ── FASTAPI ──
@app.get("/")
async def home():
    return {"status":f"{CHANNEL_NAME} v8 — Full Persistence + Interactive",
            "channel":CHANNEL_LINK,
            "admins":len(ADMIN_IDS),
            "features":["vip markets","proof page","league gating","preferences",
                        "personalized accumulator","daily push","betslip codes",
                        "N1M challenge","admin panel","team stats","h2h","form",
                        "odds compare","persistent memory","welcome back",
                        "preferred plan","channel branding"],
            "brain":f"{len(HISTORICAL_STATS)} teams"}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        threading.Thread(target=process_update, args=(data,), daemon=True).start()
        return JSONResponse({"ok":True})
    except Exception as e: print(f"Webhook: {e}"); return JSONResponse({"ok":True})

@app.get("/set-webhook")
async def set_webhook():
    set_bot_menu()
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
                     f"?url={RENDER_URL}/webhook&drop_pending_updates=true", timeout=10).json()
    return r

@app.get("/test-sportybet")
async def test_sportybet():
    events = sb_fetch_events(timeline_hours=48, page_size=20)
    return {"count":len(events),"sample":events[:3] if events else []}

@app.get("/admin/whoami")
async def admin_whoami(uid: str = ""):
    try: uid_int = int(uid)
    except: return {"error":"Provide ?uid=123456789"}
    return {"uid":uid_int,"is_admin":is_admin(uid_int)}

@app.get("/debug-db")
async def debug_db():
    db = SessionLocal()
    try:
        total = db.query(User).count()
        recent = db.query(User).order_by(User.last_seen.desc()).limit(5).all()
        return {
            "channel": CHANNEL_LINK,
            "db_url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL[:30],
            "persistent": "postgresql" in DATABASE_URL or "/data/" in DATABASE_URL,
            "total_users": total,
            "recent_users": [
                {"id": u.user_id, "name": u.first_name, "visits": u.total_visits or 0,
                 "pref_plan": u.preferred_plan or "", "tier": "VIP" if u.is_vip else "FREE"}
                for u in recent
            ],
        }
    finally: db.close()

# ── PROOF SECTION ──
def fetch_proofs_for_page():
    try:
        db = SessionLocal()
        try:
            proofs = db.query(Proof).order_by(Proof.proof_date.desc()).limit(10).all()
        finally: db.close()
        if proofs:
            return [{"date":p.proof_date,"match":p.match,"pick":p.pick,
                     "odds":p.odds,"result":p.result} for p in proofs]
    except Exception as e: print(f"[proofs] {e}")
    today = date.today(); samples = []
    for i in range(7):
        d = today - timedelta(days=i+1)
        samples.append({"date":str(d),
            "match":["Arsenal vs Chelsea","Barcelona vs Sevilla","Bayern vs Dortmund",
                     "PSG vs Lyon","Inter vs Roma","Ajax vs Feyenoord","Real Madrid vs Atletico"][i],
            "pick":["1X","Over 2.5","BTTS Yes","Over 1.5","Home Win","BTTS No","1X"][i],
            "odds":[1.25,1.85,1.72,1.28,1.95,1.68,1.22][i],
            "result":"WON"})
    return samples

def build_proof_html():
    proofs = fetch_proofs_for_page()
    if not proofs: return ""
    wins = sum(1 for p in proofs if p["result"] == "WON")
    total = len(proofs); win_rate = round(wins/total*100) if total > 0 else 0
    rows = ""
    for p in proofs[:8]:
        emoji = "✅" if p["result"] == "WON" else "❌"
        rows += f"""<div class="proof-row">
          <span class="p-date">{p['date']}</span>
          <span class="p-match">{p['match']}</span>
          <span class="p-pick">{p['pick']}</span>
          <span class="p-odds">@{p['odds']}</span>
          <span class="p-status">{emoji}</span>
        </div>"""
    return f"""
    <section class="proofs">
      <div class="proofs-header">
        <h2>📈 Verified Winning Predictions</h2>
        <p class="proofs-sub">Real results from real matches — updated daily by {CHANNEL_NAME}</p>
        <div class="proofs-stats">
          <div class="proof-stat"><div class="proof-stat-num">{win_rate}%</div>
          <div class="proof-stat-lbl">Win Rate</div></div>
          <div class="proof-stat"><div class="proof-stat-num">{wins}/{total}</div>
          <div class="proof-stat-lbl">Last {total} Picks</div></div>
          <div class="proof-stat"><div class="proof-stat-num">5,000+</div>
          <div class="proof-stat-lbl">VIP Members</div></div>
        </div>
      </div>
      <div class="proof-table">
        <div class="proof-head">
          <span>Date</span><span>Match</span><span>Pick</span><span>Odds</span><span></span>
        </div>
        {rows}
      </div>
    </section>"""

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    preferred = ""
    try:
        dbs = SessionLocal()
        usr = dbs.query(User).filter(User.user_id == int(uid)).first()
        if usr and usr.preferred_plan:
            preferred = usr.preferred_plan
        dbs.close()
    except Exception:
        pass
    return HTMLResponse(render_payment_page(uid, build_proof_html(), preferred))

@app.get("/pay")
async def pay(plan: str, uid: str):
    if not FLW_SECRET:
        return HTMLResponse(render_failed_page("Payment not configured.", uid), status_code=500)
    try:
        dbp = SessionLocal()
        up = get_user(dbp, int(uid))
        up.preferred_plan = plan
        dbp.commit()
        dbp.close()
    except Exception as e:
        print(f"[pay] save preferred_plan: {e}")
    if plan not in ("daily","weekly","monthly"):
        return HTMLResponse(render_failed_page(f"Invalid plan: {plan}", uid), status_code=400)
    amounts = {"daily":500,"weekly":2000,"monthly":5000}
    amount = amounts[plan]; tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload = {"tx_ref":tx_ref,"amount":amount,"currency":"NGN",
        "redirect_url":f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer":{"email":f"{uid}@betmasterpro.com","name":f"User {uid}"},
        "customizations":{"title":f"{CHANNEL_NAME} — {plan.title()}"},
        "payment_options":"card,banktransfer,ussd,mobilemoney"}
    try:
        r = requests.post("https://api.flutterwave.com/v3/payments", json=payload,
            headers={"Authorization":f"Bearer {FLW_SECRET}"}, timeout=20).json()
        if r.get("status")=="success" and r.get("data",{}).get("link"):
            return RedirectResponse(r["data"]["link"])
        return HTMLResponse(render_failed_page(r.get("message","Failed"), uid), status_code=400)
    except Exception as e:
        return HTMLResponse(render_failed_page(f"Error: {e}", uid), status_code=500)

@app.get("/verify")
async def verify(tx_ref: str, uid: str, plan: str):
    try:
        r = requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}",
            headers={"Authorization":f"Bearer {FLW_SECRET}"}, timeout=20).json()
        if r.get("status")=="success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ("successful","completed"):
                activate_vip(uid, plan)
                try:
                    db = SessionLocal(); u = get_user(db, int(uid))
                    if u.referred_by: award_referral(db, u.referred_by, int(uid))
                    db.close()
                except: pass
                return HTMLResponse(render_success_page(plan))
            return HTMLResponse(render_failed_page(f"Status: {data.get('status')}", uid), status_code=400)
        return HTMLResponse(render_failed_page("Not found.", uid), status_code=404)
    except Exception as e:
        return HTMLResponse(render_failed_page(f"Error: {e}", uid), status_code=500)

@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request: Request):
    try:
        sig = request.headers.get("verif-hash","")
        if FLW_WEBHOOK_HASH and sig != FLW_WEBHOOK_HASH:
            return JSONResponse({"status":"invalid"}, status_code=401)
        payload = await request.json()
        data = payload.get("data",{})
        if data.get("status","").lower() not in ("successful","completed"):
            return JSONResponse({"status":"ignored"})
        tx_ref = data.get("tx_ref","")
        parts = tx_ref.split("-")
        if len(parts)<4 or parts[0]!="BETMASTER":
            return JSONResponse({"status":"malformed"})
        uid, plan = parts[1], parts[2]
        verify = requests.get(f"https://api.flutterwave.com/v3/transactions/{data.get('id')}/verify",
            headers={"Authorization":f"Bearer {FLW_SECRET}"}, timeout=15).json()
        if (verify.get("status")=="success" and
            verify.get("data",{}).get("status")=="successful"):
            db = SessionLocal()
            try:
                u = get_user(db, int(uid))
                if u.is_vip and u.vip_expiry >= str(date.today()):
                    return JSONResponse({"status":"already_active"})
            finally: db.close()
            activate_vip(uid, plan)
        return JSONResponse({"status":"success"})
    except Exception as e: print(f"Webhook: {e}"); return JSONResponse({"status":"error"}, status_code=500)

# ── PAYMENT TEMPLATES ──
PAYMENT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Bet Master Pro — VIP</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;
background:#0a0e1a;color:#e8ecf5;line-height:1.5;min-height:100vh;padding:20px}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:34px;font-weight:700;letter-spacing:-.03em;margin:30px 0 12px;
background:linear-gradient(180deg,#fff,#b8c1d6);-webkit-background-clip:text;
-webkit-text-fill-color:transparent}
p.lead{color:#8b94ab;font-size:15px;margin-bottom:30px}
.channel-badge{display:inline-block;padding:8px 16px;background:rgba(34,197,94,.1);
border:1px solid rgba(34,197,94,.25);border-radius:999px;color:#4ade80;
font-size:13px;font-weight:600;margin-bottom:20px}
.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:50px}
.plan{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);
border-radius:16px;padding:26px 22px;position:relative}
.plan.featured{border-color:rgba(59,130,246,.4);
background:linear-gradient(180deg,rgba(59,130,246,.06),rgba(59,130,246,.02));
box-shadow:0 20px 60px -20px rgba(59,130,246,.35)}
.name{font-size:13px;font-weight:600;color:#8b94ab;letter-spacing:.08em;
text-transform:uppercase;margin-bottom:12px}
.price{font-size:34px;font-weight:700;margin-bottom:4px}
.price small{font-size:14px;color:#8b94ab;font-weight:500}
ul{list-style:none;margin:20px 0}
ul li{padding:6px 0;font-size:13.5px}
ul li:before{content:"✅ ";color:#22c55e}
.btn{display:block;padding:14px;border-radius:10px;text-decoration:none;
color:white;text-align:center;font-weight:600;font-size:14.5px;margin-top:16px}
.btn-g{background:linear-gradient(135deg,#22c55e,#16a34a)}
.btn-b{background:linear-gradient(135deg,#3b82f6,#2563eb)}
.pref-badge{color:#f5b945;font-size:11px;display:block;margin-bottom:6px;
font-weight:700;letter-spacing:.05em}
.proofs{margin:50px 0;padding:30px 24px;background:rgba(34,197,94,.04);
border:1px solid rgba(34,197,94,.15);border-radius:20px}
.proofs-header{text-align:center;margin-bottom:26px}
.proofs h2{font-size:24px;font-weight:700;letter-spacing:-.02em;margin-bottom:8px;
background:linear-gradient(180deg,#fff,#b8c1d6);-webkit-background-clip:text;
-webkit-text-fill-color:transparent}
.proofs-sub{color:#8b94ab;font-size:13.5px;margin-bottom:22px}
.proofs-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;
max-width:520px;margin:0 auto}
.proof-stat{background:rgba(255,255,255,.03);border:1px solid rgba(34,197,94,.2);
border-radius:12px;padding:14px 10px}
.proof-stat-num{font-size:22px;font-weight:700;color:#4ade80;letter-spacing:-.02em}
.proof-stat-lbl{font-size:11.5px;color:#8b94ab;margin-top:4px;text-transform:uppercase;
letter-spacing:.05em}
.proof-table{background:rgba(0,0,0,.2);border-radius:12px;overflow:hidden;
border:1px solid rgba(255,255,255,.05)}
.proof-head,.proof-row{display:grid;
grid-template-columns:90px 1fr 100px 60px 40px;gap:10px;
padding:12px 16px;font-size:13px;align-items:center}
.proof-head{background:rgba(0,0,0,.3);font-size:11px;text-transform:uppercase;
letter-spacing:.08em;color:#8b94ab;font-weight:600}
.proof-row{border-top:1px solid rgba(255,255,255,.04)}
.proof-row:first-of-type{border-top:none}
.p-date{color:#8b94ab;font-size:12px}
.p-match{color:#e8ecf5;font-weight:500}
.p-pick{color:#4ade80;font-weight:600}
.p-odds{color:#f5b945;font-weight:600;text-align:right}
.p-status{text-align:right;font-size:15px}
.cta-channel{display:block;padding:16px;background:rgba(34,197,94,.08);
border:1px solid rgba(34,197,94,.25);border-radius:12px;text-decoration:none;
color:#4ade80;text-align:center;font-weight:600;margin-top:24px}
@media(max-width:720px){
  .plans{grid-template-columns:1fr}h1{font-size:26px}
  .proof-head,.proof-row{grid-template-columns:70px 1fr 70px 50px 30px;
  font-size:11.5px;padding:10px 12px}
  .p-date{font-size:10.5px}
}
.foot{margin-top:40px;padding:20px 0;border-top:1px solid rgba(255,255,255,.08);
text-align:center;font-size:12px;color:#5a6378}
</style></head><body>
<div class="wrap">
<div style="text-align:center">
<div class="channel-badge">🏆 Bet Master Pro — Official</div>
</div>
<h1>Unlock AI Football Predictions</h1>
<p class="lead">13 markets · Personalized to your regions · Real SportyBet + Football.com codes</p>
<div class="plans">
<div class="plan">{{BADGE_DAILY}}<div class="name">Daily</div><div class="price">₦500<small>/24h</small></div>
<ul><li>10 predictions</li><li>All VIP markets</li><li>Real codes</li></ul>
<a href="/pay?plan=daily&uid={{UID}}" class="btn btn-g">Get 24h</a></div>
<div class="plan featured">{{BADGE_MONTHLY}}<div class="name">Monthly (Best)</div>
<div class="price">₦5,000<small>/month</small></div>
<ul><li>Everything</li><li>Priority support</li><li>Early features</li></ul>
<a href="/pay?plan=monthly&uid={{UID}}" class="btn btn-b">Get Monthly</a></div>
<div class="plan">{{BADGE_WEEKLY}}<div class="name">Weekly</div><div class="price">₦2,000<small>/week</small></div>
<ul><li>10 predictions/day</li><li>All 13 markets</li><li>Value bets</li></ul>
<a href="/pay?plan=weekly&uid={{UID}}" class="btn btn-g">Get Weekly</a></div>
</div>
{{PROOFS}}
<a href="{{CHANNEL_LINK}}" class="cta-channel">📢 Join {{CHANNEL_NAME}} on Telegram →</a>
<div class="foot">© {{YEAR}} Bet Master Pro · 18+ · Bet responsibly</div>
</div></body></html>"""

SUCCESS_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Success</title>
<style>body{font-family:Arial,sans-serif;background:#0a0e1a;color:#e8ecf5;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(34,197,94,.25);
border-radius:20px;padding:48px 36px;max-width:440px;text-align:center}
h1{color:#4ade80;margin:20px 0 10px}
a{display:block;padding:15px;background:linear-gradient(135deg,#22c55e,#16a34a);
color:white;text-decoration:none;border-radius:12px;font-weight:600;margin-top:20px}
.b{background:transparent;color:#8b94ab;border:1px solid rgba(255,255,255,.1)}
</style></head><body>
<div class="card"><h1>✅ {{PLAN}} Activated</h1>
<p>Return to the bot to start winning.</p>
<a href="{{BOT_LINK}}">Open Bot</a>
<a href="{{CHANNEL_LINK}}" class="b">📢 Join Channel</a></div></body></html>"""

FAILED_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Failed</title>
<style>body{font-family:Arial,sans-serif;background:#0a0e1a;color:#e8ecf5;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(239,68,68,.25);
border-radius:20px;padding:48px 36px;max-width:440px;text-align:center}
h1{color:#fca5a5}.reason{background:rgba(0,0,0,.3);border-radius:10px;padding:14px;
font-family:monospace;font-size:13px;margin:20px 0;word-break:break-word}
a{display:block;padding:14px;border-radius:12px;text-decoration:none;margin-top:10px}
.a{background:linear-gradient(135deg,#22c55e,#16a34a);color:white}
.b{background:transparent;color:#8b94ab;border:1px solid rgba(255,255,255,.1)}
</style></head><body>
<div class="card"><h1>Payment Not Confirmed</h1>
<div class="reason">{{REASON}}</div>
<a href="/subscribe?uid={{UID}}" class="a">Try Again</a>
<a href="{{BOT_LINK}}" class="b">Contact Support</a></div></body></html>"""

def render_payment_page(uid, proofs_html="", preferred=""):
    from datetime import datetime as _dt
    def badge(p):
        return ('<span class="pref-badge">⭐ YOUR PREVIOUS CHOICE</span>'
                if preferred == p else "")
    html = PAYMENT_TEMPLATE.replace("{{UID}}", str(uid))
    html = html.replace("{{BOT_LINK}}", BOT_LINK)
    html = html.replace("{{CHANNEL_LINK}}", CHANNEL_LINK)
    html = html.replace("{{CHANNEL_NAME}}", CHANNEL_NAME)
    html = html.replace("{{PROOFS}}", proofs_html)
    html = html.replace("{{YEAR}}", str(_dt.now().year))
    html = html.replace("{{BADGE_DAILY}}", badge("daily"))
    html = html.replace("{{BADGE_WEEKLY}}", badge("weekly"))
    html = html.replace("{{BADGE_MONTHLY}}", badge("monthly"))
    return html

def render_success_page(plan):
    return (SUCCESS_TEMPLATE.replace("{{PLAN}}", plan.upper())
            .replace("{{BOT_LINK}}", BOT_LINK)
            .replace("{{CHANNEL_LINK}}", CHANNEL_LINK))

def render_failed_page(reason, uid=""):
    return (FAILED_TEMPLATE.replace("{{REASON}}", html.escape(str(reason))[:500])
            .replace("{{UID}}", str(uid)).replace("{{BOT_LINK}}", BOT_LINK))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
