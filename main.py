"""
main.py — BetMaster Pro v3
Professional AI betting bot with:
- 13-market Dixon-Coles predictions + value bets
- Real SportyBet booking codes (live API)
- Football.com code conversion via BetRelay
- 20-match accumulator with safety ranking
- Tiered display (2 free / full VIP)
- Bankroll advisor, N1M challenge, admin panel

Data sources: ESPN, TheSportsDB, OpenFootball, The Odds API, SportyBet API.
"""

import os
import time
import threading
import requests
import json
import traceback
import random
import hashlib
import csv
import io
import re
import math
import html
from datetime import datetime, timedelta, date
from collections import defaultdict

import numpy as np
from scipy.stats import poisson
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
load_dotenv()

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

ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "")
ADMIN_IDS = set()
for _aid in ADMIN_IDS_RAW.split(","):
    _aid = _aid.strip()
    if _aid:
        try:
            ADMIN_IDS.add(int(_aid))
        except Exception:
            pass


def is_admin(user_id) -> bool:
    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Current-Country": "NG",
    "Accept-Language": "en-NG,en;q=0.9",
}

# ──────────────────────────────────────────────
# REPLY KEYBOARD
# ──────────────────────────────────────────────
BTN_TODAY = "⚽ Today's Fixtures"
BTN_N1M = "🚀 N1M Challenge"
BTN_EUROPE = "🇪🇺 European Leagues"
BTN_ASIA = "🇯🇵 Asian Leagues"
BTN_AMERICA = "🇺🇸 American Leagues"
BTN_ACCUMULATOR = "🎫 Accumulator"


def get_main_keyboard(is_admin_user: bool = False):
    keyboard = [
        [{"text": BTN_TODAY}, {"text": BTN_N1M}],
        [{"text": BTN_EUROPE}, {"text": BTN_ASIA}],
        [{"text": BTN_AMERICA}, {"text": BTN_ACCUMULATOR}],
    ]
    if is_admin_user:
        keyboard.append([{"text": "🔐 Admin Panel"}])
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Tap a button or send Team A vs Team B",
    }


# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Float,
    DateTime, Text, func
)
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./betmaster.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
        pool_pre_ping=True,
    )
except Exception:
    engine = create_engine("sqlite:///./betmaster.db",
                           connect_args={"check_same_thread": False})

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
    n1m_bankroll = Column(Float, default=0.0)
    n1m_best = Column(Float, default=0.0)
    bankroll = Column(Float, default=10000.0)
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


try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"DB init error: {e}")


# ──────────────────────────────────────────────
# DB HELPERS
# ──────────────────────────────────────────────
def get_user(db, user_id, username="", first_name=""):
    today_str = str(date.today())
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            ref_code = hashlib.md5(f"BM{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
            user = User(
                user_id=user_id, username=username, first_name=first_name,
                last_reset=today_str, daily_count=0,
                referral_code=ref_code, last_seen=datetime.utcnow(),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        if user.last_reset != today_str:
            user.daily_count = 0
            user.last_reset = today_str
            db.commit()
        if user.is_vip and user.vip_expiry and user.vip_expiry < today_str:
            user.is_vip = False
            user.vip_plan = ""
            db.commit()
        user.last_seen = datetime.utcnow()
        if username and user.username != username:
            user.username = username
        if first_name and user.first_name != first_name:
            user.first_name = first_name
        db.commit()
        return user
    except Exception as e:
        print(f"get_user error: {e}")
        class Dummy:
            user_id = user_id; daily_count = 0; is_vip = False
            vip_expiry = ""; streak = 0; best_streak = 0
            total_predictions = 0; total_wins = 0; total_losses = 0
            referral_code = ""; referral_count = 0
            fav_leagues = ""; fav_markets = ""
            n1m_bankroll = 0.0; n1m_best = 0.0
            bankroll = 10000.0
            is_banned = False
        return Dummy()


def activate_vip(uid, plan, silent=False):
    db = SessionLocal()
    try:
        user = get_user(db, int(uid))
        days = {"daily": 1, "weekly": 7, "monthly": 30}.get(plan, 30)
        expiry = date.today() + timedelta(days=days)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.vip_plan = plan
        user.daily_count = 0
        db.commit()
        if not silent:
            send_message(int(uid), (
                f"🎉 VIP {plan.upper()} ACTIVATED!\n\n"
                f"Valid until: {expiry}\n\n"
                f"You now have:\n"
                f"✅ 10 predictions/day\n"
                f"✅ 🎫 20-match Accumulator + real booking codes\n"
                f"✅ 🚀 N1M Challenge\n"
                f"✅ Full 13-market probabilities\n\n"
                f"Open the bot: {BOT_LINK}"
            ), reply_markup=get_main_keyboard(is_admin(int(uid))))
        return True
    except Exception as e:
        print(f"activate_vip error: {e}")
        return False
    finally:
        db.close()


def revoke_vip(uid):
    db = SessionLocal()
    try:
        user = get_user(db, int(uid))
        user.is_vip = False
        user.vip_expiry = ""
        user.vip_plan = ""
        db.commit()
        return True
    except Exception as e:
        print(f"revoke_vip error: {e}")
        return False
    finally:
        db.close()


# ──────────────────────────────────────────────
# BRAIN
# ──────────────────────────────────────────────
HISTORICAL_STATS = {}
H2H_CACHE = {}
ODDS_CACHE = {"time": None, "data": {}}
LEAGUE_AVG_GOALS = {}
SB_EVENTS_CACHE = {"time": None, "data": []}

TOP_LEAGUES = ["premier league", "la liga", "serie a", "bundesliga",
               "ligue 1", "champions league", "eredivisie", "primeira",
               "mls", "brasileir", "liga mx", "chinese super", "j1 league",
               "k league", "saudi pro"]


def is_youth(t):
    t = str(t).lower()
    return any(x in t for x in ["u21", "u-21", "u19", "u-20", "u23", "u17",
                                 "youth", "under 21", "women", "wfc"])


def calc(o, s):
    try:
        return round(float(o) * s, 2)
    except Exception:
        return 0


def load_brain():
    global HISTORICAL_STATS, LEAGUE_AVG_GOALS
    codes = ["E0", "SP1", "D1", "I1", "F1", "E1", "E2", "E3",
             "SP2", "D2", "I2", "F2", "N1", "B1", "P1", "T1", "G1", "SC0"]
    for code in codes:
        try:
            url = f"https://www.football-data.co.uk/mmz4281/2526/{code}.csv"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            reader = csv.DictReader(io.StringIO(r.text))
            rows = list(reader)[-120:]
            league_goals = []
            for row in rows:
                home = row.get("HomeTeam", "")
                away = row.get("AwayTeam", "")
                if not home or not away:
                    continue
                for team in [home, away]:
                    if team not in HISTORICAL_STATS:
                        HISTORICAL_STATS[team] = {
                            "games": 0, "scored": 0, "conceded": 0,
                            "wins": 0, "draws": 0, "losses": 0,
                            "form": [], "btts": 0, "over15": 0,
                            "over25": 0, "over35": 0, "clean": 0,
                            "failed_score": 0, "league": code,
                        }
                try:
                    fthg = int(row.get("FTHG", 0) or 0)
                    ftag = int(row.get("FTAG", 0) or 0)
                except Exception:
                    continue
                league_goals.append(fthg + ftag)
                HISTORICAL_STATS[home]["games"] += 1
                HISTORICAL_STATS[away]["games"] += 1
                HISTORICAL_STATS[home]["scored"] += fthg
                HISTORICAL_STATS[home]["conceded"] += ftag
                HISTORICAL_STATS[away]["scored"] += ftag
                HISTORICAL_STATS[away]["conceded"] += fthg
                if fthg > 0 and ftag > 0:
                    HISTORICAL_STATS[home]["btts"] += 1
                    HISTORICAL_STATS[away]["btts"] += 1
                else:
                    if fthg == 0: HISTORICAL_STATS[home]["failed_score"] += 1
                    if ftag == 0: HISTORICAL_STATS[away]["failed_score"] += 1
                    if ftag == 0: HISTORICAL_STATS[home]["clean"] += 1
                    if fthg == 0: HISTORICAL_STATS[away]["clean"] += 1
                if fthg + ftag > 1:
                    HISTORICAL_STATS[home]["over15"] += 1
                    HISTORICAL_STATS[away]["over15"] += 1
                if fthg + ftag > 2:
                    HISTORICAL_STATS[home]["over25"] += 1
                    HISTORICAL_STATS[away]["over25"] += 1
                if fthg + ftag > 3:
                    HISTORICAL_STATS[home]["over35"] += 1
                    HISTORICAL_STATS[away]["over35"] += 1
                if fthg > ftag:
                    HISTORICAL_STATS[home]["wins"] += 1
                    HISTORICAL_STATS[home]["form"].append("W")
                    HISTORICAL_STATS[away]["losses"] += 1
                    HISTORICAL_STATS[away]["form"].append("L")
                elif fthg == ftag:
                    HISTORICAL_STATS[home]["draws"] += 1
                    HISTORICAL_STATS[home]["form"].append("D")
                    HISTORICAL_STATS[away]["draws"] += 1
                    HISTORICAL_STATS[away]["form"].append("D")
                else:
                    HISTORICAL_STATS[home]["losses"] += 1
                    HISTORICAL_STATS[home]["form"].append("L")
                    HISTORICAL_STATS[away]["wins"] += 1
                    HISTORICAL_STATS[away]["form"].append("W")
                h2h_key = f"{home}_vs_{away}"
                if h2h_key not in H2H_CACHE:
                    H2H_CACHE[h2h_key] = []
                H2H_CACHE[h2h_key].append({
                    "home": home, "away": away, "fthg": fthg, "ftag": ftag,
                    "result": "H" if fthg > ftag else "A" if ftag > fthg else "D",
                    "total": fthg + ftag,
                    "btts": 1 if fthg > 0 and ftag > 0 else 0,
                })
            if league_goals:
                LEAGUE_AVG_GOALS[code] = sum(league_goals) / len(league_goals)
            for k in HISTORICAL_STATS:
                if len(HISTORICAL_STATS[k]["form"]) > 5:
                    HISTORICAL_STATS[k]["form"] = HISTORICAL_STATS[k]["form"][-5:]
        except Exception as e:
            print(f"Brain load error {code}: {e}")
    for code in codes:
        if code not in LEAGUE_AVG_GOALS:
            LEAGUE_AVG_GOALS[code] = 2.65
    print(f"BRAIN loaded {len(HISTORICAL_STATS)} teams, "
          f"H2H {len(H2H_CACHE)} pairs, {len(LEAGUE_AVG_GOALS)} leagues")


# ──────────────────────────────────────────────
# DIXON-COLES
# ──────────────────────────────────────────────
def estimate_team_strengths(team_name, league_code="E0"):
    stats = HISTORICAL_STATS.get(team_name)
    league_avg = LEAGUE_AVG_GOALS.get(league_code, 2.65) / 2.0
    if not stats or stats["games"] < 3:
        return {"attack": 1.0, "defense": 1.0, "games": 0, "source": "neutral"}
    games = stats["games"]
    attack = max(0.4, min(2.5, (stats["scored"] / games) / league_avg))
    defense = max(0.4, min(2.5, (stats["conceded"] / games) / league_avg))
    return {
        "attack": round(attack, 3), "defense": round(defense, 3),
        "games": games,
        "avg_scored": round(stats["scored"] / games, 2),
        "avg_conceded": round(stats["conceded"] / games, 2),
        "source": "historical",
    }


def dixon_coles_predict(home_team, away_team, league_code="E0",
                        home_advantage=0.20, rho=-0.05, max_goals=6):
    h = estimate_team_strengths(home_team, league_code)
    a = estimate_team_strengths(away_team, league_code)
    league_avg_per_team = LEAGUE_AVG_GOALS.get(league_code, 2.65) / 2.0
    home_xg = max(0.3, min(4.5, h["attack"] * a["defense"] * league_avg_per_team * math.exp(home_advantage)))
    away_xg = max(0.3, min(4.5, a["attack"] * h["defense"] * league_avg_per_team))
    probs = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson.pmf(i, home_xg) * poisson.pmf(j, away_xg)
            if i <= 1 and j <= 1:
                if i == 0 and j == 0: p *= (1 - home_xg * away_xg * rho)
                elif i == 0 and j == 1: p *= (1 + home_xg * rho)
                elif i == 1 and j == 0: p *= (1 + away_xg * rho)
                elif i == 1 and j == 1: p *= (1 - rho)
            probs[i][j] = max(0, p)
    total = probs.sum()
    if total <= 0:
        return {"home_win": 33.3, "draw": 33.3, "away_win": 33.3,
                "home_xg": round(home_xg, 2), "away_xg": round(away_xg, 2),
                "top_scorelines": [], "btts": 50.0, "over15": 50.0,
                "over25": 50.0, "over35": 50.0, "top_cs": "1-0",
                "home_strength": h, "away_strength": a}
    probs /= total
    home_win = float(np.tril(probs, -1).sum()) * 100
    draw = float(np.trace(probs)) * 100
    away_win = float(np.triu(probs, 1).sum()) * 100
    btts = float(probs[1:, 1:].sum()) * 100
    over25 = sum(probs[i][j] for i in range(max_goals) for j in range(max_goals) if i + j >= 3) * 100
    over15 = sum(probs[i][j] for i in range(max_goals) for j in range(max_goals) if i + j >= 2) * 100
    over35 = sum(probs[i][j] for i in range(max_goals) for j in range(max_goals) if i + j >= 4) * 100
    scores = [(f"{i}-{j}", round(float(probs[i][j]) * 100, 2))
              for i in range(max_goals) for j in range(max_goals)]
    scores.sort(key=lambda x: x[1], reverse=True)
    top_scorelines = scores[:5]
    return {
        "home_win": round(home_win, 1), "draw": round(draw, 1),
        "away_win": round(away_win, 1),
        "home_xg": round(home_xg, 2), "away_xg": round(away_xg, 2),
        "btts": round(btts, 1), "over15": round(over15, 1),
        "over25": round(over25, 1), "over35": round(over35, 1),
        "top_scorelines": top_scorelines,
        "top_cs": top_scorelines[0][0] if top_scorelines else "1-0",
        "home_strength": h, "away_strength": a,
    }


def predict_match(data):
    home = data.get("home", "Home")
    away = data.get("away", "Away")
    league_code = data.get("country", "E0")
    if league_code not in LEAGUE_AVG_GOALS:
        league_code = "E0"

    dc = dixon_coles_predict(home, away, league_code=league_code)

    h2h_key = f"{home}_vs_{away}"
    h2h_rev = f"{away}_vs_{home}"
    h2h_games = H2H_CACHE.get(h2h_key, []) + H2H_CACHE.get(h2h_rev, [])
    h2h_home_wins = len([g for g in h2h_games if
                         (g["home"] == home and g["result"] == "H") or
                         (g["away"] == home and g["result"] == "A")])
    h2h_away_wins = len([g for g in h2h_games if
                         (g["home"] == away and g["result"] == "H") or
                         (g["away"] == away and g["result"] == "A")])
    h2h_draws = len([g for g in h2h_games if g["result"] == "D"])
    h2h_btts = len([g for g in h2h_games if g["btts"] == 1])
    h2h_avg_goals = (sum(g["total"] for g in h2h_games) / len(h2h_games)) if h2h_games else 0

    dc_h, dc_d, dc_a = dc["home_win"], dc["draw"], dc["away_win"]
    if h2h_games and len(h2h_games) >= 3:
        w = 0.20
        dc_h = dc_h * (1 - w) + (h2h_home_wins / len(h2h_games) * 100) * w
        dc_d = dc_d * (1 - w) + (h2h_draws / len(h2h_games) * 100) * w
        dc_a = dc_a * (1 - w) + (h2h_away_wins / len(h2h_games) * 100) * w

    tot = dc_h + dc_d + dc_a
    if tot > 0:
        dc_h, dc_d, dc_a = dc_h / tot * 100, dc_d / tot * 100, dc_a / tot * 100

    p1 = round(dc_h, 1); pX = round(dc_d, 1); p2 = round(dc_a, 1)
    p1X = round(p1 + pX, 1); pX2 = round(pX + p2, 1); p12 = round(p1 + p2, 1)
    pBTTS_yes = round(dc["btts"], 1); pBTTS_no = round(100 - pBTTS_yes, 1)
    pO15 = round(dc["over15"], 1); pO25 = round(dc["over25"], 1); pO35 = round(dc["over35"], 1)
    pU15 = round(100 - pO15, 1); pU25 = round(100 - pO25, 1); pU35 = round(100 - pO35, 1)

    market_table = {
        "1": p1, "X": pX, "2": p2,
        "1X": p1X, "X2": pX2, "12": p12,
        "BTTS Yes": pBTTS_yes, "BTTS No": pBTTS_no,
        "Over 1.5": pO15, "Over 2.5": pO25, "Over 3.5": pO35,
        "Under 1.5": pU15, "Under 2.5": pU25, "Under 3.5": pU35,
    }

    odds_h = float(data.get("odds_h", 0) or 0) or round(100 / max(p1, 5), 2)
    odds_d = float(data.get("odds_d", 0) or 0) or round(100 / max(pX, 5), 2)
    odds_a = float(data.get("odds_a", 0) or 0) or round(100 / max(p2, 5), 2)
    odds_btts_y = float(data.get("odds_btts", 0) or 0) or round(100 / max(pBTTS_yes, 5), 2)
    odds_btts_n = round(100 / max(pBTTS_no, 5), 2)
    odds_o25 = float(data.get("odds_over25", 0) or 0) or round(100 / max(pO25, 5), 2)
    odds_u25 = round(100 / max(pU25, 5), 2)
    odds_1X = round(100 / max(p1X, 5), 2)
    odds_X2 = round(100 / max(pX2, 5), 2)
    odds_12 = round(100 / max(p12, 5), 2)
    odds_o15 = round(100 / max(pO15, 5), 2)
    odds_o35 = round(100 / max(pO35, 5), 2)
    odds_u15 = round(100 / max(pU15, 5), 2)
    odds_u35 = round(100 / max(pU35, 5), 2)

    candidates = []

    def add(market, pick, prob, odds_val, reason):
        if prob < 8 or prob > 95:
            return
        if not odds_val or odds_val <= 1.01:
            return
        implied = 100.0 / odds_val
        edge = round(prob - implied, 2)
        candidates.append({
            "market": market, "pick": pick, "prob": round(prob, 1),
            "conf": round(prob, 1), "odds": round(odds_val, 2),
            "edge": edge, "reason": reason,
        })

    add("1X2", f"{home} Win (1)", p1, odds_h, f"{home} win {p1}%.")
    add("1X2", "Draw (X)", pX, odds_d, f"Draw {pX}%.")
    add("1X2", f"{away} Win (2)", p2, odds_a, f"{away} win {p2}%.")
    add("DC", f"{home} or Draw (1X)", p1X, odds_1X, f"1X {p1X}%.")
    add("DC", f"Draw or {away} (X2)", pX2, odds_X2, f"X2 {pX2}%.")
    add("DC", f"{home} or {away} (12)", p12, odds_12, f"12 {p12}%.")
    add("BTTS", "BTTS Yes", pBTTS_yes, odds_btts_y, f"BTTS {pBTTS_yes}%.")
    add("BTTS", "BTTS No", pBTTS_no, odds_btts_n, f"BTTS No {pBTTS_no}%.")
    add("O/U", "Over 1.5 Goals", pO15, odds_o15, f"O1.5 {pO15}%.")
    add("O/U", "Over 2.5 Goals", pO25, odds_o25, f"O2.5 {pO25}%.")
    add("O/U", "Over 3.5 Goals", pO35, odds_o35, f"O3.5 {pO35}%.")
    add("O/U", "Under 1.5 Goals", pU15, odds_u15, f"U1.5 {pU15}%.")
    add("O/U", "Under 2.5 Goals", pU25, odds_u25, f"U2.5 {pU25}%.")
    add("O/U", "Under 3.5 Goals", pU35, odds_u35, f"U3.5 {pU35}%.")

    seen = set()
    unique = []
    for c in candidates:
        if c["pick"] not in seen:
            seen.add(c["pick"])
            unique.append(c)
    candidates = unique
    candidates.sort(key=lambda x: x["conf"], reverse=True)

    safe_pool = [c for c in candidates if c["odds"] >= 1.15] or candidates
    best = max(safe_pool, key=lambda x: (x["conf"], x["edge"]))

    value_pool = sorted(
        [c for c in candidates if c["edge"] > 2 and c["odds"] >= 1.30],
        key=lambda x: x["edge"], reverse=True,
    )
    value_picks = value_pool[:3]

    h_form = "".join(HISTORICAL_STATS.get(home, {}).get("form", [])[:5]) or "N/A"
    a_form = "".join(HISTORICAL_STATS.get(away, {}).get("form", [])[:5]) or "N/A"

    h2h_str = "No H2H data"
    if h2h_games:
        h2h_str = (f"H2H last {len(h2h_games)}: {home} {h2h_home_wins}W "
                   f"{h2h_draws}D {h2h_away_wins}W, BTTS {h2h_btts}/{len(h2h_games)}")

    explanation = best["reason"]
    if value_picks:
        v = value_picks[0]
        explanation += f"\n💎 VALUE: {v['pick']} @ {v['odds']} (+{v['edge']}%)"

    return {
        "best_market": best["market"],
        "best_pick": best["pick"],
        "odds": float(best["odds"]),
        "confidence": best["conf"],
        "edge": best.get("edge", 0),
        "explanation": explanation,
        "verdict": f"{best['market']} — {best['pick']} @ {best['odds']} ({best['conf']}%)",
        "all_markets": candidates,
        "top_markets": candidates[:6],
        "value_bets": value_picks,
        "market_table": market_table,
        "h2h": h2h_str,
        "form": f"Form: {home} [{h_form}] | {away} [{a_form}]",
        "standings": (f"xG: {home} {dc['home_xg']} — {away} {dc['away_xg']} | "
                      f"1X2: {p1}%/{pX}%/{p2}%"),
        "live_odds_source": data.get("source", "Model"),
        "winnings_1000": calc(best["odds"], 1000),
        "dc": dc,
        "disclaimer": "\n18+ Bet responsibly.",
    }


get_dynamic_ai_prediction = predict_match


# ──────────────────────────────────────────────
# BANKROLL ADVISOR
# ──────────────────────────────────────────────
def stake_advice(confidence, bankroll=10000.0):
    if confidence >= 90: pct = 5.0
    elif confidence >= 80: pct = 4.0
    elif confidence >= 70: pct = 3.0
    elif confidence >= 60: pct = 2.0
    else: pct = 1.0
    return {"percent": pct, "amount": round(bankroll * pct / 100, 2)}


# ──────────────────────────────────────────────
# ODDS FETCHER
# ──────────────────────────────────────────────
def fetch_the_odds_api(date_obj):
    global ODDS_CACHE
    if not THE_ODDS_API_KEY:
        return {}
    if (ODDS_CACHE["time"] and
            (datetime.now() - ODDS_CACHE["time"]).seconds < 600 and ODDS_CACHE["data"]):
        return ODDS_CACHE["data"]
    iso = date_obj.strftime("%Y-%m-%d")
    odds_map = {}
    sports = [
        "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
        "soccer_italy_serie_a", "soccer_france_ligue_one",
        "soccer_uefa_champs_league", "soccer_uefa_nations_league",
        "soccer_china_superleague", "soccer_usa_mls",
        "soccer_brazil_campeonato", "soccer_mexico_ligamx",
    ]
    for sport in sports:
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                params={"apiKey": THE_ODDS_API_KEY, "regions": "eu,uk",
                        "markets": "h2h,totals,btts", "oddsFormat": "decimal",
                        "dateFormat": "iso"},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            for game in r.json():
                try:
                    home = game["home_team"]; away = game["away_team"]
                    if game["commence_time"][:10] != iso:
                        continue
                    best_h = best_d = best_a = 0
                    best_over25 = best_btts = 0
                    for bk in game.get("bookmakers", [])[:6]:
                        for market in bk.get("markets", []):
                            if market["key"] == "h2h":
                                for o in market["outcomes"]:
                                    if o["name"] == home: best_h = max(best_h, o["price"])
                                    elif o["name"] == away: best_a = max(best_a, o["price"])
                                    elif o["name"] == "Draw": best_d = max(best_d, o["price"])
                            elif market["key"] == "totals":
                                for o in market["outcomes"]:
                                    if o["name"] == "Over" and o.get("point") == 2.5:
                                        best_over25 = max(best_over25, o["price"])
                            elif market["key"] == "btts":
                                for o in market["outcomes"]:
                                    if o["name"] == "Yes": best_btts = max(best_btts, o["price"])
                    odds_map[f"{home}_vs_{away}"] = {
                        "home": home, "away": away,
                        "league": game.get("sport_title", ""),
                        "odds_h": best_h or 0, "odds_d": best_d or 0, "odds_a": best_a or 0,
                        "odds_over25": best_over25 or 0, "odds_btts": best_btts or 0,
                        "source": "LIVE (Bet365/Pinnacle)",
                    }
                except Exception:
                    continue
        except Exception:
            continue
    ODDS_CACHE = {"time": datetime.now(), "data": odds_map}
    return odds_map


def enrich_with_odds(fixtures, date_obj):
    odds_map = fetch_the_odds_api(date_obj)
    for f in fixtures:
        key = f"{f['home']}_vs_{f['away']}"
        rev = f"{f['away']}_vs_{f['home']}"
        live = odds_map.get(key) or odds_map.get(rev)
        if live:
            f.update({
                "odds_h": live["odds_h"] or f.get("odds_h", 0),
                "odds_d": live["odds_d"] or f.get("odds_d", 0),
                "odds_a": live["odds_a"] or f.get("odds_a", 0),
                "odds_over25": live["odds_over25"] or f.get("odds_over25", 0),
                "odds_btts": live["odds_btts"] or f.get("odds_btts", 0),
                "source": live["source"],
            })
        else:
            for k in ["odds_h", "odds_d", "odds_a", "odds_over25", "odds_btts"]:
                f.setdefault(k, 0)
            f.setdefault("source", "Model")
    return fixtures


# ──────────────────────────────────────────────
# FETCHER IMPORTS
# ──────────────────────────────────────────────
from fetcher import (
    fetch_today_fixtures, fetch_by_region, fetch_espn,
    fetch_thesportsdb, fetch_openfootball_national, deduplicate,
)


def fetch_real_fixtures(days_ahead=0, limit=10, region=None):
    target = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=days_ahead)).date()
    if region:
        fixtures = fetch_by_region(target, region, limit=limit)
    else:
        fixtures = fetch_today_fixtures(target, limit=limit)
    if not fixtures and days_ahead == 0:
        for i in range(1, 8):
            t2 = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=i)).date()
            if region:
                fixtures = fetch_by_region(t2, region, limit=limit)
            else:
                fixtures = fetch_today_fixtures(t2, limit=limit)
            if fixtures:
                break
    return enrich_with_odds(fixtures, target)


# ──────────────────────────────────────────────
# SPORTYBET API
# ──────────────────────────────────────────────
def sb_fetch_events(timeline_hours=48, page_size=100):
    global SB_EVENTS_CACHE
    if (SB_EVENTS_CACHE["time"] and
            (datetime.now() - SB_EVENTS_CACHE["time"]).seconds < 300 and
            SB_EVENTS_CACHE["data"]):
        return SB_EVENTS_CACHE["data"]

    url = "https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents"
    params = {
        "sportId": "sr:sport:1",
        "marketId": "1,18,10,29",
        "pageSize": min(page_size, 100),
        "pageNum": 1,
        "timeline": min(timeline_hours, 720),
        "_t": int(time.time() * 1000),
    }
    try:
        r = requests.get(url, params=params, headers=SB_HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"[SportyBet] HTTP {r.status_code}")
            return []
        data = r.json()
        tournaments = data.get("data", {}).get("tournaments", []) or []
        events = []
        for t in tournaments:
            league = t.get("name", "")
            for ev in t.get("events", []) or []:
                home = ev.get("homeTeamName", "")
                away = ev.get("awayTeamName", "")
                if not home or not away:
                    continue
                if is_youth(home) or is_youth(away):
                    continue
                odds_h = odds_d = odds_a = 0
                odds_over25 = odds_btts = 0
                for m in ev.get("markets", []) or []:
                    mid = str(m.get("id", ""))
                    if mid == "1":
                        for o in m.get("outcomes", []) or []:
                            oid = str(o.get("id", ""))
                            try: price = float(o.get("odds", 0) or 0)
                            except Exception: price = 0
                            if oid == "1": odds_h = price
                            elif oid == "2": odds_d = price
                            elif oid == "3": odds_a = price
                    elif mid == "18":
                        for o in m.get("outcomes", []) or []:
                            if o.get("specifier") == "total=2.5" and str(o.get("id")) == "12":
                                try: odds_over25 = float(o.get("odds", 0) or 0)
                                except Exception: pass
                    elif mid == "29":
                        for o in m.get("outcomes", []) or []:
                            if str(o.get("id")) == "1":
                                try: odds_btts = float(o.get("odds", 0) or 0)
                                except Exception: pass

                kickoff_ms = ev.get("estimateStartTime", 0) or 0
                kickoff = datetime.utcfromtimestamp(kickoff_ms / 1000) if kickoff_ms else datetime.utcnow()
                wat = kickoff + timedelta(hours=1)

                events.append({
                    "eventId": ev.get("eventId", ""),
                    "home": home, "away": away, "league": league,
                    "date": wat.strftime("%Y-%m-%d"),
                    "time": wat.strftime("%H:%M"),
                    "country": "E0",
                    "odds_h": odds_h, "odds_d": odds_d, "odds_a": odds_a,
                    "odds_over25": odds_over25, "odds_btts": odds_btts,
                    "source": "SportyBet LIVE",
                })
        SB_EVENTS_CACHE = {"time": datetime.now(), "data": events}
        print(f"[SportyBet] fetched {len(events)} events")
        return events
    except Exception as e:
        print(f"[SportyBet] error: {e}")
        return []


def sb_book_bet(selections):
    url = "https://www.sportybet.com/api/ng/orders/share"
    try:
        r = requests.post(url, json={"selections": selections},
                          headers=SB_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[SportyBet book] HTTP {r.status_code}: {r.text[:300]}")
            return None
        data = r.json()
        if data.get("bizCode") != 10000:
            print(f"[SportyBet book] bizCode: {data.get('bizCode')}")
            return None
        d = data.get("data", {})
        return {
            "shareCode": d.get("shareCode", ""),
            "shareURL": d.get("shareURL", ""),
        }
    except Exception as e:
        print(f"[SportyBet book] error: {e}")
        return None


def market_to_sb_selection(pick_data, event_id):
    pick = pick_data.get("pick", "").lower()
    if "home win" in pick or "(1)" in pick:
        return {"eventId": event_id, "marketId": "1", "outcomeId": "1"}
    if "draw (x)" in pick or pick == "draw":
        return {"eventId": event_id, "marketId": "1", "outcomeId": "2"}
    if "away win" in pick or "(2)" in pick:
        return {"eventId": event_id, "marketId": "1", "outcomeId": "3"}
    if "(1x)" in pick:
        return {"eventId": event_id, "marketId": "10", "outcomeId": "1"}
    if "(12)" in pick:
        return {"eventId": event_id, "marketId": "10", "outcomeId": "2"}
    if "(x2)" in pick:
        return {"eventId": event_id, "marketId": "10", "outcomeId": "3"}
    if "btts yes" in pick:
        return {"eventId": event_id, "marketId": "29", "outcomeId": "1"}
    if "btts no" in pick:
        return {"eventId": event_id, "marketId": "29", "outcomeId": "2"}
    for line in ["1.5", "2.5", "3.5"]:
        if f"over {line}" in pick:
            return {"eventId": event_id, "marketId": "18",
                    "outcomeId": "12", "specifier": f"total={line}"}
        if f"under {line}" in pick:
            return {"eventId": event_id, "marketId": "18",
                    "outcomeId": "13", "specifier": f"total={line}"}
    return None


# ──────────────────────────────────────────────
# FOOTBALL.COM CONVERTER + DEEP LINKS
# ──────────────────────────────────────────────
def convert_sb_to_football(sb_code):
    """Convert SportyBet booking code to Football.com format."""
    if not sb_code:
        return None

    # BetRelay attempt
    try:
        r = requests.post("https://betrelay.com.ng/api/convert",
                          json={"from": "sportybet", "to": "football", "code": sb_code},
                          timeout=15)
        if r.status_code == 200:
            data = r.json()
            code = data.get("code") or data.get("converted_code") or data.get("result")
            if code:
                print(f"[BetRelay] {sb_code} → {code}")
                return code
    except Exception as e:
        print(f"[BetRelay] error: {e}")

    # Fallback
    try:
        r = requests.post("https://api.betconverter.app/convert",
                          json={"from": "sportybet", "to": "football.com", "code": sb_code},
                          timeout=12)
        if r.status_code == 200:
            data = r.json()
            code = data.get("code") or data.get("converted")
            if code:
                print(f"[betconverter] {sb_code} → {code}")
                return code
    except Exception as e:
        print(f"[betconverter] error: {e}")

    return None


def sportybet_load_url(sb_code):
    if not sb_code:
        return "https://www.sportybet.com/ng/sport/football"
    return f"https://www.sportybet.com/ng/#/share/booking/{sb_code}"


def football_com_load_url(fb_code):
    if not fb_code:
        return "https://www.football.com/en-ng/sports"
    return f"https://www.football.com/en-ng/sports#/booking/{fb_code}"


def betking_load_url():
    return "https://www.betking.com/sports"


def onexbet_load_url():
    return "https://1xbet.ng/en/line/football"


# ──────────────────────────────────────────────
# ACCUMULATOR BUILDER
# ──────────────────────────────────────────────
def safety_score(fixture, pred):
    score = pred["confidence"]
    if pred.get("edge", 0) >= 3:
        score += 5
    odds = pred["odds"]
    if 1.5 <= odds <= 2.5: score += 6
    elif 1.3 <= odds < 1.5: score += 3
    elif odds > 3.5: score -= 8
    league = fixture.get("league", "").lower()
    if any(k in league for k in TOP_LEAGUES):
        score += 8
    try:
        kick_dt = datetime.strptime(
            f"{fixture.get('date','')} {fixture.get('time','00:00')}",
            "%Y-%m-%d %H:%M")
        hours = (kick_dt - datetime.utcnow()).total_seconds() / 3600
        if 1 <= hours <= 12: score += 5
        elif 12 < hours <= 24: score += 3
        elif hours > 72: score -= 5
    except Exception:
        pass
    return score


def build_accumulator(fixtures, target_matches=20, min_odds=1.20, max_odds=3.50):
    scored = []
    for f in fixtures:
        try:
            pred = predict_match(f)
            best = pred["all_markets"][0] if pred["all_markets"] else None
            if not best:
                continue
            if best["odds"] < min_odds or best["odds"] > max_odds:
                alt = next((m for m in pred["all_markets"]
                            if min_odds <= m["odds"] <= max_odds and m["conf"] >= 55), None)
                if not alt:
                    continue
                best = alt
            sc = safety_score(f, {**pred, **best, "confidence": best["conf"]})
            scored.append({"fixture": f, "pred": pred, "pick": best, "safety": sc})
        except Exception:
            continue
    scored.sort(key=lambda x: x["safety"], reverse=True)

    selected = []
    league_count = defaultdict(int)
    used_teams = set()
    for item in scored:
        if len(selected) >= target_matches:
            break
        f = item["fixture"]
        league = f.get("league", "")
        home = f["home"]; away = f["away"]
        if home in used_teams or away in used_teams:
            continue
        if league_count[league] >= 3:
            continue
        selected.append(item)
        league_count[league] += 1
        used_teams.add(home); used_teams.add(away)
    return selected


# ──────────────────────────────────────────────
# PERSONALIZATION
# ──────────────────────────────────────────────
def update_user_preferences(db, user, fixture, market):
    try:
        fav_l = set((user.fav_leagues or "").split(",")) - {""}
        if fixture.get("league"):
            fav_l.add(fixture["league"])
        user.fav_leagues = ",".join(list(fav_l)[-10:])
        fav_m = set((user.fav_markets or "").split(",")) - {""}
        if market:
            fav_m.add(market)
        user.fav_markets = ",".join(list(fav_m)[-5:])
        db.commit()
    except Exception as e:
        print(f"Pref update error: {e}")


def score_fixture_for_user(fixture, user):
    score = 0
    fav_leagues = set((user.fav_leagues or "").split(",")) - {""}
    if fixture.get("league") in fav_leagues:
        score += 50
    league = fixture.get("league", "").lower()
    if any(k in league for k in TOP_LEAGUES):
        score += 20
    return score


# ──────────────────────────────────────────────
# ENGAGEMENT
# ──────────────────────────────────────────────
def get_user_stats(db, uid):
    try:
        user = get_user(db, uid)
        total = user.total_predictions or 0
        wins = user.total_wins or 0
        losses = user.total_losses or 0
        win_rate = round(wins / total * 100, 1) if total > 0 else 0
        return {
            "streak": user.streak, "best_streak": user.best_streak,
            "total": total, "wins": wins, "losses": losses,
            "win_rate": win_rate, "referrals": user.referral_count or 0,
            "n1m_bankroll": user.n1m_bankroll or 0.0,
            "n1m_best": user.n1m_best or 0.0,
            "bankroll": user.bankroll or 10000.0,
        }
    except Exception:
        return {"streak": 0, "best_streak": 0, "total": 0, "wins": 0,
                "losses": 0, "win_rate": 0, "referrals": 0,
                "n1m_bankroll": 0.0, "n1m_best": 0.0, "bankroll": 10000.0}


def award_referral(db, referrer_code, new_user_id):
    try:
        referrer = db.query(User).filter(User.referral_code == referrer_code).first()
        if not referrer:
            return
        existing = db.query(Referral).filter(
            Referral.referrer_id == referrer.user_id,
            Referral.referred_id == new_user_id).first()
        if existing:
            return
        db.add(Referral(referrer_id=referrer.user_id, referred_id=new_user_id, rewarded=True))
        referrer.referral_count = (referrer.referral_count or 0) + 1
        if referrer.is_vip and referrer.vip_expiry:
            try:
                current = datetime.strptime(referrer.vip_expiry, "%Y-%m-%d").date()
                new_expiry = current + timedelta(days=7)
            except Exception:
                new_expiry = date.today() + timedelta(days=7)
        else:
            referrer.is_vip = True
            new_expiry = date.today() + timedelta(days=7)
        referrer.vip_expiry = str(new_expiry)
        db.commit()
        send_message(referrer.user_id,
                     f"🎁 Referral Reward! +7 VIP days. Valid until {new_expiry}",
                     reply_markup=get_main_keyboard(is_admin(referrer.user_id)))
    except Exception as e:
        print(f"Referral error: {e}")


# ──────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────
app = FastAPI()


def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"[send_message] HTTP {r.status_code}: {r.text[:300]}")
        if parse_mode:
            payload.pop("parse_mode", None)
            clean = text.replace("*", "").replace("_", " ").replace("`", "")
            payload["text"] = clean
            r2 = requests.post(url, json=payload, timeout=15)
            if r2.status_code == 200:
                return r2.json()
        return r.json() if r.content else None
    except Exception as e:
        print(f"[send_message] Exception: {e}")
        return None


def set_bot_menu():
    commands = [
        {"command": "today", "description": "Today's top fixtures"},
        {"command": "europeanleagues", "description": "European leagues"},
        {"command": "asianleagues", "description": "Asian leagues"},
        {"command": "americanleagues", "description": "American leagues"},
        {"command": "national", "description": "FIFA / national teams"},
        {"command": "accumulator", "description": "20-match accumulator + codes"},
        {"command": "million", "description": "N1M challenge"},
        {"command": "stats", "description": "Your stats"},
        {"command": "leaderboard", "description": "Top users"},
        {"command": "refer", "description": "Refer friends"},
        {"command": "profile", "description": "Your profile"},
        {"command": "upgrade", "description": "Upgrade to VIP"},
        {"command": "help", "description": "Help"},
        {"command": "start", "description": "Start"},
    ]
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
                      json={"commands": commands}, timeout=10)
    except Exception:
        pass


# ──────────────────────────────────────────────
# REGION HANDLER
# ──────────────────────────────────────────────
REGION_INFO = {
    "european": ("🇪🇺 EUROPEAN LEAGUES", "European"),
    "asian": ("🇯🇵 ASIAN LEAGUES", "Asian"),
    "american": ("🇺🇸 AMERICAN LEAGUES", "American"),
    "national": ("🌍 NATIONAL TEAMS / FIFA", "National"),
}


def handle_region(chat_id, user_id, region, user, db, limit):
    header, pretty = REGION_INFO.get(region, ("FIXTURES", region.title()))
    kb = get_main_keyboard(is_admin(user_id))
    if user.daily_count >= limit:
        send_message(chat_id, f"🚫 Daily limit {user.daily_count}/{limit}\n"
                              f"Upgrade: {RENDER_URL}/subscribe?uid={user_id}",
                     reply_markup=kb)
        return
    send_message(chat_id, f"🔎 Scanning {pretty} fixtures...", reply_markup=kb)
    fixtures = fetch_real_fixtures(days_ahead=0, limit=15, region=region)
    if not fixtures:
        for i in range(1, 8):
            fixtures = fetch_real_fixtures(days_ahead=i, limit=15, region=region)
            if fixtures:
                break
    if not fixtures:
        send_message(chat_id, f"No {pretty} fixtures.\n{BOT_LINK}", reply_markup=kb)
        return
    scored = [(f, score_fixture_for_user(f, user)) for f in fixtures]
    scored.sort(key=lambda x: x[1], reverse=True)
    fixtures = [f for f, _ in scored]
    msg = f"{header}\n📅 {fixtures[0].get('date', 'Today')}\n\n"
    for i, f in enumerate(fixtures[:10], 1):
        msg += f"{i}. {f['home']} vs {f['away']}\n   🏆 {f.get('league', '')} · {f.get('time', '')}\n\n"
    msg += f"({user.daily_count}/{limit}) Tap below"
    inline_kb = {"inline_keyboard": [
        [{"text": "🧠 Analyze Top 5 Matches", "callback_data": f"predict_{region}"}],
        [{"text": "🎫 20-Match Accumulator", "callback_data": "build_accumulator"}],
    ]}
    send_message(chat_id, msg, reply_markup=inline_kb)


def format_full_prediction(chat_id, fixture, show_all_markets=True):
    p = predict_match(fixture)
    mt = p.get("market_table", {})
    sa = stake_advice(p["confidence"])

    msg = (
        f"⚽ {fixture['home']} vs {fixture['away']}\n"
        f"🏆 {fixture.get('league','')} | {fixture.get('time','')} WAT\n\n"
        f"📊 {p['form']}\n"
        f"📈 {p['h2h']}\n\n"
        f"🏆 SAFEST PICK\n"
        f"✅ {p['best_pick']}\n"
        f"   @ {p['odds']} · {p['confidence']}% conf"
    )
    if p.get("edge", 0) > 0:
        msg += f" · +{p['edge']}% edge"
    msg += f"\n   💰 Stake: {sa['percent']}% (N{sa['amount']} of N10,000)\n"

    if show_all_markets:
        msg += (
            "\n📋 ALL MARKET PROBABILITIES\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏠 Home Win: {mt.get('1',0):.1f}%  |  🤝 Draw: {mt.get('X',0):.1f}%  |  ✈️ Away: {mt.get('2',0):.1f}%\n"
            f"🎯 1X: {mt.get('1X',0):.1f}%  |  X2: {mt.get('X2',0):.1f}%  |  12: {mt.get('12',0):.1f}%\n"
            f"⚽ BTTS Y: {mt.get('BTTS Yes',0):.1f}%  |  N: {mt.get('BTTS No',0):.1f}%\n"
            f"🥅 O1.5: {mt.get('Over 1.5',0):.1f}%  |  O2.5: {mt.get('Over 2.5',0):.1f}%  |  O3.5: {mt.get('Over 3.5',0):.1f}%\n"
        )

    if p.get("value_bets"):
        msg += "\n💎 VALUE BETS:\n"
        for v in p["value_bets"][:2]:
            msg += f"   • {v['pick']} @ {v['odds']} (+{v['edge']}% edge)\n"

    send_message(chat_id, msg)


def handle_analyze_top5(chat_id, user, db, region=None):
    limit = 999999 if is_admin(user.user_id) else (10 if user.is_vip else 2)
    if not is_admin(user.user_id) and user.daily_count >= limit:
        send_message(chat_id, f"🚫 Daily limit {user.daily_count}/{limit}\n"
                              f"Upgrade: {RENDER_URL}/subscribe?uid={user.user_id}")
        return

    if region:
        fixtures = fetch_real_fixtures(days_ahead=0, limit=5, region=region)
        if not fixtures:
            for i in range(1, 8):
                fixtures = fetch_real_fixtures(days_ahead=i, limit=5, region=region)
                if fixtures:
                    break
    else:
        fixtures = fetch_real_fixtures(days_ahead=0, limit=5)

    if not fixtures:
        send_message(chat_id, f"No fixtures found.\n{BOT_LINK}")
        return

    ranked = []
    for f in fixtures:
        pred = predict_match(f)
        s = safety_score(f, pred)
        ranked.append((s, f, pred))
    ranked.sort(key=lambda x: x[0], reverse=True)

    is_vip = user.is_vip or is_admin(user.user_id)
    visible = 5 if is_vip else 2
    hidden_count = len(ranked) - visible

    send_message(chat_id, f"🧠 Analyzing Top {len(ranked)} matches...")

    for i, (_, f, _) in enumerate(ranked[:visible], 1):
        send_message(chat_id, f"━━━ #{i} ━━━")
        format_full_prediction(chat_id, f, show_all_markets=is_vip)
        user.daily_count += 1
        db.commit()
        time.sleep(0.6)

    if not is_vip and hidden_count > 0:
        send_message(chat_id, (
            f"🔒 {hidden_count} more predictions hidden for VIP members.\n\n"
            f"💎 VIP unlocks:\n"
            f"✅ All 5 daily predictions (not just 2)\n"
            f"✅ 🎫 20-match Accumulator with real booking codes\n"
            f"✅ 🚀 N1M Challenge\n"
            f"✅ Full 13-market probabilities\n"
            f"✅ Bankroll advisor + value-bet alerts\n\n"
            f"👉 Upgrade: {RENDER_URL}/subscribe?uid={user.user_id}"
        ))
    else:
        send_message(chat_id,
                     f"💎 Want a 20-match accumulator?\nTap 🎫 Accumulator or /accumulator")


# ──────────────────────────────────────────────
# ACCUMULATOR HANDLER
# ──────────────────────────────────────────────
def handle_accumulator(chat_id, user, db):
    if not user.is_vip and not is_admin(user.user_id):
        send_message(chat_id, (
            f"🎫 20-Match Accumulator — VIP Only\n\n"
            f"Build the smartest 20-match accumulator:\n"
            f"✅ Ranked by form, standings, league tier\n"
            f"✅ Real SportyBet booking code (loads in one tap)\n"
            f"✅ Football.com + BetKing deep links\n"
            f"✅ Bankroll advisor per leg\n\n"
            f"👉 Upgrade: {RENDER_URL}/subscribe?uid={user.user_id}"
        ), reply_markup=get_main_keyboard(False))
        return

    send_message(chat_id, "🎫 Building your 20-match accumulator...\nThis takes ~30 seconds.")

    pool = sb_fetch_events(timeline_hours=72, page_size=100)
    if not pool or len(pool) < 10:
        pool = fetch_real_fixtures(days_ahead=0, limit=60)
        if len(pool) < 10:
            for i in range(1, 5):
                extra = fetch_real_fixtures(days_ahead=i, limit=60)
                exist = {f"{x['home']}-{x['away']}" for x in pool}
                for ef in extra:
                    if f"{ef['home']}-{ef['away']}" not in exist:
                        pool.append(ef)
                if len(pool) >= 40:
                    break

    if len(pool) < 8:
        send_message(chat_id, f"Not enough fixtures ({len(pool)}). Try later.")
        return

    selected = build_accumulator(pool, target_matches=20)
    if len(selected) < 5:
        send_message(chat_id, "Could not build a safe accumulator today. Try later.")
        return

    msg_parts = [
        "🎫 YOUR 20-MATCH ACCUMULATOR",
        f"📅 {datetime.now().strftime('%d %b %Y')}",
        "",
    ]

    total_odds = 1.0
    sb_selections = []
    sendable_picks = []

    for i, item in enumerate(selected, 1):
        f = item["fixture"]
        pick = item["pick"]
        total_odds *= float(pick["odds"])
        sa = stake_advice(pick["conf"])

        msg_parts.append(
            f"{i}. {f['home']} vs {f['away']}\n"
            f"   🏆 {f.get('league','')} · {f.get('time','')}\n"
            f"   ✅ {pick['pick']} @ {pick['odds']} ({pick['conf']}%)\n"
            f"   💰 Stake: {sa['percent']}%"
        )

        if f.get("eventId"):
            sel = market_to_sb_selection(pick, f["eventId"])
            if sel:
                sb_selections.append(sel)

        sendable_picks.append({
            "match": f"{f['home']} vs {f['away']}",
            "league": f.get("league", ""),
            "pick": pick["pick"], "odds": pick["odds"], "conf": pick["conf"],
        })

    total_odds = round(total_odds, 2)
    potential_win = round(total_odds * 1000, 2)

    msg_parts.append("")
    msg_parts.append(f"📊 TOTAL ODDS: {total_odds}")
    msg_parts.append(f"💰 N1,000 → N{potential_win:,.0f}")
    msg_parts.append("")

    # Generate booking codes
    sb_code = None
    sb_url = None
    fb_code = None

    if sb_selections and len(sb_selections) >= 2:
        booking = sb_book_bet(sb_selections[:20])
        if booking and booking.get("shareCode"):
            sb_code = booking["shareCode"]
            sb_url = booking.get("shareURL") or sportybet_load_url(sb_code)

    if sb_code:
        fb_code = convert_sb_to_football(sb_code)

    # Bookmaker section
    msg_parts.append("🎟 LOAD YOUR BETSLIP INSTANTLY")
    msg_parts.append("━━━━━━━━━━━━━━━━━━━━━━")

    if sb_code:
        msg_parts.append(
            f"🟢 SPORTYBET\n"
            f"   Code: {sb_code}\n"
            f"   👉 {sb_url}"
        )
    else:
        msg_parts.append("🟢 SPORTYBET: code unavailable — use list above manually")

    if fb_code:
        msg_parts.append(
            f"\n🔵 FOOTBALL.COM\n"
            f"   Code: {fb_code}\n"
            f"   👉 {football_com_load_url(fb_code)}"
        )
    elif sb_code:
        msg_parts.append(
            f"\n🔵 FOOTBALL.COM\n"
            f"   Convert your SportyBet code {sb_code} at:\n"
            f"   https://betrelay.com.ng/sportybet-to-football"
        )
    else:
        msg_parts.append(f"\n🔵 FOOTBALL.COM: https://www.football.com/en-ng/sports")

    msg_parts.append(
        f"\n🟡 BETKING\n"
        f"   👉 {betking_load_url()}\n"
        f"   (Copy picks from list above)"
    )
    msg_parts.append(
        f"\n🔴 1XBET\n"
        f"   👉 {onexbet_load_url()}"
    )

    msg_parts.append("")
    msg_parts.append("⚠️ High-odds accumulator. Bet responsibly. 18+")

    full_msg = "\n".join(msg_parts)

    if len(full_msg) > 4000:
        code_section = "\n".join(msg_parts[-14:])
        body = "\n".join(msg_parts[:-14])
        send_message(chat_id, body)
        time.sleep(0.5)
        full_msg = code_section

    send_message(chat_id, full_msg, reply_markup=get_main_keyboard(is_admin(user.user_id)))

    try:
        for sp in sendable_picks:
            db.add(Prediction(
                user_id=user.user_id, match=sp["match"], league=sp["league"],
                market="ACCUMULATOR", pick=sp["pick"], odds=sp["odds"],
                confidence=sp["conf"], match_date=str(date.today()),
            ))
        db.commit()
    except Exception as e:
        print(f"Acca log error: {e}")


# ──────────────────────────────────────────────
# ADMIN HANDLERS
# ──────────────────────────────────────────────
def handle_admin_panel(chat_id, user):
    db = SessionLocal()
    try:
        total_users = db.query(User).count()
        total_vip = db.query(User).filter(User.is_vip == True).count()
        total_preds = db.query(Prediction).count()
    except Exception:
        total_users = total_vip = total_preds = 0
    finally:
        db.close()
    send_message(chat_id, (
        f"🔐 ADMIN PANEL\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Users: {total_users} (VIP: {total_vip})\n"
        f"Predictions: {total_preds}\n"
        f"Brain: {len(HISTORICAL_STATS)} teams · H2H {len(H2H_CACHE)}\n"
        f"SportyBet cache: {len(SB_EVENTS_CACHE.get('data', []))}\n\n"
        f"/admin_stats /admin_users /admin_user <uid>\n"
        f"/admin_grant <uid> <plan> /admin_revoke <uid>\n"
        f"/admin_broadcast <msg> /admin_channels\n\n"
        f"Admin ID: {user.user_id}"
    ), reply_markup=get_main_keyboard(True))


def handle_admin_stats(chat_id):
    db = SessionLocal()
    try:
        total_users = db.query(User).count()
        total_vip = db.query(User).filter(User.is_vip == True).count()
        total_preds = db.query(Prediction).count()
        week_ago = datetime.utcnow() - timedelta(days=7)
        new_this_week = db.query(User).filter(User.created_at >= week_ago).count()
        top_pred = db.query(User).order_by(User.total_predictions.desc()).first()
        top_ref = db.query(User).order_by(User.referral_count.desc()).first()
        msg = (f"📊 GLOBAL STATS\n\n"
               f"Users: {total_users} (VIP: {total_vip})\n"
               f"New (7d): {new_this_week}\n"
               f"Predictions: {total_preds}\n"
               f"Brain teams: {len(HISTORICAL_STATS)}\n")
        if top_pred:
            msg += f"\nTop: {top_pred.first_name or top_pred.user_id} ({top_pred.total_predictions})"
        if top_ref:
            msg += f"\nTop ref: {top_ref.first_name or top_ref.user_id} ({top_ref.referral_count})"
        send_message(chat_id, msg, reply_markup=get_main_keyboard(True))
    except Exception as e:
        send_message(chat_id, f"Error: {e}")
    finally:
        db.close()


def handle_admin_users(chat_id, page=0):
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.last_seen.desc())\
            .offset(page * 20).limit(20).all()
        if not users:
            send_message(chat_id, "No users.", reply_markup=get_main_keyboard(True))
            return
        msg = f"👥 USERS (page {page+1})\n\n"
        for u in users:
            tier = "💎" if u.is_vip else "🆓"
            name = (u.first_name or u.username or f"User{u.user_id}")[:20]
            msg += f"{tier} {name} · ID:{u.user_id} · {u.daily_count}/day\n"
        kb = {"inline_keyboard": [[
            {"text": "⬅️ Prev", "callback_data": f"admin_users_{max(0,page-1)}"},
            {"text": "Next ➡️", "callback_data": f"admin_users_{page+1}"},
        ]]}
        send_message(chat_id, msg, reply_markup=kb)
    except Exception as e:
        send_message(chat_id, f"Error: {e}")
    finally:
        db.close()


def handle_admin_user_lookup(chat_id, uid):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.user_id == uid).first()
        if not u:
            send_message(chat_id, f"❌ {uid} not found.", reply_markup=get_main_keyboard(True))
            return
        send_message(chat_id, (
            f"🔍 USER {uid}\n\n"
            f"Name: {u.first_name or '—'}\n"
            f"Username: @{u.username or '—'}\n"
            f"Tier: {'VIP' if u.is_vip else 'FREE'}\n"
            f"VIP until: {u.vip_expiry or '—'}\n"
            f"Predictions: {u.total_predictions or 0}\n"
            f"Referrals: {u.referral_count or 0}"
        ), reply_markup=get_main_keyboard(True))
    except Exception as e:
        send_message(chat_id, f"Error: {e}")
    finally:
        db.close()


def handle_admin_grant(chat_id, uid, plan):
    if plan not in ("daily", "weekly", "monthly"):
        send_message(chat_id, f"❌ Invalid plan: {plan}", reply_markup=get_main_keyboard(True))
        return
    if activate_vip(uid, plan, silent=False):
        send_message(chat_id, f"✅ Granted {plan} to {uid}", reply_markup=get_main_keyboard(True))
    else:
        send_message(chat_id, f"❌ Failed", reply_markup=get_main_keyboard(True))


def handle_admin_revoke(chat_id, uid):
    if revoke_vip(uid):
        send_message(chat_id, f"✅ Revoked {uid}", reply_markup=get_main_keyboard(True))
    else:
        send_message(chat_id, f"❌ Failed", reply_markup=get_main_keyboard(True))


def handle_admin_broadcast(chat_id, message):
    db = SessionLocal()
    try:
        users = db.query(User).all()
    finally:
        db.close()
    send_message(chat_id, f"📢 Broadcasting to {len(users)}...")
    sent = 0
    for u in users:
        try:
            r = send_message(u.user_id, f"📢 ANNOUNCEMENT\n\n{message}")
            if r and r.get("ok"):
                sent += 1
            time.sleep(0.05)
        except Exception:
            pass
    send_message(chat_id, f"✅ Sent to {sent}/{len(users)}", reply_markup=get_main_keyboard(True))


def handle_admin_test_channel(chat_id):
    if not CHANNEL_ID:
        send_message(chat_id, "❌ CHANNEL_ID not set.", reply_markup=get_main_keyboard(True))
        return
    r = send_message(CHANNEL_ID, f"🧪 Test\n{BOT_LINK}")
    send_message(chat_id, f"Sent: {bool(r and r.get('ok'))}", reply_markup=get_main_keyboard(True))


# ──────────────────────────────────────────────
# N1M HANDLER
# ──────────────────────────────────────────────
def handle_n1m(chat_id, user, db):
    kb = get_main_keyboard(is_admin(user.user_id))
    if not user.is_vip and not is_admin(user.user_id):
        send_message(chat_id,
                     f"🚀 N1M Challenge — VIP Only\n\n👉 {RENDER_URL}/subscribe?uid={user.user_id}",
                     reply_markup=kb)
        return
    send_message(chat_id, "🚀 Building your N1M slip...", reply_markup=kb)
    pool = sb_fetch_events(timeline_hours=72) or fetch_real_fixtures(days_ahead=0, limit=40)
    if len(pool) < 8:
        for i in range(1, 5):
            extra = fetch_real_fixtures(days_ahead=i, limit=40)
            exist = {f"{x['home']}-{x['away']}" for x in pool}
            for ef in extra:
                if f"{ef['home']}-{ef['away']}" not in exist:
                    pool.append(ef)
            if len(pool) >= 20:
                break
    if len(pool) < 8:
        send_message(chat_id, f"Not enough fixtures ({len(pool)}).", reply_markup=kb)
        return

    selected = build_accumulator(pool, target_matches=20)
    picks = []
    total_odds = 1.0
    for item in selected:
        f = item["fixture"]; p = item["pick"]
        total_odds *= float(p["odds"])
        picks.append({"match": f"{f['home']} vs {f['away']}", "pick": p["pick"],
                      "odds": p["odds"], "conf": p["conf"]})

    total_odds = round(total_odds, 2)
    pot_win = round(1000 * total_odds, 2)
    user.n1m_bankroll = 1000
    if pot_win > (user.n1m_best or 0):
        user.n1m_best = pot_win
    db.commit()

    msg = (f"🚀 N1M CHALLENGE\n\n"
           f"💰 Stake: N1,000\n🎯 Target: N1,000,000\n"
           f"📊 Total odds: {total_odds}\n💵 Potential: N{pot_win:,.0f}\n\n")
    for i, p in enumerate(picks[:20], 1):
        msg += f"{i}. {p['match']}\n   {p['pick']} @ {p['odds']} ({p['conf']}%)\n"
    msg += f"\n⚠️ High-risk. Bet responsibly.\n{BOT_LINK}"
    send_message(chat_id, msg, reply_markup=kb)


# ──────────────────────────────────────────────
# BUTTON ROUTER
# ──────────────────────────────────────────────
def map_button_to_command(text, admin):
    low = text.strip().lower()
    if "today" in low and "fixture" in low:
        return "/today"
    if "n1m" in low or "challenge" in low:
        return "/million"
    if "european" in low:
        return "/europeanleagues"
    if "asian" in low:
        return "/asianleagues"
    if "american" in low:
        return "/americanleagues"
    if "accumulator" in low:
        return "/accumulator"
    if admin and "admin" in low and "panel" in low:
        return "/admin"
    return None


# ──────────────────────────────────────────────
# UPDATE PROCESSOR
# ──────────────────────────────────────────────
def process_update(upd):
    try:
        base = f"https://api.telegram.org/bot{BOT_TOKEN}"

        # Callbacks
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            from_id = cq["from"]["id"]
            data = cq.get("data", "")
            admin = is_admin(from_id)
            requests.post(f"{base}/answerCallbackQuery",
                          json={"callback_query_id": cq["id"], "text": "Working..."},
                          timeout=5)

            if data.startswith("admin_users_") and admin:
                try:
                    page = int(data.replace("admin_users_", ""))
                except Exception:
                    page = 0
                handle_admin_users(chat_id, page)
                return

            db2 = SessionLocal()
            try:
                user2 = get_user(db2, from_id,
                                 cq["from"].get("username", ""),
                                 cq["from"].get("first_name", ""))
                if data.startswith("predict_"):
                    region = data.replace("predict_", "")
                    handle_analyze_top5(chat_id, user2, db2, region=region)
                elif data == "predict_top5":
                    handle_analyze_top5(chat_id, user2, db2, region=None)
                elif data == "build_accumulator":
                    handle_accumulator(chat_id, user2, db2)
                elif data in ("n1m_challenge", "n1m_regen"):
                    handle_n1m(chat_id, user2, db2)
            finally:
                db2.close()
            return

        # Messages
        msg = upd.get("message")
        if not msg or "text" not in msg or msg["chat"]["type"] != "private":
            return

        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        user_id = msg["from"]["id"]
        username = msg["from"].get("username", "")
        first_name = msg["from"].get("first_name", "")
        low = text.lower()
        admin = is_admin(user_id)
        main_kb = get_main_keyboard(admin)

        mapped = map_button_to_command(text, admin)
        if mapped:
            low = mapped.lower()
            text = mapped

        db = SessionLocal()
        try:
            user = get_user(db, user_id, username, first_name)
            FREE, VIP = 2, 10
            cur = 999999 if admin else (VIP if user.is_vip else FREE)

            # Admin
            if low.startswith("/admin") and admin:
                parts = text.split(maxsplit=2)
                subcmd = parts[0].lower()
                if subcmd == "/admin" or low.strip() == "/admin":
                    handle_admin_panel(chat_id, user)
                elif subcmd == "/admin_stats":
                    handle_admin_stats(chat_id)
                elif subcmd == "/admin_users":
                    handle_admin_users(chat_id, 0)
                elif subcmd == "/admin_user" and len(parts) >= 2:
                    try: handle_admin_user_lookup(chat_id, int(parts[1]))
                    except Exception: send_message(chat_id, "Usage: /admin_user <uid>", reply_markup=main_kb)
                elif subcmd == "/admin_grant" and len(parts) >= 3:
                    try: handle_admin_grant(chat_id, int(parts[1]), parts[2].lower())
                    except Exception: send_message(chat_id, "Usage: /admin_grant <uid> <plan>", reply_markup=main_kb)
                elif subcmd == "/admin_revoke" and len(parts) >= 2:
                    try: handle_admin_revoke(chat_id, int(parts[1]))
                    except Exception: send_message(chat_id, "Usage: /admin_revoke <uid>", reply_markup=main_kb)
                elif subcmd == "/admin_broadcast":
                    bmsg = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
                    if bmsg:
                        threading.Thread(target=handle_admin_broadcast,
                                         args=(chat_id, bmsg), daemon=True).start()
                    else:
                        send_message(chat_id, "Usage: /admin_broadcast <msg>", reply_markup=main_kb)
                elif subcmd == "/admin_channels":
                    handle_admin_test_channel(chat_id)
                else:
                    send_message(chat_id, "Unknown admin cmd. Use /admin", reply_markup=main_kb)
                return

            if low.startswith("/admin"):
                send_message(chat_id, "⛔ Admin access required.", reply_markup=main_kb)
                return

            if low.startswith("/start") and "ref_" in low:
                try:
                    ref_code = text.split("ref_")[1].split()[0].strip()
                    if ref_code and user.referred_by != ref_code:
                        user.referred_by = ref_code
                        db.commit()
                except Exception:
                    pass

            if low.startswith("/start"):
                tier = "🔐 ADMIN" if admin else ("💎 VIP" if user.is_vip else "🆓 FREE")
                admin_line = "\n🔐 ADMIN — tap 🔐 Admin Panel.\n" if admin else ""
                send_message(chat_id, (
                    f"👋 Welcome to BetMaster Pro, {first_name or 'friend'}!\n\n"
                    f"🧠 Dixon-Coles AI · 13 markets\n"
                    f"🌍 Europe · Asia · Americas · National\n"
                    f"🎫 Real SportyBet + Football.com codes\n"
                    f"🚀 N1M Challenge\n"
                    f"{admin_line}\n"
                    f"Tier: {tier}\n"
                    f"Limit: {'∞' if admin else user.daily_count}/{cur if not admin else '∞'}\n\n"
                    f"👇 Use the menu below\n\n"
                    f"VIP: /accumulator /million\n"
                    f"FREE: /today /europeanleagues /asianleagues /americanleagues /national\n"
                    f"Account: /stats /leaderboard /refer /profile /upgrade /help\n\n"
                    f"Or send: Team A vs Team B\n\n{BOT_LINK}"
                ), reply_markup=main_kb)

            elif low.startswith("/help"):
                admin_line = ("\n🔐 Admin:\n/admin /admin_stats /admin_users\n"
                              "/admin_grant /admin_revoke /admin_broadcast\n") if admin else ""
                send_message(chat_id, (
                    f"📖 Help\n\n"
                    f"VIP: /accumulator /million\n"
                    f"Fixtures: /today /europeanleagues /asianleagues /americanleagues /national\n"
                    f"Account: /stats /leaderboard /refer /profile /upgrade\n"
                    f"{admin_line}\n"
                    f"FREE {FREE}/day · VIP {VIP}/day\n{BOT_LINK}"
                ), reply_markup=main_kb)

            elif low.startswith("/europeanleagues"):
                handle_region(chat_id, user_id, "european", user, db, cur)
            elif low.startswith("/asianleagues"):
                handle_region(chat_id, user_id, "asian", user, db, cur)
            elif low.startswith("/americanleagues"):
                handle_region(chat_id, user_id, "american", user, db, cur)
            elif low.startswith("/national"):
                handle_region(chat_id, user_id, "national", user, db, cur)

            elif low.startswith("/accumulator"):
                handle_accumulator(chat_id, user, db)

            elif low.startswith("/million") or low.startswith("/m1"):
                handle_n1m(chat_id, user, db)

            elif low.startswith("/today"):
                if not admin and user.daily_count >= cur:
                    send_message(chat_id, f"🚫 Limit {user.daily_count}/{cur}\n"
                                          f"{RENDER_URL}/subscribe?uid={user_id}",
                                 reply_markup=main_kb)
                    return
                send_message(chat_id, "🔎 Scanning today's fixtures...", reply_markup=main_kb)
                fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
                if not fixtures:
                    send_message(chat_id, f"No fixtures today.\n{BOT_LINK}", reply_markup=main_kb)
                    return
                scored = [(f, score_fixture_for_user(f, user)) for f in fixtures]
                scored.sort(key=lambda x: x[1], reverse=True)
                fixtures = [f for f, _ in scored][:10]
                msg_txt = f"⚽ TOP FIXTURES — {fixtures[0].get('date', 'Today')}\n\n"
                for i, f in enumerate(fixtures, 1):
                    star = "⭐ " if score_fixture_for_user(f, user) >= 50 else ""
                    msg_txt += f"{i}. {star}{f['home']} vs {f['away']}\n   🏆 {f.get('league','')} · {f.get('time','')}\n\n"
                msg_txt += f"({user.daily_count}/{cur if not admin else '∞'}) Tap below"
                inline_kb = {"inline_keyboard": [
                    [{"text": "🧠 Analyze Top 5 Matches", "callback_data": "predict_top5"}],
                    [{"text": "🎫 20-Match Accumulator", "callback_data": "build_accumulator"}],
                ]}
                send_message(chat_id, msg_txt, reply_markup=inline_kb)

            elif low.startswith("/betslip"):
                if not user.is_vip and not admin:
                    send_message(chat_id, f"💎 VIP only.\n{RENDER_URL}/subscribe?uid={user_id}",
                                 reply_markup=main_kb)
                    return
                handle_accumulator(chat_id, user, db)

            elif low.startswith("/stats"):
                stats = get_user_stats(db, user_id)
                admin_line = "\n🔐 ADMIN" if admin else ""
                send_message(chat_id, (
                    f"📊 Stats{admin_line}\n\n"
                    f"🔥 Streak: {stats['streak']} (best {stats['best_streak']})\n"
                    f"🎯 Predictions: {stats['total']}\n"
                    f"✅ {stats['wins']}W / ❌ {stats['losses']}L\n"
                    f"📈 Win rate: {stats['win_rate']}%\n\n"
                    f"💰 Bankroll: N{stats['bankroll']:.0f}\n"
                    f"🎁 Referrals: {stats['referrals']}\n"
                    f"🚀 N1M: N{stats['n1m_bankroll']:.0f}"
                ), reply_markup=main_kb)

            elif low.startswith("/leaderboard"):
                try:
                    top = db.query(User).filter(User.total_predictions >= 5)\
                        .order_by(User.total_wins.desc()).limit(10).all()
                except Exception:
                    top = []
                msg_txt = "🏆 Leaderboard\n\n"
                if not top:
                    msg_txt += "No stats yet."
                else:
                    for i, u in enumerate(top, 1):
                        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
                        name = u.first_name or u.username or f"User{u.user_id}"
                        rate = round(u.total_wins / max(u.total_predictions, 1) * 100, 0)
                        msg_txt += f"{medal} {name} — {u.total_wins}W · {rate:.0f}%\n"
                send_message(chat_id, msg_txt, reply_markup=main_kb)

            elif low.startswith("/refer"):
                ref_link = f"https://t.me/Betmasterpro_bot?start=ref_{user.referral_code}"
                send_message(chat_id, (
                    f"🎁 Refer Friends\n\n"
                    f"Link: {ref_link}\n\n"
                    f"You get 7 free VIP days per paying referral.\n"
                    f"Referrals: {user.referral_count or 0}"
                ), reply_markup=main_kb)

            elif low.startswith("/profile"):
                stats = get_user_stats(db, user_id)
                tier = "🔐 ADMIN" if admin else ("💎 VIP" if user.is_vip else "🆓 FREE")
                exp = user.vip_expiry if user.is_vip else "—"
                send_message(chat_id, (
                    f"👤 Profile\n\n"
                    f"Name: {first_name or username or 'Anon'}\n"
                    f"Tier: {tier}\n"
                    f"VIP until: {exp}\n"
                    f"Daily used: {user.daily_count}/{cur if not admin else '∞'}\n\n"
                    f"📊 Streak {stats['streak']} · {stats['win_rate']}% win rate\n"
                    f"⭐ Fav: {user.fav_leagues or 'None'}"
                ), reply_markup=main_kb)

            elif low.startswith("/upgrade"):
                if admin:
                    send_message(chat_id, "🔐 ADMIN — full access.", reply_markup=main_kb)
                    return
                send_message(chat_id, (
                    f"💎 VIP Benefits\n\n"
                    f"✅ 10 predictions/day (vs FREE 2)\n"
                    f"✅ 🎫 20-match Accumulator with real SportyBet + Football.com codes\n"
                    f"✅ 🚀 N1M Challenge\n"
                    f"✅ Full 13-market probabilities\n"
                    f"✅ Value-bet alerts + bankroll advisor\n\n"
                    f"Plans:\n"
                    f"• Daily — N500\n• Weekly — N2,000\n• Monthly — N5,000\n\n"
                    f"👉 {RENDER_URL}/subscribe?uid={user_id}"
                ), reply_markup=main_kb)

            elif " vs " in low and 5 < len(text) < 100:
                if not admin and user.daily_count >= cur:
                    send_message(chat_id, f"🚫 Limit {user.daily_count}/{cur}\n"
                                          f"{RENDER_URL}/subscribe?uid={user_id}",
                                 reply_markup=main_kb)
                    return
                try:
                    parts = re.split(r"\s+vs\s+", text, flags=re.IGNORECASE)
                    home = parts[0].strip().title()
                    away = parts[1].strip().title()
                except Exception:
                    send_message(chat_id, "Format: Team A vs Team B", reply_markup=main_kb)
                    return
                all_f = fetch_real_fixtures(days_ahead=0, limit=100)
                matched = next((f for f in all_f
                                if home.lower() in f["home"].lower()
                                and away.lower() in f["away"].lower()), None)
                if not matched:
                    matched = next((f for f in all_f
                                    if away.lower() in f["home"].lower()
                                    and home.lower() in f["away"].lower()), None)
                data = matched or {
                    "home": home, "away": away, "league": "Custom",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "odds_h": 0, "odds_d": 0, "odds_a": 0,
                    "odds_over25": 0, "odds_btts": 0, "source": "Model",
                }
                format_full_prediction(chat_id, data, show_all_markets=(user.is_vip or admin))
                user.daily_count += 1
                db.commit()

            else:
                send_message(chat_id, f"Unknown command. /help\n{BOT_LINK}", reply_markup=main_kb)

        except Exception as e:
            print(f"Handler error: {e}")
            traceback.print_exc()
            db.rollback()
        finally:
            db.close()

    except Exception as outer:
        print(f"Outer error: {outer}")
        traceback.print_exc()


# ──────────────────────────────────────────────
# SCHEDULER
# ──────────────────────────────────────────────
def channel_scheduler():
    posted_today = set()
    while True:
        try:
            now_wat = datetime.utcnow() + timedelta(hours=1)
            hm = now_wat.strftime("%H:%M")
            today_str = now_wat.strftime("%Y-%m-%d")

            if hm == "08:00" and f"{today_str}-8am" not in posted_today and CHANNEL_ID:
                try:
                    pool = sb_fetch_events(timeline_hours=24, page_size=60)
                    if not pool:
                        pool = fetch_real_fixtures(days_ahead=0, limit=30)
                    if pool:
                        ranked = []
                        for f in pool[:30]:
                            try:
                                p = predict_match(f)
                                s = safety_score(f, p)
                                ranked.append((s, f, p))
                            except Exception:
                                continue
                        ranked.sort(key=lambda x: x[0], reverse=True)

                        msg = f"🎯 TOP 2 FREE PICKS — {today_str}\n\n"
                        for i, (_, f, p) in enumerate(ranked[:2], 1):
                            msg += (f"{i}. {f['home']} vs {f['away']}\n"
                                    f"   🏆 {f.get('league','')} · {f.get('time','')}\n"
                                    f"   ✅ {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n\n")
                        msg += (
                            f"🔒 18 more picks + 20-match accumulator with "
                            f"REAL SportyBet + Football.com codes are VIP-only.\n\n"
                            f"👉 Click to upgrade and see full betslip: {BOT_LINK}\n\n"
                            f"{BOT_HANDLE}"
                        )
                        send_message(CHANNEL_ID, msg)
                except Exception as e:
                    print(f"8AM error: {e}")
                posted_today.add(f"{today_str}-8am")

            if hm == "00:05":
                posted_today.clear()
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(60)


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────
threading.Thread(target=load_brain, daemon=True).start()
threading.Thread(target=channel_scheduler, daemon=True).start()


@app.on_event("startup")
async def on_startup():
    set_bot_menu()
    print(f"[startup] Admins: {ADMIN_IDS}")
    try:
        url = (f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
               f"?url={RENDER_URL}/webhook&drop_pending_updates=true")
        r = requests.get(url, timeout=10).json()
        print(f"WEBHOOK SET: {r}")
    except Exception as e:
        print(f"Webhook error: {e}")


# ──────────────────────────────────────────────
# FASTAPI ROUTES
# ──────────────────────────────────────────────
@app.get("/")
async def home():
    return {
        "status": "BetMaster Pro v3 — Professional AI Betting Bot",
        "admins": len(ADMIN_IDS),
        "features": ["13 markets", "value bets", "bankroll advisor",
                     "20-match accumulator", "SportyBet codes",
                     "Football.com codes", "N1M challenge", "admin panel"],
        "brain": f"{len(HISTORICAL_STATS)} teams",
        "sb_cache": len(SB_EVENTS_CACHE.get("data", [])),
    }


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        threading.Thread(target=process_update, args=(data,), daemon=True).start()
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"Webhook error: {e}")
        return JSONResponse({"ok": True})


@app.get("/set-webhook")
async def set_webhook():
    set_bot_menu()
    r = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        f"?url={RENDER_URL}/webhook&drop_pending_updates=true", timeout=10,
    ).json()
    return r


@app.get("/test-sportybet")
async def test_sportybet():
    events = sb_fetch_events(timeline_hours=48, page_size=20)
    return {"count": len(events), "sample": events[:3] if events else []}


@app.get("/test-converter")
async def test_converter(code: str = ""):
    if not code:
        return {"error": "Provide ?code=ABC123"}
    result = convert_sb_to_football(code)
    return {"input": code, "football_code": result}


@app.get("/admin/whoami")
async def admin_whoami(uid: str = ""):
    try:
        uid_int = int(uid)
    except Exception:
        return {"error": "Provide ?uid=123456789"}
    return {"uid": uid_int, "is_admin": is_admin(uid_int)}


# Payment routes
@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    return HTMLResponse(render_payment_page(uid))


@app.get("/pay")
async def pay(plan: str, uid: str):
    if not FLW_SECRET:
        return HTMLResponse(render_failed_page("Payment not configured.", uid), status_code=500)
    if plan not in ("daily", "weekly", "monthly"):
        return HTMLResponse(render_failed_page(f"Invalid plan: {plan}", uid), status_code=400)
    amounts = {"daily": 500, "weekly": 2000, "monthly": 5000}
    amount = amounts[plan]
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload = {
        "tx_ref": tx_ref, "amount": amount, "currency": "NGN",
        "redirect_url": f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer": {"email": f"{uid}@betmasterpro.com", "name": f"User {uid}"},
        "customizations": {"title": f"BetMaster Pro — {plan.title()}"},
        "payment_options": "card,banktransfer,ussd,mobilemoney",
    }
    try:
        r = requests.post("https://api.flutterwave.com/v3/payments", json=payload,
                          headers={"Authorization": f"Bearer {FLW_SECRET}"}, timeout=20).json()
        if r.get("status") == "success" and r.get("data", {}).get("link"):
            return RedirectResponse(r["data"]["link"])
        return HTMLResponse(render_failed_page(r.get("message", "Failed"), uid), status_code=400)
    except Exception as e:
        return HTMLResponse(render_failed_page(f"Error: {e}", uid), status_code=500)


@app.get("/verify")
async def verify(tx_ref: str, uid: str, plan: str):
    try:
        r = requests.get(f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}",
                         headers={"Authorization": f"Bearer {FLW_SECRET}"}, timeout=20).json()
        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ("successful", "completed"):
                activate_vip(uid, plan)
                try:
                    db = SessionLocal()
                    u = get_user(db, int(uid))
                    if u.referred_by:
                        award_referral(db, u.referred_by, int(uid))
                    db.close()
                except Exception:
                    pass
                return HTMLResponse(render_success_page(plan))
            return HTMLResponse(render_failed_page(f"Status: {data.get('status')}", uid), status_code=400)
        return HTMLResponse(render_failed_page("Not found.", uid), status_code=404)
    except Exception as e:
        return HTMLResponse(render_failed_page(f"Error: {e}", uid), status_code=500)


@app.post("/flutterwave-webhook")
async def flutterwave_webhook(request: Request):
    try:
        sig = request.headers.get("verif-hash", "")
        if FLW_WEBHOOK_HASH and sig != FLW_WEBHOOK_HASH:
            return JSONResponse({"status": "invalid"}, status_code=401)
        payload = await request.json()
        data = payload.get("data", {})
        if data.get("status", "").lower() not in ("successful", "completed"):
            return JSONResponse({"status": "ignored"})
        tx_ref = data.get("tx_ref", "")
        parts = tx_ref.split("-")
        if len(parts) < 4 or parts[0] != "BETMASTER":
            return JSONResponse({"status": "malformed"})
        uid, plan = parts[1], parts[2]
        verify = requests.get(
            f"https://api.flutterwave.com/v3/transactions/{data.get('id')}/verify",
            headers={"Authorization": f"Bearer {FLW_SECRET}"}, timeout=15,
        ).json()
        if (verify.get("status") == "success" and
                verify.get("data", {}).get("status") == "successful"):
            db = SessionLocal()
            try:
                u = get_user(db, int(uid))
                if u.is_vip and u.vip_expiry >= str(date.today()):
                    return JSONResponse({"status": "already_active"})
            finally:
                db.close()
            activate_vip(uid, plan)
        return JSONResponse({"status": "success"})
    except Exception as e:
        print(f"Webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)


# ──────────────────────────────────────────────
# PAYMENT TEMPLATES
# ──────────────────────────────────────────────
PAYMENT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BetMaster Pro — VIP</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;
background:#0a0e1a;color:#e8ecf5;line-height:1.5;min-height:100vh;padding:20px}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:34px;font-weight:700;letter-spacing:-.03em;margin:30px 0 12px;
background:linear-gradient(180deg,#fff,#b8c1d6);-webkit-background-clip:text;
-webkit-text-fill-color:transparent}
p.lead{color:#8b94ab;font-size:15px;margin-bottom:30px}
.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.plan{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);
border-radius:16px;padding:26px 22px}
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
color:white;text-align:center;font-weight:600;font-size:14.5px;margin-top:16px;
transition:transform .2s}
.btn-g{background:linear-gradient(135deg,#22c55e,#16a34a)}
.btn-b{background:linear-gradient(135deg,#3b82f6,#2563eb)}
.btn:hover{transform:translateY(-1px)}
.foot{margin-top:40px;padding:20px 0;border-top:1px solid rgba(255,255,255,.08);
text-align:center;font-size:12px;color:#5a6378}
@media(max-width:720px){.plans{grid-template-columns:1fr}h1{font-size:26px}}
</style></head><body>
<div class="wrap">
<h1>Unlock AI Football Predictions</h1>
<p class="lead">13 markets · Real SportyBet + Football.com codes · 20-match accumulator · N1M challenge</p>
<div class="plans">
<div class="plan"><div class="name">Daily</div><div class="price">₦500<small>/24h</small></div>
<ul><li>10 predictions</li><li>20-match accumulator</li><li>Real codes</li></ul>
<a href="/pay?plan=daily&uid={{UID}}" class="btn btn-g">Get 24h</a></div>
<div class="plan featured"><div class="name">Monthly (Best)</div>
<div class="price">₦5,000<small>/month</small></div>
<ul><li>Everything in Weekly</li><li>Priority support</li><li>Early features</li></ul>
<a href="/pay?plan=monthly&uid={{UID}}" class="btn btn-b">Get Monthly</a></div>
<div class="plan"><div class="name">Weekly</div><div class="price">₦2,000<small>/week</small></div>
<ul><li>10 predictions/day</li><li>All 13 markets</li><li>Value bets</li></ul>
<a href="/pay?plan=weekly&uid={{UID}}" class="btn btn-g">Get Weekly</a></div>
</div>
<div class="foot">© {{YEAR}} BetMaster Pro · 18+ · Bet responsibly</div>
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
</style></head><body>
<div class="card"><h1>✅ {{PLAN}} Activated</h1>
<p>Return to the bot to start.</p>
<a href="{{BOT_LINK}}">Open Bot</a></div></body></html>"""


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


def render_payment_page(uid):
    from datetime import datetime as _dt
    return (PAYMENT_TEMPLATE.replace("{{UID}}", str(uid))
            .replace("{{BOT_LINK}}", BOT_LINK)
            .replace("{{YEAR}}", str(_dt.now().year)))


def render_success_page(plan):
    return SUCCESS_TEMPLATE.replace("{{PLAN}}", plan.upper()).replace("{{BOT_LINK}}", BOT_LINK)


def render_failed_page(reason, uid=""):
    return (FAILED_TEMPLATE.replace("{{REASON}}", html.escape(str(reason))[:500])
            .replace("{{UID}}", str(uid)).replace("{{BOT_LINK}}", BOT_LINK))


# ──────────────────────────────────────────────
# RUN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
