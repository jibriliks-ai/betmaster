"""
main.py — BetMaster Pro
Global soccer prediction bot with Dixon-Coles modeling, value-bet detection,
multi-region coverage, and a professional payment flow.

Data sources: ESPN, TheSportsDB, OpenFootball, The Odds API.
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
# BRAIN
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
    avg_scored = stats["scored"] / games
    avg_conceded = stats["conceded"] / games

    attack = avg_scored / league_avg if league_avg > 0 else 1.0
    defense = avg_conceded / league_avg if league_avg > 0 else 1.0

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
    h = estimate_team_strengths(home_team, league_code)
    a = estimate_team_strengths(away_team, league_code)

    league_avg_per_team = LEAGUE_AVG_GOALS.get(league_code, 2.65) / 2.0

    home_xg = h["attack"] * a["defense"] * league_avg_per_team * math.exp(home_advantage)
    away_xg = a["attack"] * h["defense"] * league_avg_per_team

    home_xg = max(0.3, min(4.5, home_xg))
    away_xg = max(0.3, min(4.5, away_xg))

    probs = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson.pmf(i, home_xg) * poisson.pmf(j, away_xg)
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
            "top_scorelines": [], "btts": 50.0, "over15": 50.0,
            "over25": 50.0, "over35": 50.0, "top_cs": "1-0",
            "home_strength": h, "away_strength": a,
        }
    probs /= total

    home_win = float(np.tril(probs, -1).sum()) * 100
    draw = float(np.trace(probs)) * 100
    away_win = float(np.triu(probs, 1).sum()) * 100

    btts = float(probs[1:, 1:].sum()) * 100

    over25 = 0.0
    over15 = 0.0
    over35 = 0.0
    for i in range(max_goals):
        for j in range(max_goals):
            if i + j >= 3:
                over25 += probs[i][j]
            if i + j >= 2:
                over15 += probs[i][j]
            if i + j >= 4:
                over35 += probs[i][j]
    over25 *= 100
    over15 *= 100
    over35 *= 100

    scores = []
    for i in range(max_goals):
        for j in range(max_goals):
            scores.append((f"{i}-{j}", round(float(probs[i][j]) * 100, 2)))
    scores.sort(key=lambda x: x[1], reverse=True)
    top_scorelines = scores[:5]
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
                "model_prob": round(model_prob, 1),
                "implied": round(implied, 1),
                "edge": round(edge, 1),
                "odds": odd,
                "kelly": round(min(kelly, 15), 1),
            })

    value_bets.sort(key=lambda x: x["edge"], reverse=True)
    return value_bets


def predict_match(data):
    home = data.get("home", "Home")
    away = data.get("away", "Away")
    league = data.get("league", "")
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
        h2h_total = len(h2h_games)
        h2h_h_pct = h2h_home_wins / h2h_total * 100
        h2h_d_pct = h2h_draws / h2h_total * 100
        h2h_a_pct = h2h_away_wins / h2h_total * 100
        w = 0.20
        dc_h = dc_h * (1 - w) + h2h_h_pct * w
        dc_d = dc_d * (1 - w) + h2h_d_pct * w
        dc_a = dc_a * (1 - w) + h2h_a_pct * w

    tot = dc_h + dc_d + dc_a
    if tot > 0:
        dc_h, dc_d, dc_a = dc_h / tot * 100, dc_d / tot * 100, dc_a / tot * 100

    model_probs = {
        "home_win": round(dc_h, 1),
        "draw": round(dc_d, 1),
        "away_win": round(dc_a, 1),
    }

    odds = {
        "home": float(data.get("odds_h", 0) or 0),
        "draw": float(data.get("odds_d", 0) or 0),
        "away": float(data.get("odds_a", 0) or 0),
    }
    if odds["home"] <= 1.01:
        odds["home"] = round(100 / max(model_probs["home_win"], 5), 2)
    if odds["draw"] <= 1.01:
        odds["draw"] = round(100 / max(model_probs["draw"], 5), 2)
    if odds["away"] <= 1.01:
        odds["away"] = round(100 / max(model_probs["away_win"], 5), 2)

    markets = []

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

    dc_1x = model_probs["home_win"] + model_probs["draw"]
    dc_x2 = model_probs["draw"] + model_probs["away_win"]

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

    vb = find_value_bets(model_probs, odds)

    h_stats = HISTORICAL_STATS.get(home, {})
    a_stats = HISTORICAL_STATS.get(away, {})
    h_form = "".join(h_stats.get("form", [])[:5]) or "N/A"
    a_form = "".join(a_stats.get("form", [])[:5]) or "N/A"

    h2h_str = "No H2H data"
    if h2h_games:
        h2h_str = (f"H2H last {len(h2h_games)}: {home} {h2h_home_wins}W "
                   f"{h2h_draws}D {h2h_away_wins}W, BTTS {h2h_btts}/{len(h2h_games)}, "
                   f"Avg {h2h_avg_goals:.1f} goals")

    form_str = f"Form: {home} [{h_form}] | {away} [{a_form}]"

    standings_str = (
        f"Dixon-Coles xG: {home} {dc['home_xg']} — {away} {dc['away_xg']} | "
        f"1X2: {model_probs['home_win']}% / {model_probs['draw']}% / "
        f"{model_probs['away_win']}%"
    )

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


get_dynamic_ai_prediction = predict_match


# ──────────────────────────────────────────────
# ODDS — The Odds API
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
    target = (datetime.utcnow() + timedelta(hours=1) + timedelta(days=days_ahead)).date()

    if region:
        fixtures = fetch_by_region(target, region, limit=limit)
    else:
        fixtures = fetch_today_fixtures(target, limit=limit)

    if not fixtures and days_ahead == 0:
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
# BETSLIP
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
    --bg: #0a0e1a; --bg-2: #0f1526;
    --card: rgba(255,255,255,0.03); --card-hover: rgba(255,255,255,0.05);
    --border: rgba(255,255,255,0.08); --border-hover: rgba(255,255,255,0.16);
    --text: #e8ecf5; --text-dim: #8b94ab; --text-dimmer: #5a6378;
    --green: #22c55e; --green-glow: rgba(34,197,94,0.35);
    --blue: #3b82f6; --blue-glow: rgba(59,130,246,0.35);
    --gold: #f5b945;
    --radius: 16px; --radius-sm: 10px;
  }
  html, body { height: 100%; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
    -webkit-font-smoothing: antialiased; overflow-x: hidden;
    position: relative; min-height: 100vh;
  }
  body::before {
    content: ""; position: fixed; top: -20%; left: 50%; transform: translateX(-50%);
    width: 900px; height: 900px;
    background: radial-gradient(circle, rgba(34,197,94,0.10) 0%, transparent 60%);
    pointer-events: none; z-index: 0;
  }
  body::after {
    content: ""; position: fixed; bottom: -30%; right: -10%;
    width: 700px; height: 700px;
    background: radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 60%);
    pointer-events: none; z-index: 0;
  }
  .container { max-width: 960px; margin: 0 auto; padding: 0 20px; position: relative; z-index: 1; }
  nav { display: flex; align-items: center; justify-content: space-between; padding: 20px 0; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; letter-spacing: -0.01em; }
  .brand-logo { width: 34px; height: 34px; border-radius: 10px;
    background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 0 20px var(--green-glow); flex-shrink: 0; }
  .brand-logo svg { width: 18px; height: 18px; }
  .nav-cta { color: var(--text-dim); text-decoration: none; font-size: 13px; font-weight: 500;
    padding: 8px 14px; border: 1px solid var(--border); border-radius: 999px; transition: all 0.2s; }
  .nav-cta:hover { border-color: var(--border-hover); color: var(--text); }
  .hero { text-align: center; padding: 40px 0 32px; }
  .badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px;
    border-radius: 999px; background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.20);
    color: #4ade80; font-size: 12px; font-weight: 600; margin-bottom: 20px; letter-spacing: 0.02em; }
  .badge-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e;
    box-shadow: 0 0 8px #22c55e; animation: pulse 2s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  h1 { font-size: 40px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1;
    margin-bottom: 14px; background: linear-gradient(180deg, #ffffff 0%, #b8c1d6 100%);
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
  .hero p { color: var(--text-dim); font-size: 16px; max-width: 520px; margin: 0 auto 28px; }
  .trust-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-bottom: 8px; }
  .trust-pill { display: inline-flex; align-items: center; gap: 7px; padding: 8px 14px;
    background: var(--card); border: 1px solid var(--border); border-radius: 999px;
    font-size: 12.5px; color: var(--text-dim); font-weight: 500; }
  .trust-pill svg { width: 14px; height: 14px; color: var(--green); }
  .plans { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 40px 0 60px; }
  .plan { position: relative; background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 28px 24px; transition: all 0.25s ease; overflow: hidden; }
  .plan:hover { background: var(--card-hover); border-color: var(--border-hover); transform: translateY(-2px); }
  .plan.featured { border-color: rgba(59,130,246,0.4);
    background: linear-gradient(180deg, rgba(59,130,246,0.06) 0%, rgba(59,130,246,0.02) 100%);
    box-shadow: 0 20px 60px -20px var(--blue-glow); }
  .plan.featured:hover { border-color: rgba(59,130,246,0.6); }
  .ribbon { position: absolute; top: 14px; right: 14px; padding: 4px 10px;
    background: linear-gradient(135deg, #3b82f6, #2563eb); color: white;
    font-size: 10.5px; font-weight: 700; border-radius: 6px; letter-spacing: 0.05em;
    text-transform: uppercase; box-shadow: 0 4px 12px rgba(59,130,246,0.4); }
  .plan-name { font-size: 13px; font-weight: 600; color: var(--text-dim);
    letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 12px; }
  .plan-price { display: flex; align-items: baseline; gap: 6px; margin-bottom: 6px; }
  .plan-price .amount { font-size: 38px; font-weight: 700; letter-spacing: -0.03em; line-height: 1; }
  .plan-price .period { font-size: 15px; color: var(--text-dim); font-weight: 500; }
  .plan-sub { color: var(--text-dimmer); font-size: 13px; margin-bottom: 22px; }
  .plan-sub strong { color: #4ade80; font-weight: 600; }
  .plan-features { list-style: none; margin-bottom: 24px; }
  .plan-features li { display: flex; align-items: flex-start; gap: 10px; padding: 7px 0; font-size: 14px; color: var(--text); }
  .plan-features li svg { width: 16px; height: 16px; color: var(--green); flex-shrink: 0; margin-top: 3px; }
  .btn { display: flex; align-items: center; justify-content: center; gap: 8px;
    width: 100%; padding: 15px 20px; border-radius: var(--radius-sm); font-size: 15px;
    font-weight: 600; text-decoration: none; border: none; cursor: pointer;
    transition: all 0.2s; font-family: inherit; position: relative; overflow: hidden; }
  .btn-primary { background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
    color: white; box-shadow: 0 8px 24px -8px var(--green-glow); }
  .btn-primary:hover { box-shadow: 0 12px 32px -8px var(--green-glow); transform: translateY(-1px); }
  .btn-blue { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    color: white; box-shadow: 0 8px 24px -8px var(--blue-glow); }
  .btn-blue:hover { box-shadow: 0 12px 32px -8px var(--blue-glow); transform: translateY(-1px); }
  .btn:disabled { opacity: 0.7; cursor: not-allowed; transform: none !important; }
  .btn .spinner { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; display: none; }
  .btn.loading .spinner { display: block; }
  .btn.loading .btn-label { display: none; }
  @keyframes spin { to { transform: rotate(360deg); } }
  section { padding: 40px 0; }
  .section-title { text-align: center; font-size: 24px; font-weight: 700;
    letter-spacing: -0.02em; margin-bottom: 8px; }
  .section-sub { text-align: center; color: var(--text-dim); font-size: 14px; margin-bottom: 32px; }
  .features-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .feature-card { background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 22px 20px; transition: all 0.2s; }
  .feature-card:hover { background: var(--card-hover); border-color: var(--border-hover); }
  .feature-icon { width: 40px; height: 40px; border-radius: 10px;
    background: rgba(34,197,94,0.10); display: flex; align-items: center; justify-content: center;
    margin-bottom: 14px; }
  .feature-icon svg { width: 20px; height: 20px; color: var(--green); }
  .feature-card h3 { font-size: 15px; font-weight: 600; margin-bottom: 6px; letter-spacing: -0.01em; }
  .feature-card p { font-size: 13.5px; color: var(--text-dim); line-height: 1.55; }
  .testimonials { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .testimonial { background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 22px 20px; }
  .stars { color: var(--gold); font-size: 14px; margin-bottom: 10px; letter-spacing: 2px; }
  .testimonial p { font-size: 14px; color: var(--text); line-height: 1.6; margin-bottom: 14px; }
  .testimonial-author { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-dim); }
  .avatar { width: 32px; height: 32px; border-radius: 50%;
    background: linear-gradient(135deg, #3b82f6, #2563eb); display: flex; align-items: center;
    justify-content: center; color: white; font-weight: 600; font-size: 13px; }
  .faq-list { max-width: 680px; margin: 0 auto; }
  .faq-item { border-bottom: 1px solid var(--border); }
  .faq-item:first-child { border-top: 1px solid var(--border); }
  .faq-q { display: flex; justify-content: space-between; align-items: center;
    padding: 20px 4px; cursor: pointer; font-size: 15px; font-weight: 500; color: var(--text);
    user-select: none; transition: color 0.2s; }
  .faq-q:hover { color: #4ade80; }
  .faq-q svg { width: 18px; height: 18px; color: var(--text-dim); transition: transform 0.25s; flex-shrink: 0; }
  .faq-item.open .faq-q svg { transform: rotate(45deg); color: #4ade80; }
  .faq-a { max-height: 0; overflow: hidden;
    transition: max-height 0.3s ease, padding 0.3s ease; color: var(--text-dim);
    font-size: 14px; line-height: 1.65; padding: 0 4px; }
  .faq-item.open .faq-a { max-height: 300px; padding: 0 4px 20px; }
  footer { border-top: 1px solid var(--border); padding: 28px 0 40px;
    margin-top: 40px; text-align: center; font-size: 12.5px; color: var(--text-dimmer); }
  footer a { color: var(--text-dim); text-decoration: none; }
  footer a:hover { color: var(--text); }
  .footer-links { display: flex; justify-content: center; flex-wrap: wrap; gap: 20px; margin-bottom: 14px; }
  .disclaimer { max-width: 500px; margin: 14px auto 0; font-size: 11.5px; line-height: 1.55; color: var(--text-dimmer); }
  @media (max-width: 720px) {
    h1 { font-size: 30px; } .hero { padding: 24px 0 20px; }
    .plans { grid-template-columns: 1fr; gap: 16px; margin: 28px 0 40px; }
    .features-grid, .testimonials { grid-template-columns: 1fr; }
    .plan-price .amount { font-size: 32px; } section { padding: 28px 0; }
    .section-title { font-size: 20px; }
  }
  @media (max-width: 420px) {
    .container { padding: 0 16px; } h1 { font-size: 26px; } .brand { font-size: 15px; }
    .trust-pill { font-size: 11.5px; padding: 7px 11px; }
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
      Limited-Time Offer · Save 40%
    </div>
    <h1>Unlock AI-Powered<br>Football Predictions</h1>
    <p>Dixon-Coles statistical model · Value-bet detection · Global league coverage. Join thousands of smart bettors winning every week.</p>
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

  <section style="padding-top: 0;">
    <div class="plans">
      <div class="plan">
        <div class="plan-name">Weekly</div>
        <div class="plan-price">
          <span class="amount">₦2,000</span>
          <span class="period">/ week</span>
        </div>
        <div class="plan-sub">Perfect for <strong>trying us out</strong></div>
        <ul class="plan-features">
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>10 predictions per day</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Full Dixon-Coles analysis</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Value-bet alerts</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>All leagues: EU · Asia · Americas</li>
        </ul>
        <a href="/pay?plan=weekly&uid={{UID}}" class="btn btn-primary" onclick="return startPay(this)">
          <span class="spinner"></span>
          <span class="btn-label">Get Weekly Access</span>
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
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>10-match VIP accumulator slips</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Priority support &amp; updates</li>
          <li><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>Early access to new features</li>
        </ul>
        <a href="/pay?plan=monthly&uid={{UID}}" class="btn btn-blue" onclick="return startPay(this)">
          <span class="spinner"></span>
          <span class="btn-label">Get Monthly Access</span>
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
        <p>The industry-standard bivariate Poisson model used by professional bookmakers. Calculates exact scoreline probabilities.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
        </div>
        <h3>Real-Time Analysis</h3>
        <p>Live odds comparison across Bet365, Pinnacle and more. We find where the bookies got the price wrong.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        </div>
        <h3>Global Coverage</h3>
        <p>From the Premier League to the Chinese Super League, MLS and FIFA internationals. 200+ leagues, one bot.</p>
      </div>
    </div>
  </section>

  <section>
    <div class="section-title">Loved by Bettors</div>
    <div class="section-sub">Join our growing community of winners.</div>
    <div class="testimonials">
      <div class="testimonial">
        <div class="stars">★★★★★</div>
        <p>"Won 3 accumulators in my first week. The value-bet alerts are a game changer."</p>
        <div class="testimonial-author">
          <div class="avatar">E</div>
          <span>Emeka · Lagos</span>
        </div>
      </div>
      <div class="testimonial">
        <div class="stars">★★★★★</div>
        <p>"Finally a bot that actually explains its reasoning. The Dixon-Coles model is legit."</p>
        <div class="testimonial-author">
          <div class="avatar">T</div>
          <span>Tunde · Abuja</span>
        </div>
      </div>
      <div class="testimonial">
        <div class="stars">★★★★★</div>
        <p>"I stopped guessing. This pays for itself every single month."</p>
        <div class="testimonial-author">
          <div class="avatar">C</div>
          <span>Chidi · Port Harcourt</span>
        </div>
      </div>
    </div>
  </section>

  <section>
    <div class="section-title">Frequently Asked</div>
    <div class="section-sub">Quick answers to common questions.</div>
    <div class="faq-list">
      <div class="faq-item">
        <div class="faq-q">How do I receive predictions after paying?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Once payment is confirmed, your Telegram account is instantly upgraded. Return to the bot and use /today, /europeanleagues, /asianleagues, /americanleagues or /national to access your daily predictions.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">What payment methods do you accept?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">We accept all cards (Visa, Mastercard, Verve), bank transfers, USSD, and mobile money through Flutterwave — Nigeria's most trusted payment processor.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">Can I cancel anytime?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Yes. There are no contracts. Your VIP access runs until the expiry date and simply won't renew. You can restart whenever you like.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">Is my payment secure?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">Absolutely. All payments are processed by Flutterwave, PCI-DSS Level 1 certified. We never see or store your card details.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q">Do you guarantee winnings?<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
        <div class="faq-a">No legitimate service can guarantee winnings. Our model provides statistically-backed predictions with measurable edge over bookmaker odds — the same approach used by professional bettors. Always bet responsibly.</div>
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
    <div class="disclaimer">
      18+ only. Gambling involves risk. Bet only what you can afford to lose. If you need help, contact the National Problem Gambling Helpline.
    </div>
  </footer>
</div>
<script>
  document.querySelectorAll('.faq-q').forEach(function(q) {
    q.addEventListener('click', function() {
      var item = q.parentElement;
      item.classList.toggle('open');
    });
  });
  function startPay(btn) {
    btn.classList.add('loading');
    btn.disabled = true;
    return true;
  }
</script>
</body>
</html>"""


SUCCESS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0a0e1a">
<title>Payment Successful — BetMaster Pro</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Arial, sans-serif;
    background: #0a0e1a; color: #e8ecf5; min-height: 100vh; display: flex;
    align-items: center; justify-content: center; padding: 24px; position: relative; overflow: hidden; }
  body::before { content: ""; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: 700px; height: 700px; background: radial-gradient(circle, rgba(34,197,94,0.15) 0%, transparent 60%);
    pointer-events: none; }
  .card { position: relative; background: rgba(255,255,255,0.03); border: 1px solid rgba(34,197,94,0.25);
    border-radius: 20px; padding: 48px 36px; max-width: 440px; width: 100%; text-align: center;
    box-shadow: 0 30px 80px -30px rgba(34,197,94,0.4); }
  .check { width: 80px; height: 80px; border-radius: 50%;
    background: linear-gradient(135deg, #22c55e, #16a34a); display: flex; align-items: center;
    justify-content: center; margin: 0 auto 24px; box-shadow: 0 0 40px rgba(34,197,94,0.5);
    animation: pop 0.5s cubic-bezier(0.68,-0.55,0.27,1.55); }
  @keyframes pop { 0% { transform: scale(0); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
  .check svg { width: 40px; height: 40px; }
  h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 10px;
    background: linear-gradient(180deg, #fff 0%, #b8c1d6 100%); -webkit-background-clip: text;
    background-clip: text; -webkit-text-fill-color: transparent; }
  p { color: #8b94ab; font-size: 15px; line-height: 1.6; margin-bottom: 28px; }
  .plan-badge { display: inline-block; padding: 6px 14px; background: rgba(34,197,94,0.1);
    border: 1px solid rgba(34,197,94,0.25); border-radius: 999px; color: #4ade80;
    font-size: 13px; font-weight: 600; margin-bottom: 20px; letter-spacing: 0.05em; text-transform: uppercase; }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    padding: 15px 28px; background: linear-gradient(135deg, #22c55e, #16a34a); color: white;
    text-decoration: none; border-radius: 12px; font-weight: 600; font-size: 15px;
    box-shadow: 0 10px 30px -10px rgba(34,197,94,0.5); transition: all 0.2s; width: 100%; }
  .btn:hover { transform: translateY(-1px); box-shadow: 0 15px 40px -10px rgba(34,197,94,0.6); }
  .btn svg { width: 18px; height: 18px; }
</style>
</head>
<body>
<div class="card">
  <div class="check">
    <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  </div>
  <div class="plan-badge">{{PLAN}} Activated</div>
  <h1>Welcome to VIP!</h1>
  <p>Your payment was confirmed and your account has been upgraded. Return to the bot to start receiving premium AI predictions.</p>
  <a href="{{BOT_LINK}}" class="btn">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>
    </svg>
    Open Telegram Bot
  </a>
</div>
</body>
</html>"""


FAILED_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0a0e1a">
<title>Payment Issue — BetMaster Pro</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Arial, sans-serif;
    background: #0a0e1a; color: #e8ecf5; min-height: 100vh; display: flex;
    align-items: center; justify-content: center; padding: 24px; position: relative; overflow: hidden; }
  body::before { content: ""; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: 700px; height: 700px; background: radial-gradient(circle, rgba(239,68,68,0.12) 0%, transparent 60%);
    pointer-events: none; }
  .card { position: relative; background: rgba(255,255,255,0.03); border: 1px solid rgba(239,68,68,0.25);
    border-radius: 20px; padding: 48px 36px; max-width: 440px; width: 100%; text-align: center;
    box-shadow: 0 30px 80px -30px rgba(239,68,68,0.35); }
  .icon { width: 80px; height: 80px; border-radius: 50%;
    background: linear-gradient(135deg, #ef4444, #dc2626); display: flex; align-items: center;
    justify-content: center; margin: 0 auto 24px; box-shadow: 0 0 40px rgba(239,68,68,0.4); }
  .icon svg { width: 40px; height: 40px; }
  h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 10px; color: #fca5a5; }
  p { color: #8b94ab; font-size: 15px; line-height: 1.6; margin-bottom: 12px; }
  .reason { background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px; padding: 14px 16px; font-size: 13px; color: #cbd5e1;
    font-family: ui-monospace, "SF Mono", Menlo, monospace; margin: 20px 0 24px;
    word-break: break-word; text-align: left; }
  .actions { display: flex; flex-direction: column; gap: 10px; }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    padding: 14px 24px; border-radius: 12px; font-weight: 600; font-size: 14.5px;
    text-decoration: none; transition: all 0.2s; width: 100%; }
  .btn-primary { background: linear-gradient(135deg, #22c55e, #16a34a); color: white;
    box-shadow: 0 10px 30px -10px rgba(34,197,94,0.5); }
  .btn-primary:hover { transform: translateY(-1px); }
  .btn-secondary { background: transparent; color: #8b94ab; border: 1px solid rgba(255,255,255,0.1); }
  .btn-secondary:hover { color: #e8ecf5; border-color: rgba(255,255,255,0.2); }
</style>
</head>
<body>
<div class="card">
  <div class="icon">
    <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  </div>
  <h1>Payment Not Confirmed</h1>
  <p>We couldn't verify your transaction. If you were charged, please contact support with the reference below.</p>
  <div class="reason">{{REASON}}</div>
  <div class="actions">
    <a href="/subscribe?uid={{UID}}" class="btn btn-primary">Try Again</a>
    <a href="{{BOT_LINK}}" class="btn btn-secondary">Contact Support</a>
  </div>
</div>
</body>
</html>"""


def render_payment_page(uid: str) -> str:
    from datetime import datetime as _dt
    return (PAYMENT_TEMPLATE
            .replace("{{UID}}", str(uid))
            .replace("{{BOT_LINK}}", BOT_LINK)
            .replace("{{BOT_HANDLE}}", BOT_HANDLE)
            .replace("{{YEAR}}", str(_dt.now().year)))


def render_success_page(plan: str) -> str:
    return (SUCCESS_TEMPLATE
            .replace("{{PLAN}}", plan.upper())
            .replace("{{BOT_LINK}}", BOT_LINK))


def render_failed_page(reason: str, uid: str = "") -> str:
    import html
    return (FAILED_TEMPLATE
            .replace("{{REASON}}", html.escape(str(reason))[:500])
            .replace("{{UID}}", str(uid))
            .replace("{{BOT_LINK}}", BOT_LINK))


# ──────────────────────────────────────────────
# TELEGRAM APP
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
                     f"Daily limit reached ({user.daily_count}/{limit}).\n"
                     f"Upgrade: {RENDER_URL}/subscribe?uid={user_id}")
        return

    send_message(chat_id, f"🔎 Scanning {pretty} fixtures for today...")

    fixtures = fetch_real_fixtures(days_ahead=0, limit=15, region=region)

    if not fixtures:
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


def send_full_prediction(chat_id, fixture):
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
                        send_full_prediction(chat_id, f)
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
                        send_full_prediction(chat_id, f)
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
                    f"Or send: Team A vs Team B for instant analysis.\n\n"
                    f"FREE {FREE}/day · VIP {VIP}/day\n{BOT_LINK}"
                ))

            elif low.startswith("/europeanleagues"):
                handle_region(chat_id, user_id, "european", user, db, cur)

            elif low.startswith("/asianleagues"):
                handle_region(chat_id, user_id, "asian", user, db, cur)

            elif low.startswith("/americanleagues"):
                handle_region(chat_id, user_id, "american", user, db, cur)

            elif low.startswith("/national"):
                handle_region(chat_id, user_id, "national", user, db, cur)

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


# ──────────────────────────────────────────────
# PAYMENT ROUTES
# ──────────────────────────────────────────────
@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    return HTMLResponse(render_payment_page(uid))


@app.get("/pay")
async def pay(plan: str, uid: str):
    if not FLW_SECRET:
        return HTMLResponse(
            render_failed_page("Payment system is not configured. Please contact support.", uid),
            status_code=500,
        )

    if plan not in ("weekly", "monthly"):
        return HTMLResponse(
            render_failed_page(f"Invalid plan: {plan}", uid),
            status_code=400,
        )

    amount = 2000 if plan == "weekly" else 5000
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"

    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": f"{RENDER_URL}/verify?tx_ref={tx_ref}&uid={uid}&plan={plan}",
        "customer": {
            "email": f"{uid}@betmasterpro.com",
            "name": f"User {uid}",
        },
        "customizations": {
            "title": f"BetMaster Pro — {plan.title()}",
            "description": f"VIP access for {plan} plan",
        },
        "payment_options": "card,banktransfer,ussd,mobilemoney",
    }
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}

    try:
        r = requests.post(
            "https://api.flutterwave.com/v3/payments",
            json=payload, headers=headers, timeout=20,
        ).json()

        if r.get("status") == "success" and r.get("data", {}).get("link"):
            return RedirectResponse(r["data"]["link"])

        err = r.get("message", "Could not create payment session")
        return HTMLResponse(render_failed_page(err, uid), status_code=400)

    except requests.exceptions.Timeout:
        return HTMLResponse(
            render_failed_page("Payment gateway timed out. Please try again.", uid),
            status_code=504,
        )
    except Exception as e:
        return HTMLResponse(
            render_failed_page(f"Unexpected error: {e}", uid),
            status_code=500,
        )


@app.get("/verify")
async def verify(tx_ref: str, uid: str, plan: str):
    headers = {"Authorization": f"Bearer {FLW_SECRET}"}

    try:
        r = requests.get(
            f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}",
            headers=headers, timeout=20,
        ).json()

        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]

            if data.get("status") in ("successful", "completed"):
                activate_vip(uid, plan)
                return HTMLResponse(render_success_page(plan))

            return HTMLResponse(
                render_failed_page(f"Transaction status: {data.get('status', 'unknown')}", uid),
                status_code=400,
            )

        return HTMLResponse(
            render_failed_page("Transaction not found or already processed.", uid),
            status_code=404,
        )

    except requests.exceptions.Timeout:
        return HTMLResponse(
            render_failed_page("Verification timed out. Please contact support with your reference.", uid),
            status_code=504,
        )
    except Exception as e:
        return HTMLResponse(
            render_failed_page(f"Verification error: {e}", uid),
            status_code=500,
        )


# ──────────────────────────────────────────────
# RUN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
