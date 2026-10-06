"""
BetMaster Pro — Professional Sports Betting Bot
Full feature set: Dixon-Coles modeling, engagement systems, VIP tiers,
N1 Million accumulator generator, personalized predictions, payments.

Data sources: ESPN, TheSportsDB, OpenFootball, The Odds API.
No API-Football dependency.
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
FOOTYSTATS_KEY = os.getenv("FOOTYSTATS_KEY", "")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"
BOT_HANDLE = "@Betmasterpro_bot"
ADMIN_ID = os.getenv("ADMIN_ID", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Float,
    DateTime, Text, ForeignKey, func
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

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
    # Engagement
    streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    total_predictions = Column(Integer, default=0)
    total_wins = Column(Integer, default=0)
    total_losses = Column(Integer, default=0)
    # Referral
    referral_code = Column(String, default="", index=True)
    referred_by = Column(String, default="")
    referral_count = Column(Integer, default=0)
    # Preferences (personalization)
    fav_leagues = Column(Text, default="")  # comma-separated
    fav_markets = Column(Text, default="")  # comma-separated
    # N1M challenge
    n1m_bankroll = Column(Float, default=0.0)
    n1m_best = Column(Float, default=0.0)
    # Timestamps
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
    result = Column(String, default="pending")  # pending / win / loss
    created_at = Column(DateTime, default=datetime.utcnow)
    match_date = Column(String)


class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, index=True)
    referred_id = Column(Integer, index=True)
    rewarded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TrackedBet(Base):
    __tablename__ = "tracked_bets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    match = Column(String)
    market = Column(String)
    pick = Column(String)
    odds = Column(Float)
    stake = Column(Float, default=1000.0)
    result = Column(String, default="pending")
    profit = Column(Float, default=0.0)
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
        # Daily reset
        if user.last_reset != today_str:
            user.daily_count = 0
            user.last_reset = today_str
            db.commit()
        # VIP expiry
        if user.is_vip and user.vip_expiry and user.vip_expiry < today_str:
            user.is_vip = False
            user.vip_plan = ""
            db.commit()
        # Update last seen
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
        return Dummy()


def activate_vip(uid, plan):
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
        send_message(int(uid), (
            f"🎉 *VIP {plan.upper()} ACTIVATED!*\n\n"
            f"Valid until: {expiry}\n\n"
            f"You now have:\n"
            f"✅ 10 predictions/day\n"
            f"✅ N1M challenge access\n"
            f"✅ 10-match betslip generator\n"
            f"✅ Value-bet alerts\n\n"
            f"Open the bot: {BOT_LINK}"
        ), parse_mode="Markdown")
        return True
    except Exception as e:
        print(f"activate_vip error: {e}")
        return False
    finally:
        db.close()


# ──────────────────────────────────────────────
# BRAIN: historical stats
# ──────────────────────────────────────────────
HISTORICAL_STATS = {}
H2H_CACHE = {}
ODDS_CACHE = {"time": None, "data": {}}
LEAGUE_AVG_GOALS = {}


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
# DIXON-COLES MODEL
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


def find_value_bets(model_probs, odds):
    value_bets = []
    markets = {
        "Home Win": (model_probs.get("home_win", 0), odds.get("home")),
        "Draw": (model_probs.get("draw", 0), odds.get("draw")),
        "Away Win": (model_probs.get("away_win", 0), odds.get("away")),
    }
    for market, (mp, odd) in markets.items():
        if not odd or odd <= 1.01:
            continue
        implied = 100.0 / odd
        edge = mp - implied
        if edge > 3.0:
            kelly = max(0.0, (edge / 100.0 * odd - 1) / (odd - 1)) * 100
            value_bets.append({
                "market": market, "model_prob": round(mp, 1),
                "implied": round(implied, 1), "edge": round(edge, 1),
                "odds": odd, "kelly": round(min(kelly, 15), 1),
            })
    value_bets.sort(key=lambda x: x["edge"], reverse=True)
    return value_bets


def predict_match(data):
    """Master prediction engine — Dixon-Coles + H2H + value bets."""
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

    mp = {"home_win": round(dc_h, 1), "draw": round(dc_d, 1), "away_win": round(dc_a, 1)}

    odds = {
        "home": float(data.get("odds_h", 0) or 0),
        "draw": float(data.get("odds_d", 0) or 0),
        "away": float(data.get("odds_a", 0) or 0),
    }
    if odds["home"] <= 1.01: odds["home"] = round(100 / max(mp["home_win"], 5), 2)
    if odds["draw"] <= 1.01: odds["draw"] = round(100 / max(mp["draw"], 5), 2)
    if odds["away"] <= 1.01: odds["away"] = round(100 / max(mp["away_win"], 5), 2)

    markets = []

    best_1x2 = max(
        [("Home Win", mp["home_win"], odds["home"]),
         ("Draw", mp["draw"], odds["draw"]),
         ("Away Win", mp["away_win"], odds["away"])],
        key=lambda x: x[1],
    )
    if best_1x2[1] >= 40:
        markets.append({
            "market": "1X2", "pick": best_1x2[0], "odds": best_1x2[2],
            "conf": round(best_1x2[1], 1),
            "reason": f"Dixon-Coles: {best_1x2[0]} {best_1x2[1]:.1f}%. "
                      f"xG {home} {dc['home_xg']} vs {away} {dc['away_xg']}.",
        })

    dc_1x = mp["home_win"] + mp["draw"]
    dc_x2 = mp["draw"] + mp["away_win"]
    if dc_1x >= 70:
        markets.append({
            "market": "DC", "pick": f"{home} Win or Draw (1X)",
            "odds": round(1.01 + (100 - dc_1x) / 100, 2),
            "conf": round(dc_1x, 1),
            "reason": f"Model: {dc_1x:.1f}% chance {home} does not lose.",
        })
    if dc_x2 >= 70:
        markets.append({
            "market": "DC", "pick": f"{away} Win or Draw (X2)",
            "odds": round(1.01 + (100 - dc_x2) / 100, 2),
            "conf": round(dc_x2, 1),
            "reason": f"Model: {dc_x2:.1f}% chance {away} does not lose.",
        })

    if dc["btts"] >= 60:
        markets.append({
            "market": "BTTS", "pick": "BTTS Yes",
            "odds": float(data.get("odds_btts", 1.85) or 1.85),
            "conf": round(dc["btts"], 1),
            "reason": f"BTTS probability {dc['btts']}%.",
        })
    elif dc["btts"] <= 40:
        markets.append({
            "market": "BTTS", "pick": "BTTS No", "odds": 1.85,
            "conf": round(100 - dc["btts"], 1),
            "reason": f"BTTS probability only {dc['btts']}%.",
        })

    if dc["over25"] >= 60:
        markets.append({
            "market": "O/U", "pick": "Over 2.5 Goals",
            "odds": float(data.get("odds_over25", 1.90) or 1.90),
            "conf": round(dc["over25"], 1),
            "reason": f"Over 2.5 probability {dc['over25']}%. "
                      f"Total xG {dc['home_xg'] + dc['away_xg']:.2f}.",
        })
    elif dc["over25"] <= 40:
        markets.append({
            "market": "O/U", "pick": "Under 2.5 Goals", "odds": 1.90,
            "conf": round(100 - dc["over25"], 1),
            "reason": f"Under 2.5 probability {100 - dc['over25']:.1f}%.",
        })

    if dc["over15"] >= 75:
        markets.append({
            "market": "O/U", "pick": "Over 1.5 Goals", "odds": 1.30,
            "conf": round(dc["over15"], 1),
            "reason": f"Over 1.5 probability {dc['over15']}% — banker.",
        })

    if not markets:
        top = max(
            [("Home Win", mp["home_win"], odds["home"]),
             ("Draw", mp["draw"], odds["draw"]),
             ("Away Win", mp["away_win"], odds["away"])],
            key=lambda x: x[1],
        )
        markets.append({
            "market": "1X2", "pick": top[0], "odds": top[2],
            "conf": round(top[1], 1),
            "reason": f"Best available — {top[0]} at {top[1]:.1f}%.",
        })

    markets.sort(key=lambda x: x["conf"], reverse=True)
    best = markets[0]
    vb = find_value_bets(mp, odds)

    h_form = "".join(HISTORICAL_STATS.get(home, {}).get("form", [])[:5]) or "N/A"
    a_form = "".join(HISTORICAL_STATS.get(away, {}).get("form", [])[:5]) or "N/A"

    h2h_str = "No H2H data"
    if h2h_games:
        h2h_str = (f"H2H last {len(h2h_games)}: {home} {h2h_home_wins}W "
                   f"{h2h_draws}D {h2h_away_wins}W, BTTS {h2h_btts}/{len(h2h_games)}, "
                   f"Avg {h2h_avg_goals:.1f} goals")

    explanation = best["reason"]
    if vb:
        explanation += (f"\n💎 VALUE: {vb[0]['market']} @ {vb[0]['odds']} "
                        f"(edge +{vb[0]['edge']}%)")
    explanation += ("\nTop scorelines: "
                    + ", ".join(f"{s[0]} ({s[1]}%)" for s in dc["top_scorelines"][:3]))

    return {
        "best_market": best["market"],
        "best_pick": best["pick"],
        "odds": float(best["odds"]),
        "confidence": best["conf"],
        "explanation": explanation,
        "verdict": f"AI: {best['market']} — {best['pick']} @ {best['odds']}",
        "all_markets": markets[:5],
        "value_bets": vb,
        "h2h": h2h_str,
        "form": f"Form: {home} [{h_form}] | {away} [{a_form}]",
        "standings": (f"xG: {home} {dc['home_xg']} — {away} {dc['away_xg']} | "
                      f"1X2: {mp['home_win']}%/{mp['draw']}%/{mp['away_win']}%"),
        "live_odds_source": data.get("source", "Model"),
        "winnings_1000": calc(best["odds"], 1000),
        "dc": dc,
        "disclaimer": "\n\n18+ Bet responsibly.",
    }


get_dynamic_ai_prediction = predict_match


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
# PERSONALIZATION
# ──────────────────────────────────────────────
def update_user_preferences(db, user, fixture, market):
    """Learn user's favorite leagues/markets over time."""
    try:
        fav_l = set((user.fav_leagues or "").split(",")) - {""}
        if fixture.get("league"):
            fav_l.add(fixture["league"])
        user.fav_leagues = ",".join(list(fav_l)[-10:])  # Keep last 10

        fav_m = set((user.fav_markets or "").split(",")) - {""}
        if market:
            fav_m.add(market)
        user.fav_markets = ",".join(list(fav_m)[-5:])  # Keep last 5
        db.commit()
    except Exception as e:
        print(f"Pref update error: {e}")


def score_fixture_for_user(fixture, user):
    """Higher score = more relevant for this user."""
    score = 0
    fav_leagues = set((user.fav_leagues or "").split(",")) - {""}
    if fixture.get("league") in fav_leagues:
        score += 50
    # Top leagues always get a boost
    league = fixture.get("league", "").lower()
    if any(k in league for k in ["premier league", "la liga", "serie a",
                                  "bundesliga", "ligue 1", "champions league"]):
        score += 20
    return score


# ──────────────────────────────────────────────
# N1 MILLION ACCUMULATOR
# ──────────────────────────────────────────────
def generate_n1m_slip(fixtures, user, stake=1000.0, target=1000000.0):
    """
    Build a high-odds accumulator: N1,000 → N1,000,000 (needs total odds ~1000).
    Personalizes to user's favorite leagues when possible.
    """
    target_odds = target / stake  # = 1000.0

    # Score all fixtures for this user
    scored = [(f, score_fixture_for_user(f, user)) for f in fixtures]
    scored.sort(key=lambda x: x[1], reverse=True)

    picks = []
    total_odds = 1.0

    for fixture, _ in scored:
        if total_odds >= target_odds:
            break

        p = predict_match(fixture)

        # Pick the highest-confidence market for this fixture
        best = None
        for m in p["all_markets"]:
            if m["odds"] and 1.2 <= m["odds"] <= 5.0 and m["conf"] >= 50:
                if best is None or m["conf"] > best["conf"]:
                    best = m

        if not best:
            continue

        # Avoid duplicate matches
        if any(pk["match"] == f"{fixture['home']} vs {fixture['away']}" for pk in picks):
            continue

        picks.append({
            "match": f"{fixture['home']} vs {fixture['away']}",
            "league": fixture.get("league", ""),
            "market": best["market"],
            "pick": best["pick"],
            "odds": float(best["odds"]),
            "conf": best["conf"],
            "reason": best["reason"],
        })
        total_odds *= float(best["odds"])

        if len(picks) >= 15:
            break

    total_odds = round(total_odds, 2)
    potential_win = round(stake * total_odds, 2)

    return {
        "picks": picks,
        "total_odds": total_odds,
        "stake": stake,
        "potential_win": potential_win,
        "target_met": potential_win >= target * 0.9,
    }


# ──────────────────────────────────────────────
# BETSLIP (10-match)
# ──────────────────────────────────────────────
def generate_betslip(fixtures, user=None):
    if len(fixtures) < 5:
        return None

    if user:
        scored = [(f, score_fixture_for_user(f, user)) for f in fixtures]
        scored.sort(key=lambda x: x[1], reverse=True)
        fixtures = [f for f, _ in scored]

    picks = []
    total = 1.0
    for f in fixtures[:10]:
        p = predict_match(f)
        picks.append({
            "match": f"{f['home']} vs {f['away']}",
            "league": f.get("league", ""),
            "pick": p["best_pick"],
            "odds": p["odds"],
            "market": p["best_market"],
            "conf": p["confidence"],
        })
        total *= float(p["odds"])

    total = round(total, 2)
    return {
        "picks": picks, "total_odds": total,
        "winnings_1000": round(total * 1000, 2),
        "winnings_2000": round(total * 2000, 2),
    }


# ──────────────────────────────────────────────
# ENGAGEMENT HELPERS
# ──────────────────────────────────────────────
def get_daily_recap(db):
    """Yesterday's results from tracked predictions."""
    try:
        yesterday = str(date.today() - timedelta(days=1))
        preds = db.query(Prediction).filter(Prediction.match_date == yesterday).all()
        if not preds:
            return None
        wins = sum(1 for p in preds if p.result == "win")
        losses = sum(1 for p in preds if p.result == "loss")
        total = wins + losses
        if total == 0:
            return None
        profit = sum(p.odds - 1 for p in preds if p.result == "win") - losses
        return {
            "wins": wins, "losses": losses, "total": total,
            "profit": round(profit, 2),
            "preds": preds[:5],
        }
    except Exception as e:
        print(f"Recap error: {e}")
        return None


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
        }
    except Exception:
        return {"streak": 0, "best_streak": 0, "total": 0, "wins": 0,
                "losses": 0, "win_rate": 0, "referrals": 0,
                "n1m_bankroll": 0.0, "n1m_best": 0.0}


def award_referral(db, referrer_code, new_user_id):
    """Reward referrer with 7 free VIP days when referred user pays."""
    try:
        referrer = db.query(User).filter(User.referral_code == referrer_code).first()
        if not referrer:
            return
        # Check not already rewarded
        existing = db.query(Referral).filter(
            Referral.referrer_id == referrer.user_id,
            Referral.referred_id == new_user_id,
        ).first()
        if existing:
            return

        referral = Referral(referrer_id=referrer.user_id, referred_id=new_user_id, rewarded=True)
        db.add(referral)
        referrer.referral_count = (referrer.referral_count or 0) + 1

        # Reward: 7 extra VIP days
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

        send_message(referrer.user_id, (
            f"🎁 *Referral Reward!*\n\n"
            f"Someone you referred just paid. "
            f"You got *7 free VIP days* — now valid until {new_expiry}.\n\n"
            f"Keep sharing your link: {BOT_LINK}?start=ref_{referrer.referral_code}"
        ), parse_mode="Markdown")
    except Exception as e:
        print(f"Referral error: {e}")


# ──────────────────────────────────────────────
# TELEGRAM API
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
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Send error {e}")


def set_bot_menu():
    commands = [
        {"command": "today",            "description": "Today's top fixtures"},
        {"command": "europeanleagues",  "description": "European leagues"},
        {"command": "asianleagues",     "description": "Asian leagues"},
        {"command": "americanleagues",  "description": "American leagues"},
        {"command": "national",         "description": "FIFA / national teams"},
        {"command": "million",          "description": "N1M challenge"},
        {"command": "betslip",          "description": "VIP 10-match betslip"},
        {"command": "stats",            "description": "Your stats & accuracy"},
        {"command": "leaderboard",      "description": "Top users this week"},
        {"command": "refer",            "description": "Refer friends, earn VIP"},
        {"command": "profile",          "description": "Your profile"},
        {"command": "upgrade",          "description": "Upgrade to VIP"},
        {"command": "help",             "description": "Help"},
        {"command": "start",            "description": "Start"},
    ]
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
            json={"commands": commands}, timeout=10,
        )
    except Exception:
        pass


# ──────────────────────────────────────────────
# REGION COMMANDS
# ──────────────────────────────────────────────
REGION_INFO = {
    "european": ("🇪🇺 EUROPEAN LEAGUES", "European"),
    "asian":    ("🇯🇵 ASIAN LEAGUES",    "Asian"),
    "american": ("🇺🇸 AMERICAN LEAGUES", "American"),
    "national": ("🌍 NATIONAL TEAMS / FIFA", "National"),
}


def handle_region(chat_id, user_id, region, user, db, limit):
    header, pretty = REGION_INFO.get(region, ("FIXTURES", region.title()))

    if user.daily_count >= limit:
        send_message(chat_id,
                     f"🚫 Daily limit reached ({user.daily_count}/{limit}).\n\n"
                     f"Upgrade for 10/day + N1M challenge:\n"
                     f"{RENDER_URL}/subscribe?uid={user_id}")
        return

    send_message(chat_id, f"🔎 Scanning {pretty} fixtures...")

    fixtures = fetch_real_fixtures(days_ahead=0, limit=15, region=region)
    if not fixtures:
        for i in range(1, 8):
            fixtures = fetch_real_fixtures(days_ahead=i, limit=15, region=region)
            if fixtures:
                break

    if not fixtures:
        send_message(chat_id, f"No {pretty} fixtures in the next 7 days.\n{BOT_LINK}")
        return

    # Personalize order
    scored = [(f, score_fixture_for_user(f, user)) for f in fixtures]
    scored.sort(key=lambda x: x[1], reverse=True)
    fixtures = [f for f, _ in scored]

    msg = f"{header}\n📅 {fixtures[0].get('date', 'Today')}\n\n"
    for i, f in enumerate(fixtures, 1):
        star = "⭐ " if score_fixture_for_user(f, user) >= 50 else ""
        msg += (f"{i}. {star}{f['home']} vs {f['away']}\n"
                f"   🏆 {f.get('league', '')}\n"
                f"   🕐 {f.get('time', '')} WAT\n\n")

    msg += f"({user.daily_count}/{limit}) — Tap below for analysis\n{BOT_LINK}"

    keyboard = {"inline_keyboard": [
        [{"text": f"🧠 Analyze {pretty} Top 5", "callback_data": f"predict_{region}"}],
        [{"text": "💰 N1M Challenge", "callback_data": "n1m_challenge"},
         {"text": "🎯 VIP Betslip", "callback_data": "generate_betslip"}],
    ]}
    send_message(chat_id, msg, reply_markup=keyboard)


def send_full_prediction(chat_id, fixture, db=None, user=None):
    p = predict_match(fixture)
    msg = (
        f"⚽ *{fixture['home']} vs {fixture['away']}*\n"
        f"🏆 {fixture.get('league','')} | {fixture.get('date','')} {fixture.get('time','')} WAT\n\n"
        f"📊 {p['form']}\n"
        f"📈 {p['h2h']}\n"
        f"📉 {p['standings']}\n\n"
        f"✅ *{p['verdict']}* ({p['confidence']}%)\n"
        f"📝 {p['explanation']}\n\n"
        f"📋 *ALL MARKETS:*\n"
    )
    for m in p["all_markets"][:4]:
        msg += f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"

    if p.get("value_bets"):
        msg += "\n💎 *VALUE BETS:*\n"
        for v in p["value_bets"][:2]:
            msg += f"• {v['market']} @ {v['odds']} (edge +{v['edge']}%)\n"

    msg += (f"\n💰 N1000 → N{p['winnings_1000']}\n"
            f"📡 {p['live_odds_source']}\n{p['disclaimer']}")

    send_message(chat_id, msg, parse_mode="Markdown")

    # Log prediction for tracking
    if db and user:
        try:
            pred = Prediction(
                user_id=user.user_id,
                match=f"{fixture['home']} vs {fixture['away']}",
                league=fixture.get("league", ""),
                market=p["best_market"], pick=p["best_pick"],
                odds=p["odds"], confidence=p["confidence"],
                match_date=fixture.get("date", str(date.today())),
            )
            db.add(pred)
            user.total_predictions = (user.total_predictions or 0) + 1
            db.commit()
            update_user_preferences(db, user, fixture, p["best_market"])
        except Exception as e:
            print(f"Pred log error: {e}")


# ──────────────────────────────────────────────
# UPDATE PROCESSOR
# ──────────────────────────────────────────────
def process_update(upd):
    try:
        base = f"https://api.telegram.org/bot{BOT_TOKEN}"

        # ═══ CALLBACKS ═══
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            from_id = cq["from"]["id"]
            data = cq.get("data", "")

            requests.post(f"{base}/answerCallbackQuery",
                          json={"callback_query_id": cq["id"], "text": "Working..."},
                          timeout=5)

            db2 = SessionLocal()
            try:
                user2 = get_user(
                    db2, from_id,
                    cq["from"].get("username", ""),
                    cq["from"].get("first_name", ""),
                )
                limit = 10 if user2.is_vip else 2

                if data.startswith("predict_"):
                    region = data.replace("predict_", "")
                    if user2.daily_count >= limit:
                        send_message(chat_id,
                                     f"🚫 Limit {user2.daily_count}/{limit}\n\n"
                                     f"Upgrade: {RENDER_URL}/subscribe?uid={from_id}")
                        return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5, region=region)
                    if not fixtures:
                        for i in range(1, 8):
                            fixtures = fetch_real_fixtures(days_ahead=i, limit=5, region=region)
                            if fixtures:
                                break
                    if not fixtures:
                        send_message(chat_id, f"No fixtures for {region}.\n{BOT_LINK}")
                        return
                    send_message(chat_id, f"🧠 *AI Analysis — {region.title()}*", parse_mode="Markdown")
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit:
                            break
                        send_full_prediction(chat_id, f, db2, user2)
                        user2.daily_count += 1
                        db2.commit()
                        time.sleep(0.8)

                elif data == "predict_top5":
                    if user2.daily_count >= limit:
                        send_message(chat_id,
                                     f"🚫 Limit {user2.daily_count}/{limit}\n"
                                     f"{RENDER_URL}/subscribe?uid={from_id}")
                        return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures:
                        send_message(chat_id, f"No fixtures today.\n{BOT_LINK}")
                        return
                    # Sort by user preference
                    scored = [(f, score_fixture_for_user(f, user2)) for f in fixtures]
                    scored.sort(key=lambda x: x[1], reverse=True)
                    fixtures = [f for f, _ in scored]

                    send_message(chat_id, "🧠 *Personalized AI Analysis*", parse_mode="Markdown")
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit:
                            break
                        send_full_prediction(chat_id, f, db2, user2)
                        user2.daily_count += 1
                        db2.commit()
                        time.sleep(0.8)

                elif data == "generate_betslip":
                    if not user2.is_vip:
                        send_message(chat_id,
                                     f"💎 *VIP only.*\n\n"
                                     f"Get 10-match betslips + N1M challenge:\n"
                                     f"{RENDER_URL}/subscribe?uid={from_id}",
                                     parse_mode="Markdown")
                        return
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=20)
                    if len(fixtures) < 5:
                        for i in range(1, 8):
                            extra = fetch_real_fixtures(days_ahead=i, limit=20)
                            exist = {f"{x['home']}-{x['away']}" for x in fixtures}
                            for ef in extra:
                                if f"{ef['home']}-{ef['away']}" not in exist:
                                    fixtures.append(ef)
                            if len(fixtures) >= 10:
                                break
                    slip = generate_betslip(fixtures, user2)
                    if not slip:
                        send_message(chat_id, f"Not enough fixtures ({len(fixtures)}).")
                        return
                    msg = (f"💰 *VIP BETSLIP — {datetime.now().strftime('%d %b %Y')}*\n"
                           f"10 matches · Dixon-Coles · Personalized\n\n")
                    for i, p in enumerate(slip["picks"], 1):
                        msg += (f"{i}. {p['match']}\n"
                                f"   {p['market']}: {p['pick']} @ {p['odds']} ({p['conf']}%)\n\n")
                    msg += (f"*TOTAL ODDS:* {slip['total_odds']}\n"
                            f"N1000 → N{slip['winnings_1000']}\n"
                            f"N2000 → N{slip['winnings_2000']}\n{BOT_LINK}")
                    send_message(chat_id, msg, parse_mode="Markdown")

                elif data == "n1m_challenge":
                    handle_n1m(chat_id, user2, db2)

                elif data == "n1m_regen":
                    handle_n1m(chat_id, user2, db2)

            finally:
                db2.close()
            return

        # ═══ MESSAGES ═══
        msg = upd.get("message")
        if not msg or "text" not in msg or msg["chat"]["type"] != "private":
            return

        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        user_id = msg["from"]["id"]
        username = msg["from"].get("username", "")
        first_name = msg["from"].get("first_name", "")
        low = text.lower()

        db = SessionLocal()
        try:
            user = get_user(db, user_id, username, first_name)
            FREE, VIP = 2, 10
            cur = VIP if user.is_vip else FREE

            # Handle referral code in /start ref_XXXX
            if low.startswith("/start") and "ref_" in low:
                try:
                    ref_code = text.split("ref_")[1].split()[0].strip()
                    if ref_code and user.referred_by != ref_code:
                        user.referred_by = ref_code
                        db.commit()
                except Exception:
                    pass

            # ── /start ──
            if low.startswith("/start"):
                tier = "💎 VIP" if user.is_vip else "🆓 FREE"
                send_message(chat_id, (
                    f"👋 *Welcome to BetMaster Pro, {first_name or 'friend'}!*\n\n"
                    f"🧠 Dixon-Coles AI prediction engine\n"
                    f"🌍 Europe · Asia · Americas · National\n"
                    f"💎 Value-bet detection\n"
                    f"🚀 *N1M Challenge* — ₦1,000 → ₦1,000,000\n\n"
                    f"*Your tier:* {tier}\n"
                    f"*Daily limit:* {user.daily_count}/{cur}\n\n"
                    f"*Commands:*\n"
                    f"/today — Today's top picks\n"
                    f"/europeanleagues — Premier League, La Liga...\n"
                    f"/asianleagues — CSL, J1, Saudi Pro...\n"
                    f"/americanleagues — MLS, Liga MX, Brasileirão\n"
                    f"/national — FIFA / national teams\n"
                    f"/million — 🚀 N1M Challenge\n"
                    f"/betslip — VIP 10-match accumulator\n"
                    f"/stats — Your accuracy & streaks\n"
                    f"/leaderboard — Top users\n"
                    f"/refer — Invite friends, earn VIP\n"
                    f"/profile — Your profile\n"
                    f"/upgrade — Go VIP\n\n"
                    f"Or send *Team A vs Team B* for instant analysis.\n\n{BOT_LINK}"
                ), parse_mode="Markdown")

            # ── /help ──
            elif low.startswith("/help"):
                send_message(chat_id, (
                    f"📖 *BetMaster Pro Help*\n\n"
                    f"*Fixtures:*\n"
                    f"• /today — Top fixtures globally\n"
                    f"• /europeanleagues — European fixtures\n"
                    f"• /asianleagues — Asian fixtures\n"
                    f"• /americanleagues — American fixtures\n"
                    f"• /national — FIFA matches\n\n"
                    f"*VIP Features:*\n"
                    f"• /million — N1M accumulator challenge\n"
                    f"• /betslip — 10-match personalized accumulator\n\n"
                    f"*Account:*\n"
                    f"• /stats — Your accuracy & streak\n"
                    f"• /leaderboard — Top 10 users\n"
                    f"• /refer — Get 7 free VIP days per paying referral\n"
                    f"• /profile — Full profile\n"
                    f"• /upgrade — See VIP plans\n\n"
                    f"FREE {FREE}/day · VIP {VIP}/day\n{BOT_LINK}"
                ), parse_mode="Markdown")

            # ── Region commands ──
            elif low.startswith("/europeanleagues"):
                handle_region(chat_id, user_id, "european", user, db, cur)
            elif low.startswith("/asianleagues"):
                handle_region(chat_id, user_id, "asian", user, db, cur)
            elif low.startswith("/americanleagues"):
                handle_region(chat_id, user_id, "american", user, db, cur)
            elif low.startswith("/national"):
                handle_region(chat_id, user_id, "national", user, db, cur)

            # ── /million — N1M Challenge ──
            elif low.startswith("/million") or low.startswith("/m1"):
                handle_n1m(chat_id, user, db)

            # ── /today ──
            elif low.startswith("/today"):
                if user.daily_count >= cur:
                    send_message(chat_id,
                                 f"🚫 Daily limit {user.daily_count}/{cur}\n"
                                 f"Upgrade: {RENDER_URL}/subscribe?uid={user_id}")
                    return
                send_message(chat_id, "🔎 Scanning today's fixtures...")
                fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
                if not fixtures:
                    send_message(chat_id, f"No fixtures today.\n{BOT_LINK}")
                    return
                scored = [(f, score_fixture_for_user(f, user)) for f in fixtures]
                scored.sort(key=lambda x: x[1], reverse=True)
                fixtures = [f for f, _ in scored]

                msg_txt = f"⚽ *TOP FIXTURES — {fixtures[0].get('date', 'Today')}*\n\n"
                for i, f in enumerate(fixtures, 1):
                    star = "⭐ " if score_fixture_for_user(f, user) >= 50 else ""
                    msg_txt += (f"{i}. {star}{f['home']} vs {f['away']}\n"
                                f"   🏆 {f.get('league','')}\n"
                                f"   🕐 {f.get('time','')} WAT\n\n")
                msg_txt += f"({user.daily_count}/{cur}) Tap for analysis\n{BOT_LINK}"

                kb = {"inline_keyboard": [
                    [{"text": "🧠 Predict Top 5", "callback_data": "predict_top5"}],
                    [{"text": "🚀 N1M Challenge", "callback_data": "n1m_challenge"}],
                ]}
                send_message(chat_id, msg_txt, reply_markup=kb, parse_mode="Markdown")

            # ── /betslip ──
            elif low.startswith("/betslip"):
                if not user.is_vip:
                    send_message(chat_id,
                                 f"💎 VIP only.\n{RENDER_URL}/subscribe?uid={user_id}")
                    return
                fixtures = fetch_real_fixtures(days_ahead=0, limit=20)
                slip = generate_betslip(fixtures, user)
                if not slip:
                    send_message(chat_id, "Not enough fixtures for a 10-match slip.")
                    return
                msg_txt = f"💰 *VIP BETSLIP — {datetime.now().strftime('%d %b %Y')}*\n\n"
                for i, p in enumerate(slip["picks"], 1):
                    msg_txt += f"{i}. {p['match']}\n   {p['market']}: {p['pick']} @ {p['odds']}\n\n"
                msg_txt += (f"*TOTAL ODDS:* {slip['total_odds']}\n"
                            f"N1000 → N{slip['winnings_1000']}\n"
                            f"N2000 → N{slip['winnings_2000']}\n{BOT_LINK}")
                send_message(chat_id, msg_txt, parse_mode="Markdown")

            # ── /stats ──
            elif low.startswith("/stats"):
                stats = get_user_stats(db, user_id)
                msg_txt = (
                    f"📊 *Your BetMaster Stats*\n\n"
                    f"🔥 *Current streak:* {stats['streak']}\n"
                    f"🏆 *Best streak:* {stats['best_streak']}\n"
                    f"🎯 *Total predictions:* {stats['total']}\n"
                    f"✅ Wins: {stats['wins']} | ❌ Losses: {stats['losses']}\n"
                    f"📈 *Win rate:* {stats['win_rate']}%\n\n"
                    f"🎁 *Referrals:* {stats['referrals']}\n"
                    f"🚀 *N1M bankroll:* N{stats['n1m_bankroll']:.0f} "
                    f"(best: N{stats['n1m_best']:.0f})\n\n"
                    f"{BOT_LINK}"
                )
                send_message(chat_id, msg_txt, parse_mode="Markdown")

            # ── /leaderboard ──
            elif low.startswith("/leaderboard"):
                try:
                    top = db.query(User).filter(User.total_predictions >= 5)\
                        .order_by(User.total_wins.desc()).limit(10).all()
                except Exception:
                    top = []

                msg_txt = "🏆 *Leaderboard — Top Predictors*\n\n"
                if not top:
                    msg_txt += "No stats yet. Be the first to top the chart!\n"
                else:
                    for i, u in enumerate(top, 1):
                        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
                        name = u.first_name or u.username or f"User{u.user_id}"
                        rate = round(u.total_wins / max(u.total_predictions, 1) * 100, 0)
                        msg_txt += f"{medal} {name} — {u.total_wins}W · {rate:.0f}%\n"
                msg_txt += f"\n{BOT_LINK}"
                send_message(chat_id, msg_txt, parse_mode="Markdown")

            # ── /refer ──
            elif low.startswith("/refer"):
                ref_link = f"https://t.me/Betmasterpro_bot?start=ref_{user.referral_code}"
                msg_txt = (
                    f"🎁 *Refer Friends, Earn VIP*\n\n"
                    f"*Your referral link:*\n`{ref_link}`\n\n"
                    f"*Rewards:*\n"
                    f"✅ You get *7 free VIP days* when someone you refer pays\n"
                    f"✅ They get *20% off* their first month\n\n"
                    f"*Your referrals:* {user.referral_count or 0}\n\n"
                    f"Share it, stack up VIP days free! 💎\n{BOT_LINK}"
                )
                send_message(chat_id, msg_txt, parse_mode="Markdown")

            # ── /profile ──
            elif low.startswith("/profile"):
                stats = get_user_stats(db, user_id)
                tier = "💎 VIP" if user.is_vip else "🆓 FREE"
                exp = user.vip_expiry if user.is_vip else "—"
                fav_l = user.fav_leagues or "None yet"
                msg_txt = (
                    f"👤 *Your Profile*\n\n"
                    f"*Name:* {first_name or username or 'Anon'}\n"
                    f"*Tier:* {tier}\n"
                    f"*VIP until:* {exp}\n"
                    f"*Daily used:* {user.daily_count}/{cur}\n\n"
                    f"📊 *Stats:*\n"
                    f"• Streak: {stats['streak']} (best {stats['best_streak']})\n"
                    f"• Win rate: {stats['win_rate']}% ({stats['wins']}/{stats['total']})\n"
                    f"• Referrals: {stats['referrals']}\n\n"
                    f"⭐ *Favorite leagues:* {fav_l}\n\n"
                    f"{BOT_LINK}"
                )
                send_message(chat_id, msg_txt, parse_mode="Markdown")

            # ── /upgrade ──
            elif low.startswith("/upgrade"):
                send_message(chat_id, (
                    f"💎 *VIP Benefits*\n\n"
                    f"✅ 10 predictions/day (vs FREE 2)\n"
                    f"✅ 🚀 *N1M Challenge* — N1,000 → N1,000,000\n"
                    f"✅ 10-match personalized betslips\n"
                    f"✅ Value-bet alerts\n"
                    f"✅ Personalized fixture ranking\n\n"
                    f"*Plans:*\n"
                    f"• Daily — N500 (24h)\n"
                    f"• Weekly — N2,000\n"
                    f"• Monthly — N5,000 (save N3,000)\n\n"
                    f"👉 {RENDER_URL}/subscribe?uid={user_id}"
                ), parse_mode="Markdown")

            # ── Team vs Team manual query ──
            elif " vs " in low and 5 < len(text) < 100:
                if user.daily_count >= cur:
                    send_message(chat_id,
                                 f"🚫 Limit {user.daily_count}/{cur}\n"
                                 f"{RENDER_URL}/subscribe?uid={user_id}")
                    return
                try:
                    parts = re.split(r"\s+vs\s+", text, flags=re.IGNORECASE)
                    home = parts[0].strip().title()
                    away = parts[1].strip().title()
                except Exception:
                    send_message(chat_id, "Format: Team A vs Team B")
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
                send_full_prediction(chat_id, data, db, user)
                user.daily_count += 1
                db.commit()

            else:
                send_message(chat_id, f"Unknown command. Try /help\n{BOT_LINK}")

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
# N1M HANDLER
# ──────────────────────────────────────────────
def handle_n1m(chat_id, user, db):
    """Generate or view the N1M challenge slip."""
    if not user.is_vip:
        send_message(chat_id, (
            f"🚀 *N1M Challenge — VIP Only*\n\n"
            f"Turn ₦1,000 into ₦1,000,000 with a single accumulator.\n\n"
            f"✅ Personalized to your favorite leagues\n"
            f"✅ Built by Dixon-Coles model\n"
            f"✅ Regenerate anytime\n\n"
            f"👉 {RENDER_URL}/subscribe?uid={user.user_id}"
        ), parse_mode="Markdown")
        return

    send_message(chat_id, "🚀 *Building your N1M slip...*\nThis takes ~15 seconds.", parse_mode="Markdown")

    fixtures = fetch_real_fixtures(days_ahead=0, limit=40)
    if len(fixtures) < 8:
        for i in range(1, 8):
            extra = fetch_real_fixtures(days_ahead=i, limit=40)
            exist = {f"{x['home']}-{x['away']}" for x in fixtures}
            for ef in extra:
                if f"{ef['home']}-{ef['away']}" not in exist:
                    fixtures.append(ef)
            if len(fixtures) >= 20:
                break

    if len(fixtures) < 8:
        send_message(chat_id, f"Not enough fixtures today ({len(fixtures)}). Try again later.")
        return

    slip = generate_n1m_slip(fixtures, user, stake=1000, target=1000000)

    if not slip["picks"]:
        send_message(chat_id, "Could not build a slip. Try again later.")
        return

    # Update bankroll if this is a fresh generation
    user.n1m_bankroll = slip["stake"]
    if slip["potential_win"] > (user.n1m_best or 0):
        user.n1m_best = slip["potential_win"]
    db.commit()

    target_status = "✅ TARGET MET" if slip["target_met"] else "⚠️ Slightly below target"

    msg = (
        f"🚀 *N1M CHALLENGE — {datetime.now().strftime('%d %b %Y')}*\n\n"
        f"💰 *Stake:* N{slip['stake']:.0f}\n"
        f"🎯 *Potential win:* N{slip['potential_win']:,.0f}\n"
        f"📊 *Total odds:* {slip['total_odds']}\n"
        f"{target_status}\n\n"
        f"*Your {len(slip['picks'])}-leg accumulator:*\n\n"
    )
    for i, p in enumerate(slip["picks"], 1):
        msg += (f"{i}. *{p['match']}*\n"
                f"   {p['market']}: {p['pick']} @ {p['odds']} ({p['conf']}%)\n"
                f"   🏆 {p['league']}\n\n")

    msg += (f"⚠️ *N1M slip is high-risk.* Higher odds = higher chance of failure. "
            f"Only stake what you can afford to lose.\n\n"
            f"Regenerate with new picks: tap below.\n{BOT_LINK}")

    kb = {"inline_keyboard": [[
        {"text": "🔄 Regenerate Slip", "callback_data": "n1m_regen"},
        {"text": "💎 Go VIP Monthly", "url": f"{RENDER_URL}/subscribe?uid={user.user_id}"},
    ]]}
    send_message(chat_id, msg, reply_markup=kb, parse_mode="Markdown")

    # Log each pick
    try:
        for p in slip["picks"]:
            pred = Prediction(
                user_id=user.user_id, match=p["match"], league=p["league"],
                market=p["market"], pick=p["pick"], odds=p["odds"],
                confidence=p["conf"], match_date=str(date.today()),
            )
            db.add(pred)
        db.commit()
    except Exception as e:
        print(f"N1M log error: {e}")


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

            # 06:00 — morning picks
            if hm == "06:00" and f"{today_str}-6am" not in posted_today:
                try:
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    if fixtures and CHANNEL_ID:
                        msg = f"☀️ *Good Morning {today_str} — 6AM Picks*\n\n"
                        for f in fixtures[:3]:
                            p = predict_match(f)
                            msg += (f"*{f['home']} vs {f['away']}*\n"
                                    f"{f.get('league','')} · {p['best_market']}: "
                                    f"*{p['best_pick']}* @ {p['odds']} ({p['confidence']}%)\n\n")
                        msg += f"Full analysis: {BOT_HANDLE}\n{BOT_LINK}"
                        send_message(CHANNEL_ID, msg, parse_mode="Markdown")
                except Exception as e:
                    print(f"6AM error: {e}")
                posted_today.add(f"{today_str}-6am")

            # 08:00 — top 5
            if hm == "08:00" and f"{today_str}-8am" not in posted_today:
                try:
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
                    if fixtures and CHANNEL_ID:
                        msg = f"🎯 *TOP MATCHES — {today_str}*\n\n"
                        for f in fixtures[:5]:
                            p = predict_match(f)
                            msg += (f"*{f['home']} vs {f['away']}*\n"
                                    f"{f.get('league','')} · {p['best_pick']} @ {p['odds']} "
                                    f"({p['confidence']}%)\n\n")
                        msg += f"Want full analysis? {BOT_HANDLE}\n{BOT_LINK}"
                        send_message(CHANNEL_ID, msg, parse_mode="Markdown")
                except Exception as e:
                    print(f"8AM error: {e}")
                posted_today.add(f"{today_str}-8am")

            # 21:00 — tomorrow preview
            if hm == "21:00" and f"{today_str}-9pm" not in posted_today:
                try:
                    fixtures = fetch_real_fixtures(days_ahead=1, limit=5)
                    if fixtures and CHANNEL_ID:
                        msg = f"🌙 *TOMORROW'S TOP PICKS*\n\n"
                        for f in fixtures[:3]:
                            p = predict_match(f)
                            msg += (f"*{f['home']} vs {f['away']}*\n"
                                    f"{f.get('league','')} · {p['best_pick']} @ {p['odds']}\n\n")
                        msg += f"More on {BOT_HANDLE}\n{BOT_LINK}"
                        send_message(CHANNEL_ID, msg, parse_mode="Markdown")
                except Exception as e:
                    print(f"9PM error: {e}")
                posted_today.add(f"{today_str}-9pm")

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
        "status": "BetMaster Pro — Dixon-Coles AI · Full Professional",
        "features": ["regions", "n1m", "betslip", "stats", "leaderboard",
                     "referrals", "personalization", "vip"],
        "brain": f"{len(HISTORICAL_STATS)} teams · H2H {len(H2H_CACHE)}",
        "regions": ["european", "asian", "american", "national"],
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


# ═══ PAYMENT ROUTES ═══
@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    return HTMLResponse(render_payment_page(uid))


@app.get("/pay")
async def pay(plan: str, uid: str):
    if not FLW_SECRET:
        return HTMLResponse(render_failed_page("Payment system not configured.", uid), status_code=500)
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
        r = requests.post(
            "https://api.flutterwave.com/v3/payments",
            json=payload,
            headers={"Authorization": f"Bearer {FLW_SECRET}"},
            timeout=20,
        ).json()
        if r.get("status") == "success" and r.get("data", {}).get("link"):
            return RedirectResponse(r["data"]["link"])
        return HTMLResponse(
            render_failed_page(r.get("message", "Payment failed"), uid), status_code=400,
        )
    except Exception as e:
        return HTMLResponse(render_failed_page(f"Error: {e}", uid), status_code=500)


@app.get("/verify")
async def verify(tx_ref: str, uid: str, plan: str):
    try:
        r = requests.get(
            f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}",
            headers={"Authorization": f"Bearer {FLW_SECRET}"}, timeout=20,
        ).json()
        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ("successful", "completed"):
                activate_vip(uid, plan)
                # Award referral
                try:
                    db = SessionLocal()
                    u = get_user(db, int(uid))
                    if u.referred_by:
                        award_referral(db, u.referred_by, int(uid))
                    db.close()
                except Exception as e:
                    print(f"Referral award error: {e}")
                return HTMLResponse(render_success_page(plan))
            return HTMLResponse(render_failed_page(f"Status: {data.get('status')}", uid), status_code=400)
        return HTMLResponse(render_failed_page("Transaction not found.", uid), status_code=404)
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
            try:
                db = SessionLocal()
                u = get_user(db, int(uid))
                if u.referred_by:
                    award_referral(db, u.referred_by, int(uid))
                db.close()
            except Exception:
                pass

        return JSONResponse({"status": "success"})
    except Exception as e:
        print(f"Webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)


# ──────────────────────────────────────────────
# PAYMENT PAGE TEMPLATES
# ──────────────────────────────────────────────
PAYMENT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="theme-color" content="#0a0e1a">
<title>BetMaster Pro — VIP Subscription</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:#0a0e1a; --card:rgba(255,255,255,0.03); --card-hover:rgba(255,255,255,0.05);
    --border:rgba(255,255,255,0.08); --border-hover:rgba(255,255,255,0.16);
    --text:#e8ecf5; --text-dim:#8b94ab; --text-dimmer:#5a6378;
    --green:#22c55e; --green-glow:rgba(34,197,94,0.35);
    --blue:#3b82f6; --blue-glow:rgba(59,130,246,0.35);
    --gold:#f5b945; --radius:16px; --radius-sm:10px;
  }
  html,body{height:100%;}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;
    background:var(--bg);color:var(--text);line-height:1.5;-webkit-font-smoothing:antialiased;
    overflow-x:hidden;position:relative;min-height:100vh;}
  body::before{content:"";position:fixed;top:-20%;left:50%;transform:translateX(-50%);
    width:900px;height:900px;background:radial-gradient(circle,rgba(34,197,94,0.10) 0%,transparent 60%);
    pointer-events:none;z-index:0;}
  body::after{content:"";position:fixed;bottom:-30%;right:-10%;width:700px;height:700px;
    background:radial-gradient(circle,rgba(59,130,246,0.08) 0%,transparent 60%);pointer-events:none;z-index:0;}
  .container{max-width:960px;margin:0 auto;padding:0 20px;position:relative;z-index:1;}
  nav{display:flex;align-items:center;justify-content:space-between;padding:20px 0;}
  .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;}
  .brand-logo{width:34px;height:34px;border-radius:10px;
    background:linear-gradient(135deg,#22c55e,#16a34a);display:flex;align-items:center;
    justify-content:center;box-shadow:0 0 20px var(--green-glow);flex-shrink:0;}
  .brand-logo svg{width:18px;height:18px;}
  .nav-cta{color:var(--text-dim);text-decoration:none;font-size:13px;font-weight:500;
    padding:8px 14px;border:1px solid var(--border);border-radius:999px;transition:all .2s;}
  .nav-cta:hover{border-color:var(--border-hover);color:var(--text);}
  .hero{text-align:center;padding:40px 0 32px;}
  .badge{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:999px;
    background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.20);color:#4ade80;
    font-size:12px;font-weight:600;margin-bottom:20px;}
  .badge-dot{width:6px;height:6px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;
    animation:pulse 2s infinite;}
  @keyframes pulse{0%,100%{opacity:1;}50%{opacity:.5;}}
  h1{font-size:40px;font-weight:700;letter-spacing:-.03em;line-height:1.1;margin-bottom:14px;
    background:linear-gradient(180deg,#fff,#b8c1d6);-webkit-background-clip:text;
    background-clip:text;-webkit-text-fill-color:transparent;}
  .hero p{color:var(--text-dim);font-size:16px;max-width:520px;margin:0 auto 28px;}
  .trust-row{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-bottom:8px;}
  .trust-pill{display:inline-flex;align-items:center;gap:7px;padding:8px 14px;background:var(--card);
    border:1px solid var(--border);border-radius:999px;font-size:12.5px;color:var(--text-dim);font-weight:500;}
  .trust-pill svg{width:14px;height:14px;color:var(--green);}
  .plans{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:40px 0 60px;}
  .plan{position:relative;background:var(--card);border:1px solid var(--border);
    border-radius:var(--radius);padding:26px 22px;transition:all .25s ease;overflow:hidden;}
  .plan:hover{background:var(--card-hover);border-color:var(--border-hover);transform:translateY(-2px);}
  .plan.featured{border-color:rgba(59,130,246,0.4);
    background:linear-gradient(180deg,rgba(59,130,246,0.06),rgba(59,130,246,0.02));
    box-shadow:0 20px 60px -20px var(--blue-glow);}
  .ribbon{position:absolute;top:14px;right:14px;padding:4px 10px;
    background:linear-gradient(135deg,#3b82f6,#2563eb);color:white;font-size:10.5px;
    font-weight:700;border-radius:6px;letter-spacing:.05em;text-transform:uppercase;
    box-shadow:0 4px 12px rgba(59,130,246,0.4);}
  .plan-name{font-size:13px;font-weight:600;color:var(--text-dim);letter-spacing:.08em;
    text-transform:uppercase;margin-bottom:12px;}
  .plan-price{display:flex;align-items:baseline;gap:6px;margin-bottom:6px;}
  .plan-price .amount{font-size:34px;font-weight:700;letter-spacing:-.03em;line-height:1;}
  .plan-price .period{font-size:14px;color:var(--text-dim);font-weight:500;}
  .plan-sub{color:var(--text-dimmer);font-size:13px;margin-bottom:20px;}
  .plan-sub strong{color:#4ade80;font-weight:600;}
  .plan-features{list-style:none;margin-bottom:22px;}
  .plan-features li{display:flex;align-items:flex-start;gap:10px;padding:6px 0;font-size:13.5px;}
  .plan-features li svg{width:15px;height:15px;color:var(--green);flex-shrink:0;margin-top:3px;}
  .btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;
    padding:14px 18px;border-radius:var(--radius-sm);font-size:14.5px;font-weight:600;
    text-decoration:none;border:none;cursor:pointer;transition:all .2s;font-family:inherit;
    position:relative;overflow:hidden;}
  .btn-primary{background:linear-gradient(135deg,#22c55e,#16a34a);color:white;
    box-shadow:0 8px 24px -8px var(--green-glow);}
  .btn-primary:hover{transform:translateY(-1px);}
  .btn-blue{background:linear-gradient(135deg,#3b82f6,#2563eb);color:white;
    box-shadow:0 8px 24px -8px var(--blue-glow);}
  .btn-blue:hover{transform:translateY(-1px);}
  .btn-gold{background:linear-gradient(135deg,#f5b945,#d97706);color:#0a0e1a;
    box-shadow:0 8px 24px -8px rgba(245,185,69,0.5);}
  .btn-gold:hover{transform:translateY(-1px);}
  .btn:disabled{opacity:.7;cursor:not-allowed;}
  .btn .spinner{width:16px;height:16px;border:2px solid rgba(255,255,255,0.3);
    border-top-color:white;border-radius:50%;animation:spin .7s linear infinite;display:none;}
  .btn.loading .spinner{display:block;}
  .btn.loading .btn-label{display:none;}
  @keyframes spin{to{transform:rotate(360deg);}}
  section{padding:40px 0;}
  .section-title{text-align:center;font-size:24px;font-weight:700;letter-spacing:-.02em;margin-bottom:8px;}
  .section-sub{text-align:center;color:var(--text-dim);font-size:14px;margin-bottom:32px;}
  .features-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
  .feature-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
    padding:22px 20px;transition:all .2s;}
  .feature-card:hover{background:var(--card-hover);border-color:var(--border-hover);}
  .feature-icon{width:40px;height:40px;border-radius:10px;background:rgba(34,197,94,0.10);
    display:flex;align-items:center;justify-content:center;margin-bottom:14px;}
  .feature-icon svg{width:20px;height:20px;color:var(--green);}
  .feature-card h3{font-size:15px;font-weight:600;margin-bottom:6px;}
  .feature-card p{font-size:13.5px;color:var(--text-dim);line-height:1.55;}
  .testimonials{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
  .testimonial{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
    padding:22px 20px;}
  .stars{color:var(--gold);font-size:14px;margin-bottom:10px;letter-spacing:2px;}
  .testimonial p{font-size:14px;line-height:1.6;margin-bottom:14px;}
  .testimonial-author{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--text-dim);}
  .avatar{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#2563eb);
    display:flex;align-items:center;justify-content:center;color:white;font-weight:600;font-size:13px;}
  .faq-list{max-width:680px;margin:0 auto;}
  .faq-item{border-bottom:1px solid var(--border);}
  .faq-item:first-child{border-top:1px solid var(--border);}
  .faq-q{display:flex;justify-content:space-between;align-items:center;padding:20px 4px;
    cursor:pointer;font-size:15px;font-weight:500;user-select:none;transition:color .2s;}
  .faq-q:hover{color:#4ade80;}
  .faq-q svg{width:18px;height:18px;color:var(--text-dim);transition:transform .25s;flex-shrink:0;}
  .faq-item.open .faq-q svg{transform:rotate(45deg);color:#4ade80;}
  .faq-a{max-height:0;overflow:hidden;transition:max-height .3s ease,padding .3s ease;
    color:var(--text-dim);font-size:14px;line-height:1.65;padding:0 4px;}
  .faq-item.open .faq-a{max-height:300px;padding:0 4px 20px;}
  footer{border-top:1px solid var(--border);padding:28px 0 40px;margin-top:40px;text-align:center;
    font-size:12.5px;color:var(--text-dimmer);}
  footer a{color:var(--text-dim);text-decoration:none;}
  footer a:hover{color:var(--text);}
  .footer-links{display:flex;justify-content:center;flex-wrap:wrap;gap:20px;margin-bottom:14px;}
  .disclaimer{max-width:500px;margin:14px auto 0;font-size:11.5px;line-height:1.55;color:var(--text-dimmer);}
  @media (max-width:720px){
    h1{font-size:30px;} .hero{padding:24px 0 20px;}
    .plans{grid-template-columns:1fr;gap:16px;margin:28px 0 40px;}
    .features-grid,.testimonials{grid-template-columns:1fr;}
    .plan-price .amount{font-size:30px;} section{padding:28px 0;}
    .section-title{font-size:20px;}
  }
  @media (max-width:420px){
    .container{padding:0 16px;} h1{font-size:26px;} .brand{font-size:15px;}
    .trust-pill{font-size:11.5px;padding:7px 11px;}
  }
</style>
</head>
<body>
<div class="container">
  <nav>
    <div class="brand">
      <div class="brand-logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </div>
      <span>BetMaster Pro</span>
    </div>
    <a class="nav-cta" href="{{BOT_LINK}}">Open Bot</a>
  </nav>

  <section class="hero">
    <div class="badge">
      <span class="badge-dot"></span>
      🚀 N1,000 → N1,000,000 Challenge
    </div>
    <h1>Unlock AI-Powered<br>Football Predictions</h1>
    <p>Dixon-Coles model · Value-bet detection · Global coverage · N1M accumulator generator · Personalized picks</p>
    <div class="trust-row">
      <div class="trust-pill">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        SSL Secured
      </div>
      <div class="trust-pill">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        Flutterwave
      </div>
      <div class="trust-pill">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z"/></svg>
        Trusted by 5,000+
      </div>
    </div>
  </section>

  <section style="padding-top:0;">
    <div class="plans">
      <div class="plan">
        <div class="plan-name">Daily</div>
        <div class="plan-price">
          <span class="amount">₦500</span>
          <span class="period">/ 24h</span>
        </div>
        <div class="plan-sub">Quick taste of VIP</div>
        <ul class="plan-features">
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>10 predictions</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>N1M challenge</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>10-match betslip</li>
        </ul>
        <a href="/pay?plan=daily&uid={{UID}}" class="btn btn-primary" onclick="return startPay(this)">
          <span class="spinner"></span>
          <span class="btn-label">Get 24h Access</span>
        </a>
      </div>

      <div class="plan featured">
        <div class="ribbon">Best Value</div>
        <div class="plan-name">Monthly</div>
        <div class="plan-price">
          <span class="amount">₦5,000</span>
          <span class="period">/ month</span>
        </div>
        <div class="plan-sub">Save <strong>₦3,000</strong> vs weekly</div>
        <ul class="plan-features">
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Everything in Weekly</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Priority support</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Early access to features</li>
        </ul>
        <a href="/pay?plan=monthly&uid={{UID}}" class="btn btn-blue" onclick="return startPay(this)">
          <span class="spinner"></span>
          <span class="btn-label">Get Monthly Access</span>
        </a>
      </div>

      <div class="plan">
        <div class="plan-name">Weekly</div>
        <div class="plan-price">
          <span class="amount">₦2,000</span>
          <span class="period">/ week</span>
        </div>
        <div class="plan-sub">Trying us out</div>
        <ul class="plan-features">
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>10 predictions/day</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>All markets + value bets</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Personalized picks</li>
        </ul>
        <a href="/pay?plan=weekly&uid={{UID}}" class="btn btn-primary" onclick="return startPay(this)">
          <span class="spinner"></span>
          <span class="btn-label">Get Weekly Access</span>
        </a>
      </div>
    </div>
  </section>

  <section>
    <div class="section-title">Why BetMaster Pro?</div>
    <div class="section-sub">Built with the same models used by professional sportsbooks.</div>
    <div class="features-grid">
      <div class="feature-card">
        <div class="feature-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>
        </div>
        <h3>Dixon-Coles Model</h3>
        <p>The industry-standard bivariate Poisson model used by pro bookmakers.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
        </div>
        <h3>N1M Challenge</h3>
        <p>Turn ₦1,000 into ₦1,000,000 with our high-odds accumulator builder.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        </div>
        <h3>Personalized</h3>
        <p>Learns your favorite leagues and markets. Ranks fixtures for you.</p>
      </div>
    </div>
  </section>

  <section>
    <div class="section-title">Loved by Bettors</div>
    <div class="testimonials">
      <div class="testimonial">
        <div class="stars">★★★★★</div>
        <p>"Won 3 accumulators in my first week. The N1M challenge is insane."</p>
        <div class="testimonial-author"><div class="avatar">E</div><span>Emeka · Lagos</span></div>
      </div>
      <div class="testimonial">
        <div class="stars">★★★★★</div>
        <p>"Finally a bot that explains its reasoning. Dixon-Coles is legit."</p>
        <div class="testimonial-author"><div class="avatar">T</div><span>Tunde · Abuja</span></div>
      </div>
      <div class="testimonial">
        <div class="stars">★★★★★</div>
        <p>"I stopped guessing. This pays for itself every single month."</p>
        <div class="testimonial-author"><div class="avatar">C</div><span>Chidi · PH</span></div>
      </div>
    </div>
  </section>

  <section>
    <div class="section-title">Frequently Asked</div>
    <div class="faq-list">
      <div class="faq-item">
        <div class="faq-q">How do I receive predictions after paying?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Once payment confirms, your Telegram is instantly upgraded. Use /today, /europeanleagues, /asianleagues, /americanleagues, /national, /million or /betslip.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">What payment methods work?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Cards, bank transfer, USSD, mobile money via Flutterwave.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">What is the N1M Challenge?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Our AI builds a high-odds accumulator where ₦1,000 could win up to ₦1,000,000. High risk, high reward — bet only what you can afford to lose.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">Is my payment secure?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Yes. Processed by Flutterwave, PCI-DSS Level 1 certified. We never see your card details.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">Do you guarantee winnings?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">No service can guarantee winnings. We provide statistically-backed predictions with measurable edge. Bet responsibly.</div>
      </div>
    </div>
  </section>

  <footer>
    <div class="footer-links">
      <a href="{{BOT_LINK}}">Telegram Bot</a>
      <a href="/">Status</a>
      <a href="mailto:support@betmasterpro.com">Support</a>
    </div>
    <div>© {{YEAR}} BetMaster Pro. All rights reserved.</div>
    <div class="disclaimer">18+ only. Gambling involves risk. Bet only what you can afford to lose.</div>
  </footer>
</div>
<script>
  document.querySelectorAll('.faq-q').forEach(function(q){
    q.addEventListener('click',function(){q.parentElement.classList.toggle('open');});
  });
  function startPay(btn){btn.classList.add('loading');btn.disabled=true;return true;}
</script>
</body>
</html>"""


SUCCESS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Payment Successful — BetMaster Pro</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;
    background:#0a0e1a;color:#e8ecf5;min-height:100vh;display:flex;align-items:center;
    justify-content:center;padding:24px;margin:0;position:relative;overflow:hidden;}
  body::before{content:"";position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
    width:700px;height:700px;background:radial-gradient(circle,rgba(34,197,94,.15) 0%,transparent 60%);
    pointer-events:none;}
  .card{position:relative;background:rgba(255,255,255,.03);border:1px solid rgba(34,197,94,.25);
    border-radius:20px;padding:48px 36px;max-width:440px;width:100%;text-align:center;
    box-shadow:0 30px 80px -30px rgba(34,197,94,.4);}
  .check{width:80px;height:80px;border-radius:50%;background:linear-gradient(135deg,#22c55e,#16a34a);
    display:flex;align-items:center;justify-content:center;margin:0 auto 24px;
    box-shadow:0 0 40px rgba(34,197,94,.5);animation:pop .5s cubic-bezier(.68,-.55,.27,1.55);}
  @keyframes pop{0%{transform:scale(0);opacity:0;}100%{transform:scale(1);opacity:1;}}
  .check svg{width:40px;height:40px;}
  h1{font-size:26px;font-weight:700;margin-bottom:10px;
    background:linear-gradient(180deg,#fff,#b8c1d6);-webkit-background-clip:text;
    background-clip:text;-webkit-text-fill-color:transparent;}
  p{color:#8b94ab;font-size:15px;line-height:1.6;margin-bottom:28px;}
  .plan-badge{display:inline-block;padding:6px 14px;background:rgba(34,197,94,.1);
    border:1px solid rgba(34,197,94,.25);border-radius:999px;color:#4ade80;font-size:13px;
    font-weight:600;margin-bottom:20px;letter-spacing:.05em;text-transform:uppercase;}
  .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:15px 28px;
    background:linear-gradient(135deg,#22c55e,#16a34a);color:white;text-decoration:none;
    border-radius:12px;font-weight:600;font-size:15px;box-shadow:0 10px 30px -10px rgba(34,197,94,.5);
    transition:all .2s;width:100%;}
  .btn:hover{transform:translateY(-1px);}
  .btn svg{width:18px;height:18px;}
</style>
</head>
<body>
<div class="card">
  <div class="check"><svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></div>
  <div class="plan-badge">{{PLAN}} Activated</div>
  <h1>Welcome to VIP!</h1>
  <p>Your payment was confirmed. Return to the bot to access premium AI predictions, the N1M challenge, and personalized betslips.</p>
  <a href="{{BOT_LINK}}" class="btn">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>
    Open Telegram Bot
  </a>
</div>
</body>
</html>"""


FAILED_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Payment Issue — BetMaster Pro</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;
    background:#0a0e1a;color:#e8ecf5;min-height:100vh;display:flex;align-items:center;
    justify-content:center;padding:24px;margin:0;position:relative;overflow:hidden;}
  body::before{content:"";position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
    width:700px;height:700px;background:radial-gradient(circle,rgba(239,68,68,.12) 0%,transparent 60%);
    pointer-events:none;}
  .card{position:relative;background:rgba(255,255,255,.03);border:1px solid rgba(239,68,68,.25);
    border-radius:20px;padding:48px 36px;max-width:440px;width:100%;text-align:center;
    box-shadow:0 30px 80px -30px rgba(239,68,68,.35);}
  .icon{width:80px;height:80px;border-radius:50%;background:linear-gradient(135deg,#ef4444,#dc2626);
    display:flex;align-items:center;justify-content:center;margin:0 auto 24px;
    box-shadow:0 0 40px rgba(239,68,68,.4);}
  .icon svg{width:40px;height:40px;}
  h1{font-size:24px;font-weight:700;margin-bottom:10px;color:#fca5a5;}
  p{color:#8b94ab;font-size:15px;line-height:1.6;margin-bottom:12px;}
  .reason{background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.06);border-radius:10px;
    padding:14px 16px;font-size:13px;color:#cbd5e1;font-family:ui-monospace,Menlo,monospace;
    margin:20px 0 24px;word-break:break-word;text-align:left;}
  .actions{display:flex;flex-direction:column;gap:10px;}
  .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 24px;
    border-radius:12px;font-weight:600;font-size:14.5px;text-decoration:none;transition:all .2s;width:100%;}
  .btn-primary{background:linear-gradient(135deg,#22c55e,#16a34a);color:white;
    box-shadow:0 10px 30px -10px rgba(34,197,94,.5);}
  .btn-secondary{background:transparent;color:#8b94ab;border:1px solid rgba(255,255,255,.1);}
</style>
</head>
<body>
<div class="card">
  <div class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></div>
  <h1>Payment Not Confirmed</h1>
  <p>We couldn't verify your transaction. If you were charged, contact support with the reference below.</p>
  <div class="reason">{{REASON}}</div>
  <div class="actions">
    <a href="/subscribe?uid={{UID}}" class="btn btn-primary">Try Again</a>
    <a href="{{BOT_LINK}}" class="btn btn-secondary">Contact Support</a>
  </div>
</div>
</body>
</html>"""


def render_payment_page(uid):
    from datetime import datetime as _dt
    return (PAYMENT_TEMPLATE
            .replace("{{UID}}", str(uid))
            .replace("{{BOT_LINK}}", BOT_LINK)
            .replace("{{YEAR}}", str(_dt.now().year)))


def render_success_page(plan):
    return SUCCESS_TEMPLATE.replace("{{PLAN}}", plan.upper()).replace("{{BOT_LINK}}", BOT_LINK)


def render_failed_page(reason, uid=""):
    return (FAILED_TEMPLATE
            .replace("{{REASON}}", html.escape(str(reason))[:500])
            .replace("{{UID}}", str(uid))
            .replace("{{BOT_LINK}}", BOT_LINK))


# ──────────────────────────────────────────────
# RUN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
