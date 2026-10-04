"""
main.py — BetMaster Pro
Global soccer prediction bot with Dixon-Coles modeling, value-bet detection,
and multi-region coverage (Europe / Asia / Americas / National teams).

Data sources: ESPN hidden API, TheSportsDB, OpenFootball JSON, The Odds API.
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
THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")
FOOTYSTATS_KEY = os.getenv("FOOTYSTATS_KEY", "")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"
BOT_HANDLE = "@Betmasterpro_bot"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────
from sqlalchemy import create_engine, Column, Integer, String, Boolean
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
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base = declarative_base()
except Exception:
    engine = create_engine("sqlite:///./betmaster.db",
                           connect_args={"check_same_thread": False})
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


try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"DB init error: {e}")


def get_user(db, user_id, username=""):
    today_str = str(date.today())
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            user = User(user_id=user_id, username=username,
                        last_reset=today_str, daily_count=0)
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
            db.commit()
        return user
    except Exception as e:
        print(f"get_user error: {e}")
        class Dummy:
            user_id = user_id
            daily_count = 0
            is_vip = False
            vip_expiry = ""
        return Dummy()


# ──────────────────────────────────────────────
# BRAIN: historical stats from football-data.co.uk
# ──────────────────────────────────────────────
HISTORICAL_STATS = {}
H2H_CACHE = {}
FOOTYSTATS_CACHE = {}
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
    """Load historical stats from football-data.co.uk CSVs (Europe only)."""
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
                    if fthg == 0:
                        HISTORICAL_STATS[home]["failed_score"] += 1
                    if ftag == 0:
                        HISTORICAL_STATS[away]["failed_score"] += 1
                    if ftag == 0:
                        HISTORICAL_STATS[home]["clean"] += 1
                    if fthg == 0:
                        HISTORICAL_STATS[away]["clean"] += 1

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

            # Trim form to last 5
            for k in HISTORICAL_STATS:
                if len(HISTORICAL_STATS[k]["form"]) > 5:
                    HISTORICAL_STATS[k]["form"] = HISTORICAL_STATS[k]["form"][-5:]

        except Exception as e:
            print(f"Brain load error {code}: {e}")

    # Fallback league averages if missing
    for code in codes:
        if code not in LEAGUE_AVG_GOALS:
            LEAGUE_AVG_GOALS[code] = 2.65

    print(f"BRAIN loaded {len(HISTORICAL_STATS)} teams, "
          f"H2H {len(H2H_CACHE)} pairs, {len(LEAGUE_AVG_GOALS)} leagues")


# ──────────────────────────────────────────────
# DIXON-COLES POISSON MODEL
# ──────────────────────────────────────────────
def estimate_team_strengths(team_name, league_code="E0"):
    """Estimate attack/defense strengths from historical stats."""
    stats = HISTORICAL_STATS.get(team_name)
    league_avg = LEAGUE_AVG_GOALS.get(league_code, 2.65) / 2.0  # per-team avg

    if not stats or stats["games"] < 3:
        # Neutral fallback
        return {"attack": 1.0, "defense": 1.0, "games": 0, "source": "neutral"}

    games = stats["games"]
    avg_scored = stats["scored"] / games
    avg_conceded = stats["conceded"] / games

    # Strength = team_avg / league_avg
    attack = avg_scored / league_avg if league_avg > 0 else 1.0
    defense = avg_conceded / league_avg if league_avg > 0 else 1.0

    # Clamp to reasonable range
    attack = max(0.4, min(2.5, attack))
    defense = max(0.4, min(2.5, defense))

    return {
        "attack": round(attack, 3),
        "defense": round(defense, 3),
        "games": games,
        "avg_scored": round(avg_scored, 2),
        "avg_conceded": round(avg_conceded, 2),
        "source": "historical",
    }


def dixon_coles_predict(home_team, away_team, league_code="E0",
                        home_advantage=0.20, rho=-0.05, max_goals=6):
    """
    Dixon-Coles Poisson prediction.
    Returns win/draw/loss probabilities, expected goals, top scorelines.
    """
    h = estimate_team_strengths(home_team, league_code)
    a = estimate_team_strengths(away_team, league_code)

    league_avg_per_team = LEAGUE_AVG_GOALS.get(league_code, 2.65) / 2.0

    # Expected goals
    home_xg = h["attack"] * a["defense"] * league_avg_per_team * math.exp(home_advantage)
    away_xg = a["attack"] * h["defense"] * league_avg_per_team

    # Clamp xG
    home_xg = max(0.3, min(4.5, home_xg))
    away_xg = max(0.3, min(4.5, away_xg))

    # Build scoreline probability matrix
    probs = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson.pmf(i, home_xg) * poisson.pmf(j, away_xg)
            # Dixon-Coles low-score correction
            if i <= 1 and j <= 1:
                if i == 0 and j == 0:
                    p *= (1 - home_xg * away_xg * rho)
                elif i == 0 and j == 1:
                    p *= (1 + home_xg * rho)
                elif i == 1 and j == 0:
                    p *= (1 + away_xg * rho)
                elif i == 1 and j == 1:
                    p *= (1 - rho)
            probs[i][j] = max(0, p)

    total = probs.sum()
    if total <= 0:
        return {
            "home_win": 33.3, "draw": 33.3, "away_win": 33.3,
            "home_xg": round(home_xg, 2), "away_xg": round(away_xg, 2),
            "top_scorelines": [], "btts": 50.0, "over25": 50.0,
            "home_strength": h, "away_strength": a,
        }
    probs /= total

    home_win = float(np.tril(probs, -1).sum()) * 100
    draw = float(np.trace(probs)) * 100
    away_win = float(np.triu(probs, 1).sum()) * 100

    # BTTS = P(home >= 1 AND away >= 1)
    btts = float(probs[1:, 1:].sum()) * 100

    # Over 2.5 = P(total >= 3)
    over25 = 0.0
    for i in range(max_goals):
        for j in range(max_goals):
            if i + j >= 3:
                over25 += probs[i][j]
    over25 *= 100

    over15 = 0.0
    for i in range(max_goals):
        for j in range(max_goals):
            if i + j >= 2:
                over15 += probs[i][j]
    over15 *= 100

    over35 = 0.0
    for i in range(max_goals):
        for j in range(max_goals):
            if i + j >= 4:
                over35 += probs[i][j]
    over35 *= 100

    # Top 5 scorelines
    scores = []
    for i in range(max_goals):
        for j in range(max_goals):
            scores.append((f"{i}-{j}", round(float(probs[i][j]) * 100, 2)))
    scores.sort(key=lambda x: x[1], reverse=True)
    top_scorelines = scores[:5]

    # Most likely correct score
    top_cs = top_scorelines[0][0] if top_scorelines else "1-0"

    return {
        "home_win": round(home_win, 1),
        "draw": round(draw, 1),
        "away_win": round(away_win, 1),
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
        "btts": round(btts, 1),
        "over15": round(over15, 1),
        "over25": round(over25, 1),
        "over35": round(over35, 1),
        "top_scorelines": top_scorelines,
        "top_cs": top_cs,
        "home_strength": h,
        "away_strength": a,
    }


def find_value_bets(model_probs, odds):
    """Compare model probabilities against bookmaker implied probabilities."""
    value_bets = []
    markets = {
        "Home Win": (model_probs.get("home_win", 0), odds.get("home")),
        "Draw":     (model_probs.get("draw", 0), odds.get("draw")),
        "Away Win": (model_probs.get("away_win", 0), odds.get("away")),
    }

    for market, (model_prob, odd) in markets.items():
        if not odd or odd <= 1.01:
            continue
        implied = 100.0 / odd
        edge = model_prob - implied
        if edge > 3.0:
            kelly = max(0.0, (edge / 100.0 * odd - 1) / (odd - 1)) * 100
            value_bets.append({
                "market": market,
                "model_prob": round(model_probs.get("home_win" if "Home" in market else
                                                     "draw" if market == "Draw" else
                                                     "away_win", 0), 1),
                "implied": round(implied, 1),
                "edge": round(edge, 1),
                "odds": odd,
                "kelly": round(min(kelly, 15), 1),
            })

    value_bets.sort(key=lambda x: x["edge"], reverse=True)
    return value_bets


# ──────────────────────────────────────────────
# MASTER PREDICTION ENGINE
# ──────────────────────────────────────────────
def predict_match(data):
    """
    Master prediction engine.
    Uses Dixon-Coles + historical form + H2H + value bets.
    """
    home = data.get("home", "Home")
    away = data.get("away", "Away")
    league = data.get("league", "")
    league_code = data.get("country", "E0")
    if league_code not in LEAGUE_AVG_GOALS:
        league_code = "E0"

    # Dixon-Coles
    dc = dixon_coles_predict(home, away, league_code=league_code)

    # H2H
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

    # Blend DC probabilities with H2H evidence (small weight)
    dc_h, dc_d, dc_a = dc["home_win"], dc["draw"], dc["away_win"]
    if h2h_games and len(h2h_games) >= 3:
        h2h_total = len(h2h_games)
        h2h_h_pct = h2h_home_wins / h2h_total * 100
        h2h_d_pct = h2h_draws / h2h_total * 100
        h2h_a_pct = h2h_away_wins / h2h_total * 100
        w = 0.20
        dc_h = dc_h * (1 - w) + h2h_h_pct * w
        dc_d = dc_d * (1 - w) + h2h_d_pct * w
        dc_a = dc_a * (1 - w) + h2h_a_pct * w

    # Normalize
    tot = dc_h + dc_d + dc_a
    if tot > 0:
        dc_h, dc_d, dc_a = dc_h / tot * 100, dc_d / tot * 100, dc_a / tot * 100

    model_probs = {
        "home_win": round(dc_h, 1),
        "draw": round(dc_d, 1),
        "away_win": round(dc_a, 1),
    }

    # Odds
    odds = {
        "home": float(data.get("odds_h", 0) or 0),
        "draw": float(data.get("odds_d", 0) or 0),
        "away": float(data.get("odds_a", 0) or 0),
    }
    # Fallback odds if missing
    if odds["home"] <= 1.01:
        odds["home"] = round(100 / max(model_probs["home_win"], 5), 2)
    if odds["draw"] <= 1.01:
        odds["draw"] = round(100 / max(model_probs["draw"], 5), 2)
    if odds["away"] <= 1.01:
        odds["away"] = round(100 / max(model_probs["away_win"], 5), 2)

    # Build markets
    markets = []

    # 1X2 markets
    best_1x2 = max(
        [("Home Win", model_probs["home_win"], odds["home"]),
         ("Draw", model_probs["draw"], odds["draw"]),
         ("Away Win", model_probs["away_win"], odds["away"])],
        key=lambda x: x[1],
    )
    if best_1x2[1] >= 40:
        markets.append({
            "market": "1X2",
            "pick": best_1x2[0],
            "odds": best_1x2[2],
            "conf": round(best_1x2[1], 1),
            "reason": f"Dixon-Coles model gives {best_1x2[0]} {best_1x2[1]:.1f}% probability. "
                      f"xG: {home} {dc['home_xg']} vs {away} {dc['away_xg']}.",
        })

    # Double Chance
    dc_1x = model_probs["home_win"] + model_probs["draw"]
    dc_x2 = model_probs["draw"] + model_probs["away_win"]
    dc_12 = model_probs["home_win"] + model_probs["away_win"]

    if dc_1x >= 70:
        markets.append({
            "market": "DC",
            "pick": f"{home} Win or Draw (1X)",
            "odds": round(1.01 + (100 - dc_1x) / 100, 2),
            "conf": round(dc_1x, 1),
            "reason": f"Model: {dc_1x:.1f}% chance {home} does not lose.",
        })
    if dc_x2 >= 70:
        markets.append({
            "market": "DC",
            "pick": f"{away} Win or Draw (X2)",
            "odds": round(1.01 + (100 - dc_x2) / 100, 2),
            "conf": round(dc_x2, 1),
            "reason": f"Model: {dc_x2:.1f}% chance {away} does not lose.",
        })

    # BTTS
    if dc["btts"] >= 60:
        markets.append({
            "market": "BTTS",
            "pick": "BTTS Yes",
            "odds": float(data.get("odds_btts", 1.85) or 1.85),
            "conf": round(dc["btts"], 1),
            "reason": f"Model: BTTS probability {dc['btts']}%. "
                      f"xG {home} {dc['home_xg']} vs {away} {dc['away_xg']}.",
        })
    elif dc["btts"] <= 40:
        markets.append({
            "market": "BTTS",
            "pick": "BTTS No",
            "odds": 1.85,
            "conf": round(100 - dc["btts"], 1),
            "reason": f"Model: BTTS probability only {dc['btts']}%.",
        })

    # Over/Under
    if dc["over25"] >= 60:
        markets.append({
            "market": "O/U",
            "pick": "Over 2.5 Goals",
            "odds": float(data.get("odds_over25", 1.90) or 1.90),
            "conf": round(dc["over25"], 1),
            "reason": f"Model: Over 2.5 probability {dc['over25']}%. "
                      f"Total xG {dc['home_xg'] + dc['away_xg']:.2f}.",
        })
    elif dc["over25"] <= 40:
        markets.append({
            "market": "O/U",
            "pick": "Under 2.5 Goals",
            "odds": 1.90,
            "conf": round(100 - dc["over25"], 1),
            "reason": f"Model: Under 2.5 probability {100 - dc['over25']:.1f}%.",
        })

    if dc["over15"] >= 75:
        markets.append({
            "market": "O/U",
            "pick": "Over 1.5 Goals",
            "odds": 1.30,
            "conf": round(dc["over15"], 1),
            "reason": f"Model: Over 1.5 probability {dc['over15']}% — banker.",
        })

    # If still nothing (rare), force a pick
    if not markets:
        top = max(
            [("Home Win", model_probs["home_win"], odds["home"]),
             ("Draw", model_probs["draw"], odds["draw"]),
             ("Away Win", model_probs["away_win"], odds["away"])],
            key=lambda x: x[1],
        )
        markets.append({
            "market": "1X2",
            "pick": top[0],
            "odds": top[2],
            "conf": round(top[1], 1),
            "reason": f"Best available pick — {top[0]} at {top[1]:.1f}%.",
        })

    markets.sort(key=lambda x: x["conf"], reverse=True)
    best = markets[0]

    # Value bets
    vb = find_value_bets(model_probs, odds)

    # Form strings
    h_stats = HISTORICAL_STATS.get(home, {})
    a_stats = HISTORICAL_STATS.get(away, {})
    h_form = "".join(h_stats.get("form", [])[:5]) or "N/A"
    a_form = "".join(a_stats.get("form", [])[:5]) or "N/A"

    h2h_str = "No H2H data"
    if h2h_games:
        h2h_str = (f"H2H last {len(h2h_games)}: {home} {h2h_home_wins}W "
                   f"{h2h_draws}D {h2h_away_wins}W, BTTS {h2h_btts}/{len(h2h_games)}, "
                   f"Avg {h2h_avg_goals:.1f} goals")

    form_str = (f"Form: {home} [{h_form}] | {away} [{a_form}]")

    standings_str = (
        f"Dixon-Coles xG: {home} {dc['home_xg']} — {away} {dc['away_xg']} | "
        f"1X2: {model_probs['home_win']}% / {model_probs['draw']}% / "
        f"{model_probs['away_win']}%"
    )

    # Verdict
    verdict = f"AI RECOMMENDS: {best['market']} — {best['pick']} @ {best['odds']}"

    explanation = best["reason"]
    if vb:
        explanation += (f"\nVALUE BET: {vb[0]['market']} @ {vb[0]['odds']} "
                        f"(model {vb[0]['model_prob']}% vs implied {vb[0]['implied']}%, "
                        f"edge +{vb[0]['edge']}%)")

    explanation += (f"\nTop scorelines: "
                    + ", ".join(f"{s[0]} ({s[1]}%)" for s in dc["top_scorelines"][:3]))

    return {
        "best_market": best["market"],
        "best_pick": best["pick"],
        "odds": float(best["odds"]),
        "confidence": best["conf"],
        "explanation": explanation,
        "verdict": verdict,
        "all_markets": markets[:5],
        "value_bets": vb,
        "h2h": h2h_str,
        "form": form_str,
        "standings": standings_str,
        "footystats": f"Brain: {len(HISTORICAL_STATS)} teams, H2H {len(h2h_games)} games",
        "live_odds_source": data.get("source", "Model"),
        "winnings_1000": calc(best["odds"], 1000),
        "winnings_2000": calc(best["odds"], 2000),
        "dc": dc,
        "disclaimer": "\n\n18+ Bet responsibly. Dixon-Coles model + H2H + value-bet detection.",
    }


# Backwards-compatible alias
get_dynamic_ai_prediction = predict_match


# ──────────────────────────────────────────────
# ODDS FETCHER — The Odds API
# ──────────────────────────────────────────────
def fetch_the_odds_api(date_obj):
    global ODDS_CACHE
    if not THE_ODDS_API_KEY:
        return {}
    if (ODDS_CACHE["time"] and
            (datetime.now() - ODDS_CACHE["time"]).seconds < 600 and
            ODDS_CACHE["data"]):
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
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
            params = {
                "apiKey": THE_ODDS_API_KEY,
                "regions": "eu,uk",
                "markets": "h2h,totals,btts",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                continue

            for game in r.json():
                try:
                    home = game["home_team"]
                    away = game["away_team"]
                    if game["commence_time"][:10] != iso:
                        continue

                    best_h = best_d = best_a = 0
                    best_over25 = best_btts = 0

                    for bk in game.get("bookmakers", [])[:6]:
                        for market in bk.get("markets", []):
                            if market["key"] == "h2h":
                                for o in market["outcomes"]:
                                    if o["name"] == home:
                                        best_h = max(best_h, o["price"])
                                    elif o["name"] == away:
                                        best_a = max(best_a, o["price"])
                                    elif o["name"] == "Draw":
                                        best_d = max(best_d, o["price"])
                            elif market["key"] == "totals":
                                for o in market["outcomes"]:
                                    if o["name"] == "Over" and o.get("point") == 2.5:
                                        best_over25 = max(best_over25, o["price"])
                            elif market["key"] == "btts":
                                for o in market["outcomes"]:
                                    if o["name"] == "Yes":
                                        best_btts = max(best_btts, o["price"])

                    key = f"{home}_vs_{away}"
                    odds_map[key] = {
                        "home": home, "away": away,
                        "league": game.get("sport_title", ""),
                        "odds_h": best_h or 0,
                        "odds_d": best_d or 0,
                        "odds_a": best_a or 0,
                        "odds_over25": best_over25 or 0,
                        "odds_btts": best_btts or 0,
                        "source": "LIVE (Bet365/Pinnacle)",
                    }
                except Exception:
                    continue
        except Exception:
            continue

    ODDS_CACHE = {"time": datetime.now(), "data": odds_map}
    print(f"Odds API: {len(odds_map)} games for {iso}")
    return odds_map


def enrich_with_odds(fixtures, date_obj):
    """Attach live odds to fixtures when available."""
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
            f.setdefault("odds_h", 0)
            f.setdefault("odds_d", 0)
            f.setdefault("odds_a", 0)
            f.setdefault("odds_over25", 0)
            f.setdefault("odds_btts", 0)
            f.setdefault("source", "Model")
    return fixtures


# ──────────────────────────────────────────────
# IMPORTS FROM fetcher.py
# ──────────────────────────────────────────────
from fetcher import (
    fetch_today_fixtures,
    fetch_by_region,
    fetch_espn,
    fetch_thesportsdb,
    fetch_openfootball_national,
    deduplicate,
)


def fetch_real_fixtures(days_ahead=0, limit=10, region=None):
    """Master fixture fetcher for main.py handlers."""
    target = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=days_ahead)).date()

    if region:
        fixtures = fetch_by_region(target, region, limit=limit)
    else:
        fixtures = fetch_today_fixtures(target, limit=limit)

    if not fixtures and days_ahead == 0:
        # Try tomorrow
        for i in range(1, 8):
            target2 = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=i)).date()
            if region:
                fixtures = fetch_by_region(target2, region, limit=limit)
            else:
                fixtures = fetch_today_fixtures(target2, limit=limit)
            if fixtures:
                break

    return enrich_with_odds(fixtures, target)


# ──────────────────────────────────────────────
# BETSLIP GENERATOR
# ──────────────────────────────────────────────
def generate_betslip(fixtures):
    if len(fixtures) < 5:
        return None
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
        "picks": picks,
        "total_odds": total,
        "winnings_1000": round(total * 1000, 2),
        "winnings_2000": round(total * 2000, 2),
    }


# ──────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────
app = FastAPI()


def send_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "..."
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
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
        {"command": "betslip",          "description": "VIP 10-match betslip"},
        {"command": "upgrade",          "description": "Upgrade to VIP"},
        {"command": "help",             "description": "Help"},
        {"command": "start",            "description": "Start"},
    ]
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        requests.post(url, json={"commands": commands}, timeout=10)
    except Exception:
        pass


def activate_vip(uid, plan):
    db = SessionLocal()
    try:
        user = get_user(db, int(uid))
        days = 7 if "weekly" in plan else 30
        expiry = date.today() + timedelta(days=days)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.daily_count = 0
        db.commit()
        send_message(int(uid), f"VIP {plan.upper()} activated until {expiry}\n{BOT_LINK}")
        return True
    except Exception as e:
        print(f"activate_vip error: {e}")
        return False
    finally:
        db.close()


# ──────────────────────────────────────────────
# REGION / COMMAND HANDLERS
# ──────────────────────────────────────────────
REGION_INFO = {
    "european": ("🇪🇺 EUROPEAN LEAGUES", "European"),
    "asian":    ("🇯🇵 ASIAN LEAGUES",    "Asian"),
    "american": ("🇺🇸 AMERICAN LEAGUES", "American"),
    "national": ("🌍 NATIONAL TEAMS / FIFA", "National"),
}


def handle_region(chat_id, user_id, region, user, db, limit):
    """Generic handler for /europeanleagues /asianleagues /americanleagues /national."""
    header, pretty = REGION_INFO.get(region, ("FIXTURES", region.title()))

    if user.daily_count >= limit:
        send_message(chat_id,
                     f"Daily limit reached ({user.daily_count}/{limit}).\n"
                     f"Upgrade: {RENDER_URL}/subscribe?uid={user_id}")
        return

    send_message(chat_id, f"🔎 Scanning {pretty} fixtures for today...")

    fixtures = fetch_real_fixtures(days_ahead=0, limit=15, region=region)

    if not fixtures:
        # Try next few days
        for i in range(1, 8):
            fixtures = fetch_real_fixtures(days_ahead=i, limit=15, region=region)
            if fixtures:
                break

    if not fixtures:
        send_message(chat_id, f"No {pretty} fixtures found in the next 7 days.\n{BOT_LINK}")
        return

    msg = f"{header}\n📅 {fixtures[0].get('date', 'Today')}\n\n"
    for i, f in enumerate(fixtures, 1):
        msg += (f"{i}. {f['home']} vs {f['away']}\n"
                f"   🏆 {f.get('league', '')}\n"
                f"   🕐 {f.get('time', '')} WAT\n\n")

    msg += f"({user.daily_count}/{limit}) — Tap below for full analysis\n{BOT_LINK}"

    keyboard = {"inline_keyboard": [[
        {"text": f"🧠 Predict {pretty} Top 5", "callback_data": f"predict_{region}"},
        {"text": "💰 VIP 10-Match Betslip", "callback_data": "generate_betslip"},
    ]]}

    send_message(chat_id, msg, reply_markup=keyboard)


def send_full_prediction(chat_id, fixture, user, db, limit):
    """Send detailed prediction for one fixture."""
    p = predict_match(fixture)
    msg = (
        f"⚽ {fixture['home']} vs {fixture['away']}\n"
        f"🏆 {fixture.get('league','')} | {fixture.get('date','')} {fixture.get('time','')} WAT\n\n"
        f"📊 {p['form']}\n"
        f"📈 {p['h2h']}\n"
        f"📉 {p['standings']}\n\n"
        f"✅ {p['verdict']} ({p['confidence']}%)\n"
        f"📝 {p['explanation']}\n\n"
        f"📋 ALL MARKETS:\n"
    )
    for m in p["all_markets"][:4]:
        msg += f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"

    if p.get("value_bets"):
        msg += "\n💎 VALUE BETS:\n"
        for v in p["value_bets"][:2]:
            msg += f"• {v['market']} @ {v['odds']} (edge +{v['edge']}%)\n"

    msg += (f"\n💰 N1000 → N{p['winnings_1000']}\n"
            f"📡 Source: {p['live_odds_source']}\n"
            f"{p['disclaimer']}")

    send_message(chat_id, msg)


# ──────────────────────────────────────────────
# UPDATE PROCESSOR
# ──────────────────────────────────────────────
def process_update(upd):
    try:
        base = f"https://api.telegram.org/bot{BOT_TOKEN}"

        # ── Callback queries ──
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            from_id = cq["from"]["id"]
            data = cq.get("data", "")

            requests.post(f"{base}/answerCallbackQuery",
                          json={"callback_query_id": cq["id"], "text": "Analyzing..."},
                          timeout=5)

            db2 = SessionLocal()
            try:
                user2 = get_user(db2, from_id)
                limit = 10 if user2.is_vip else 2

                if data.startswith("predict_"):
                    region = data.replace("predict_", "")
                    if user2.daily_count >= limit:
                        send_message(chat_id,
                                     f"Limit {user2.daily_count}/{limit}\n"
                                     f"{RENDER_URL}/subscribe?uid={from_id}")
                        return

                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5, region=region)
                    if not fixtures:
                        for i in range(1, 8):
                            fixtures = fetch_real_fixtures(days_ahead=i, limit=5, region=region)
                            if fixtures:
                                break

                    if not fixtures:
                        send_message(chat_id, f"No fixtures found for {region}.\n{BOT_LINK}")
                        return

                    send_message(chat_id, f"🧠 AI Analysis for {region.title()} — Top 5")
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit:
                            break
                        send_full_prediction(chat_id, f, user2, db2, limit)
                        user2.daily_count += 1
                        db2.commit()
                        time.sleep(0.8)

                elif data == "predict_top5":
                    if user2.daily_count >= limit:
                        send_message(chat_id,
                                     f"Limit {user2.daily_count}/{limit}\n"
                                     f"{RENDER_URL}/subscribe?uid={from_id}")
                        return

                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    if not fixtures:
                        send_message(chat_id, f"No fixtures today.\n{BOT_LINK}")
                        return

                    send_message(chat_id, "🧠 AI Analysis — Top 5")
                    for f in fixtures[:5]:
                        if user2.daily_count >= limit:
                            break
                        send_full_prediction(chat_id, f, user2, db2, limit)
                        user2.daily_count += 1
                        db2.commit()
                        time.sleep(0.8)

                elif data == "generate_betslip":
                    if not user2.is_vip:
                        send_message(chat_id,
                                     f"VIP only — 10-match dynamic betslip.\n"
                                     f"{RENDER_URL}/subscribe?uid={from_id}")
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

                    slip = generate_betslip(fixtures)
                    if not slip:
                        send_message(chat_id, f"Not enough fixtures ({len(fixtures)}).")
                        return

                    msg = (f"💰 VIP BETSLIP — {datetime.now().strftime('%d %b %Y')}\n"
                           f"10 matches · Dixon-Coles model\n\n")
                    for i, p in enumerate(slip["picks"], 1):
                        msg += (f"{i}. {p['match']}\n"
                                f"   {p['market']}: {p['pick']} @ {p['odds']} ({p['conf']}%)\n\n")
                    msg += (f"TOTAL ODDS: {slip['total_odds']}\n"
                            f"N1000 → N{slip['winnings_1000']}\n"
                            f"N2000 → N{slip['winnings_2000']}\n{BOT_LINK}")
                    send_message(chat_id, msg)

            finally:
                db2.close()
            return

        # ── Messages ──
        msg = upd.get("message")
        if not msg or "text" not in msg or msg["chat"]["type"] != "private":
            return

        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        user_id = msg["from"]["id"]
        low = text.lower()

        db = SessionLocal()
        try:
            user = get_user(db, user_id)
            FREE, VIP = 2, 10
            cur = VIP if user.is_vip else FREE

            # ── /start ──
            if low.startswith("/start"):
                send_message(chat_id, (
                    f"👋 Welcome to BetMaster Pro\n\n"
                    f"🧠 Dixon-Coles AI prediction engine\n"
                    f"🌍 Global coverage: Europe · Asia · Americas · National\n"
                    f"💎 Value-bet detection vs live odds\n\n"
                    f"Commands:\n"
                    f"/today — Top fixtures today\n"
                    f"/europeanleagues — Premier League, La Liga, Serie A...\n"
                    f"/asianleagues — CSL, J1, K League, Saudi Pro...\n"
                    f"/americanleagues — MLS, Liga MX, Brasileirão...\n"
                    f"/national — FIFA / national team fixtures\n"
                    f"/betslip — VIP 10-match betslip\n"
                    f"/upgrade — Go VIP\n\n"
                    f"FREE {FREE}/day · VIP {VIP}/day\n"
                    f"{BOT_LINK}"
                ))

            # ── /help ──
            elif low.startswith("/help"):
                send_message(chat_id, (
                    f"📖 BetMaster Pro Help\n\n"
                    f"• /today — Top fixtures globally\n"
                    f"• /europeanleagues — Europe fixtures\n"
                    f"• /asianleagues — Asia fixtures\n"
                    f"• /americanleagues — Americas fixtures\n"
                    f"• /national — FIFA national team fixtures\n"
                    f"• /betslip — VIP 10-match accumulator\n"
                    f"• /upgrade — VIP plans\n\n"
                    f"Or send: `Team A vs Team B` for instant analysis.\n\n"
                    f"FREE {FREE}/day · VIP {VIP}/day\n{BOT_LINK}"
                ))

            # ── Region commands ──
            elif low.startswith("/europeanleagues"):
                handle_region(chat_id, user_id, "european", user, db, cur)

            elif low.startswith("/asianleagues"):
                handle_region(chat_id, user_id, "asian", user, db, cur)

            elif low.startswith("/americanleagues"):
                handle_region(chat_id, user_id, "american", user, db, cur)

            elif low.startswith("/national"):
                handle_region(chat_id, user_id, "national", user, db, cur)

            # ── /today ──
            elif low.startswith("/today"):
                if user.daily_count >= cur:
                    send_message(chat_id,
                                 f"Limit {user.daily_count}/{cur}\n"
                                 f"{RENDER_URL}/subscribe?uid={user_id}")
                    return

                send_message(chat_id, "🔎 Scanning today's fixtures...")
                fixtures = fetch_real_fixtures(days_ahead=0, limit=10)

                if not fixtures:
                    send_message(chat_id, f"No fixtures found today.\n{BOT_LINK}")
                    return

                msg_txt = f"⚽ TOP FIXTURES — {fixtures[0].get('date', 'Today')}\n\n"
                for i, f in enumerate(fixtures, 1):
                    msg_txt += (f"{i}. {f['home']} vs {f['away']}\n"
                                f"   🏆 {f.get('league','')} · 🕐 {f.get('time','')} WAT\n\n")
                msg_txt += f"({user.daily_count}/{cur}) Tap for AI analysis\n{BOT_LINK}"

                keyboard = {"inline_keyboard": [[
                    {"text": "🧠 Predict Top 5", "callback_data": "predict_top5"},
                    {"text": "💰 VIP Betslip", "callback_data": "generate_betslip"},
                ]]}
                send_message(chat_id, msg_txt, reply_markup=keyboard)

            # ── /betslip ──
            elif low.startswith("/betslip"):
                if not user.is_vip:
                    send_message(chat_id,
                                 f"VIP only.\n{RENDER_URL}/subscribe?uid={user_id}")
                    return
                fixtures = fetch_real_fixtures(days_ahead=0, limit=20)
                slip = generate_betslip(fixtures)
                if not slip:
                    send_message(chat_id, "Not enough fixtures for a 10-match slip.")
                    return
                msg_txt = f"💰 VIP BETSLIP — {datetime.now().strftime('%d %b %Y')}\n\n"
                for i, p in enumerate(slip["picks"], 1):
                    msg_txt += f"{i}. {p['match']}\n   {p['market']}: {p['pick']} @ {p['odds']}\n\n"
                msg_txt += (f"TOTAL ODDS: {slip['total_odds']}\n"
                            f"N1000 → N{slip['winnings_1000']}\n"
                            f"N2000 → N{slip['winnings_2000']}\n{BOT_LINK}")
                send_message(chat_id, msg_txt)

            # ── /upgrade ──
            elif low.startswith("/upgrade"):
                send_message(chat_id, (
                    f"💎 VIP Benefits\n"
                    f"• 10 predictions/day (vs FREE 2)\n"
                    f"• 10-match VIP betslip\n"
                    f"• Value-bet alerts\n\n"
                    f"Plans:\n"
                    f"Weekly — N2000\n"
                    f"Monthly — N5000\n\n"
                    f"{RENDER_URL}/subscribe?uid={user_id}"
                ))

            # ── Team vs Team manual query ──
            elif " vs " in low and 5 < len(text) < 100:
                if user.daily_count >= cur:
                    send_message(chat_id,
                                 f"Limit {user.daily_count}/{cur}\n"
                                 f"{RENDER_URL}/subscribe?uid={user_id}")
                    return

                try:
                    parts = re.split(r"\s+vs\s+", text, flags=re.IGNORECASE)
                    home = parts[0].strip().title()
                    away = parts[1].strip().title()
                except Exception:
                    send_message(chat_id, "Format: `Team A vs Team B`")
                    return

                # Try to find in today's fixtures for accurate league/odds
                all_f = fetch_real_fixtures(days_ahead=0, limit=100)
                matched = next((f for f in all_f
                                if home.lower() in f["home"].lower()
                                and away.lower() in f["away"].lower()), None)

                if not matched:
                    # Try reversed
                    matched = next((f for f in all_f
                                    if away.lower() in f["home"].lower()
                                    and home.lower() in f["away"].lower()), None)

                data = matched or {
                    "home": home, "away": away, "league": "Custom",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "odds_h": 0, "odds_d": 0, "odds_a": 0,
                    "odds_over25": 0, "odds_btts": 0,
                    "source": "Model",
                }

                p = predict_match(data)
                user.daily_count += 1
                db.commit()

                msg_txt = (
                    f"⚽ {home} vs {away}\n"
                    f"🏆 {data.get('league','Custom')} | {data.get('date','')}\n\n"
                    f"📊 {p['form']}\n"
                    f"📈 {p['h2h']}\n"
                    f"📉 {p['standings']}\n\n"
                    f"✅ {p['verdict']} ({p['confidence']}%)\n"
                    f"📝 {p['explanation']}\n\n"
                    f"📋 ALL MARKETS:\n"
                )
                for m in p["all_markets"][:4]:
                    msg_txt += f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"

                if p.get("value_bets"):
                    msg_txt += "\n💎 VALUE BETS:\n"
                    for v in p["value_bets"][:2]:
                        msg_txt += f"• {v['market']} @ {v['odds']} (edge +{v['edge']}%)\n"

                msg_txt += (f"\n💰 N1000 → N{p['winnings_1000']}\n"
                            f"{p['disclaimer']}\n{BOT_LINK}")
                send_message(chat_id, msg_txt)

            else:
                send_message(chat_id,
                             f"Unknown command. Try /help\n{BOT_LINK}")

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
# CHANNEL SCHEDULER
# ──────────────────────────────────────────────
def channel_scheduler():
    posted_today = set()
    while True:
        try:
            now_utc = datetime.utcnow()
            now_wat = now_utc + timedelta(hours=1)
            hm = now_wat.strftime("%H:%M")
            today_str = now_wat.strftime("%Y-%m-%d")

            # 6 AM — morning picks
            if hm == "06:00" and f"{today_str}-6am" not in posted_today:
                try:
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=5)
                    if fixtures and CHANNEL_ID:
                        msg = f"☀️ Good Morning {today_str} — 6AM Picks\n\n"
                        for f in fixtures[:3]:
                            p = predict_match(f)
                            msg += (f"{f['home']} vs {f['away']}\n"
                                    f"{f.get('league','')} · {p['best_market']}: "
                                    f"{p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n\n")
                        msg += f"Full analysis on {BOT_HANDLE}\n{BOT_LINK}"
                        send_message(CHANNEL_ID, msg)
                except Exception as e:
                    print(f"6AM error: {e}")
                posted_today.add(f"{today_str}-6am")

            # 8 AM — top 5 picks
            if hm == "08:00" and f"{today_str}-8am" not in posted_today:
                try:
                    fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
                    if fixtures and CHANNEL_ID:
                        msg = f"🎯 TOP MATCHES — {today_str}\n\n"
                        for f in fixtures[:5]:
                            p = predict_match(f)
                            msg += (f"{f['home']} vs {f['away']}\n"
                                    f"{f.get('league','')} · {p['best_market']}: "
                                    f"{p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n\n")
                        msg += f"Want full analysis? {BOT_HANDLE}\n{BOT_LINK}"
                        send_message(CHANNEL_ID, msg)
                except Exception as e:
                    print(f"8AM error: {e}")
                posted_today.add(f"{today_str}-8am")

            # 9 PM — tomorrow preview
            if hm == "21:00" and f"{today_str}-9pm" not in posted_today:
                try:
                    fixtures = fetch_real_fixtures(days_ahead=1, limit=5)
                    if fixtures and CHANNEL_ID:
                        msg = f"🌙 TOMORROW'S TOP PICKS\n\n"
                        for f in fixtures[:3]:
                            p = predict_match(f)
                            msg += (f"{f['home']} vs {f['away']}\n"
                                    f"{f.get('league','')} · {p['best_market']}: "
                                    f"{p['best_pick']} @ {p['odds']}\n\n")
                        msg += f"More on {BOT_HANDLE}\n{BOT_LINK}"
                        send_message(CHANNEL_ID, msg)
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
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
                         timeout=8).json()
        ok = r.get("ok", False)
        username = r.get("result", {}).get("username", "UNKNOWN")
        wh = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo",
                          timeout=8).json()
    except Exception as e:
        ok = False
        username = str(e)
        wh = {}

    return {
        "status": "BetMaster Pro — Dixon-Coles AI · Global Coverage",
        "bot_ok": ok,
        "username": username,
        "webhook": wh.get("result", {}),
        "bot_link": BOT_LINK,
        "brain": f"{len(HISTORICAL_STATS)} teams · H2H {len(H2H_CACHE)}",
        "leagues": len(LEAGUE_AVG_GOALS),
        "has_keys": f"OddsAPI:{bool(THE_ODDS_API_KEY)}",
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
    url = (f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
           f"?url={RENDER_URL}/webhook&drop_pending_updates=true")
    r = requests.get(url, timeout=10).json()
    return r


@app.get("/debug-fixtures")
async def debug_fixtures(date: str = "", region: str = ""):
    try:
        target = (datetime.strptime(date, "%Y-%m-%d").date()
                  if date else (datetime.utcnow() + timedelta(hours=1)).date())

        if region:
            fixtures = fetch_by_region(target, region, limit=10)
        else:
            fixtures = fetch_today_fixtures(target, limit=10)

        return {
            "requested_date": target.strftime("%Y-%m-%d"),
            "region": region or "all",
            "found": len(fixtures),
            "fixtures": fixtures[:5],
            "brain_size": len(HISTORICAL_STATS),
            "h2h_pairs": len(H2H_CACHE),
            "leagues_loaded": len(LEAGUE_AVG_GOALS),
        }
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}


@app.get("/debug-predict")
async def debug_predict(home: str = "Arsenal", away: str = "Chelsea",
                        league: str = "E0"):
    try:
        result = dixon_coles_predict(home, away, league_code=league)
        return {
            "home": home, "away": away,
            "dixon_coles": result,
            "home_stats": HISTORICAL_STATS.get(home, {}),
            "away_stats": HISTORICAL_STATS.get(away, {}),
        }
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}


@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    return HTMLResponse(f"""
    <html><body style='background:#0f172a;color:white;text-align:center;
    padding:20px;font-family:sans-serif'>
    <div style='background:#1e293b;padding:20px;border-radius:15px;
    max-width:400px;margin:auto'>
    <h2>💎 BetMaster Pro VIP</h2>
    <p>10 predictions/day · 10-match betslip · Value-bet alerts<br>
    Dixon-Coles AI · Global coverage</p>
    <a href='/pay?plan=weekly&uid={uid}'
       style='display:block;padding:15px;background:#22c55e;color:white;
       border-radius:10px;text-decoration:none;margin:10px 0'>
       Weekly — N2000</a>
    <a href='/pay?plan=monthly&uid={uid}'
       style='display:block;padding:15px;background:#3b82f6;color:white;
       border-radius:10px;text-decoration:none'>
       Monthly — N5000</a>
    <p>{BOT_LINK}</p>
    </div></body></html>
    """)


@app.get("/pay")
async def pay(plan: str, uid: str):
    if not FLW_SECRET:
        return JSONResponse({"error": "No FLW secret key"}, status_code=500)
    amount = 2000 if plan == "weekly" else 5000
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"
    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer": {"email": f"{uid}@betmasterpro.com", "name": f"User {uid}"},
        "customizations": {"title": f"BetMaster Pro {plan.upper()}"},
    }
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        r = requests.post("https://api.flutterwave.com/v3/payments",
                          json=payload, headers=headers, timeout=15).json()
        if r.get("status") == "success":
            return RedirectResponse(r["data"]["link"])
        return JSONResponse(r, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/verify")
async def verify(tx_ref: str, uid: str, plan: str):
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}
    try:
        r = requests.get(
            f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}",
            headers=headers, timeout=15
        ).json()
        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            if data.get("status") in ["successful", "completed"]:
                activate_vip(uid, plan)
                return HTMLResponse(
                    f"<h1>✅ {plan.upper()} activated!</h1>"
                    f"<a href='{BOT_LINK}'>Return to bot</a>"
                )
        return HTMLResponse(f"<h1>Not confirmed: {tx_ref}</h1>")
    except Exception as e:
        return HTMLResponse(f"Error: {e}")


# ──────────────────────────────────────────────
# RUN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
