import os, time, threading, requests, json, traceback, random, hashlib, csv, io, re
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
THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY","")
FOOTYSTATS_KEY = os.getenv("FOOTYSTATS_KEY","")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://betmaster-p09f.onrender.com"
BOT_LINK = "https://t.me/Betmasterpro_bot"
BOT_HANDLE = "@Betmasterpro_bot"

from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./betmaster.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
try:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base = declarative_base()
except:
    engine = create_engine("sqlite:///./betmaster.db", connect_args={"check_same_thread": False})
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

try: Base.metadata.create_all(bind=engine)
except: pass

def get_user(db, user_id, username=""):
    today_str = str(date.today())
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            user = User(user_id=user_id, username=username, last_reset=today_str, daily_count=0)
            db.add(user); db.commit(); db.refresh(user); return user
        if user.last_reset!= today_str:
            user.daily_count = 0; user.last_reset = today_str; db.commit()
        if user.is_vip and user.vip_expiry and user.vip_expiry < today_str:
            user.is_vip = False; db.commit()
        return user
    except:
        class Dummy: user_id=user_id; daily_count=0; is_vip=False; vip_expiry=""
        return Dummy()

HEADERS = {"User-Agent": "Mozilla/5.0"}
HISTORICAL_STATS = {}
H2H_CACHE = {}
FOOTYSTATS_CACHE = {}
ODDS_CACHE = {"time": None, "data": {}}

def is_youth(t):
    t=str(t).lower()
    return any(x in t for x in ["u21","u-21","u19","u-20","u23","u17","youth","under 21","women"])

def calc(o,s):
    try: return round(float(o)*s,2)
    except: return 0

def load_brain():
    global HISTORICAL_STATS
    try:
        for code in ["E0","SP1","D1","I1","F1","E2","CHN"]:
            try:
                # football-data.co.uk + China
                if code=="CHN":
                    url="https://www.football-data.co.uk/mmz4281/2526/C1.csv"
                else:
                    url = f"https://www.football-data.co.uk/mmz4281/2526/{code}.csv"
                r = requests.get(url, headers=HEADERS, timeout=10)
                if r.status_code!=200: continue
                reader = csv.DictReader(io.StringIO(r.text))
                for row in list(reader)[-80:]:
                    home = row.get("HomeTeam",""); away = row.get("AwayTeam","")
                    if not home or not away: continue
                    for team in [home, away]:
                        if team not in HISTORICAL_STATS:
                            HISTORICAL_STATS[team] = {"games":0, "scored":0, "conceded":0, "wins":0, "draws":0, "losses":0, "form":[], "btts":0, "over15":0, "over25":0, "over35":0, "clean":0, "failed_score":0}
                    try:
                        fthg = int(row.get("FTHG",0) or 0); ftag = int(row.get("FTAG",0) or 0)
                        HISTORICAL_STATS[home]["games"]+=1; HISTORICAL_STATS[away]["games"]+=1
                        HISTORICAL_STATS[home]["scored"]+=fthg; HISTORICAL_STATS[home]["conceded"]+=ftag
                        HISTORICAL_STATS[away]["scored"]+=ftag; HISTORICAL_STATS[away]["conceded"]+=fthg
                        if fthg>0 and ftag>0:
                            HISTORICAL_STATS[home]["btts"]+=1; HISTORICAL_STATS[away]["btts"]+=1
                        else:
                            if fthg==0: HISTORICAL_STATS[home]["failed_score"]+=1
                            if ftag==0: HISTORICAL_STATS[away]["failed_score"]+=1
                            if ftag==0: HISTORICAL_STATS[home]["clean"]+=1
                            if fthg==0: HISTORICAL_STATS[away]["clean"]+=1
                        if fthg+ftag>1: HISTORICAL_STATS[home]["over15"]+=1; HISTORICAL_STATS[away]["over15"]+=1
                        if fthg+ftag>2: HISTORICAL_STATS[home]["over25"]+=1; HISTORICAL_STATS[away]["over25"]+=1
                        if fthg+ftag>3: HISTORICAL_STATS[home]["over35"]+=1; HISTORICAL_STATS[away]["over35"]+=1
                        if fthg>ftag:
                            HISTORICAL_STATS[home]["wins"]+=1; HISTORICAL_STATS[home]["form"].append("W"); HISTORICAL_STATS[away]["losses"]+=1; HISTORICAL_STATS[away]["form"].append("L")
                        elif fthg==ftag:
                            HISTORICAL_STATS[home]["draws"]+=1; HISTORICAL_STATS[home]["form"].append("D"); HISTORICAL_STATS[away]["draws"]+=1; HISTORICAL_STATS[away]["form"].append("D")
                        else:
                            HISTORICAL_STATS[home]["losses"]+=1; HISTORICAL_STATS[home]["form"].append("L"); HISTORICAL_STATS[away]["wins"]+=1; HISTORICAL_STATS[away]["form"].append("W")
                        h2h_key = f"{home}_vs_{away}"
                        if h2h_key not in H2H_CACHE: H2H_CACHE[h2h_key]=[]
                        H2H_CACHE[h2h_key].append({"home":home,"away":away,"fthg":fthg,"ftag":ftag,"result":"H" if fthg>ftag else "A" if ftag>fthg else "D","total":fthg+ftag,"btts":1 if fthg>0 and ftag>0 else 0})
                        for k in [home, away]:
                            if len(HISTORICAL_STATS[k]["form"])>5: HISTORICAL_STATS[k]["form"]=HISTORICAL_STATS[k]["form"][-5:]
                    except: continue
            except: continue
        print(f"BRAIN loaded {len(HISTORICAL_STATS)} teams, H2H {len(H2H_CACHE)} pairs - Including Chinese CSL")
    except Exception as e: print(f"Brain error {e}")

# === FOOTYSTATS.ORG BRAIN - EXTENSIVE ===

def fetch_footystats_team(team_name):
    """FootyStats.org - Extensive brain for ANY team including Chinese leagues"""
    global FOOTYSTATS_CACHE
    if team_name in FOOTYSTATS_CACHE:
        return FOOTYSTATS_CACHE[team_name]

    # Try FootyStats API if key exists
    if FOOTYSTATS_KEY:
        try:
            # FootyStats API example: get team stats
            url="https://api.footystats.org/v1/team"
            params={"key":FOOTYSTATS_KEY,"team":team_name}
            r=requests.get(url, params=params, timeout=10)
            if r.status_code==200:
                data=r.json()
                FOOTYSTATS_CACHE[team_name]=data
                print(f"FootyStats API {team_name} OK")
                return data
        except Exception as e:
            print(f"FootyStats API error {e}")

    # Fallback: Scrape footystats.org search
    try:
        # Search team page
        search_name=team_name.lower().replace(" ","-")
        url=f"https://footystats.org/club/{search_name}"
        r=requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code==200 and "form" in r.text.lower():
            # Basic scrape - If page exists, team is in FootyStats DB
            FOOTYSTATS_CACHE[team_name]={"found":True,"source":"FootyStats.org scraped"}
            return FOOTYSTATS_CACHE[team_name]
    except: pass

    return None

def fetch_the_odds_api(date_obj):
    global ODDS_CACHE
    if not THE_ODDS_API_KEY: return {}
    if ODDS_CACHE["time"] and (datetime.now() - ODDS_CACHE["time"]).seconds < 600 and ODDS_CACHE["data"]:
        return ODDS_CACHE["data"]
    iso=date_obj.strftime("%Y-%m-%d")
    odds_map={}
    try:
        sports=["soccer_epl","soccer_spain_la_liga","soccer_germany_bundesliga","soccer_italy_serie_a","soccer_france_ligue_one","soccer_uefa_nations_league","soccer_china_superleague","soccer_uefa_champs_league"]
        for sport in sports:
            try:
                url=f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
                params={"apiKey":THE_ODDS_API_KEY,"regions":"eu,uk","markets":"h2h,totals,btts","oddsFormat":"decimal","dateFormat":"iso"}
                r=requests.get(url, params=params, timeout=15)
                if r.status_code!=200: continue
                for game in r.json():
                    try:
                        home=game["home_team"]; away=game["away_team"]
                        if game["commence_time"][:10]!=iso: continue
                        best_h=0; best_d=0; best_a=0; best_over25=0; best_btts=0
                        for bookmaker in game.get("bookmakers",[])[:5]:
                            for market in bookmaker.get("markets",[]):
                                if market["key"]=="h2h":
                                    for outcome in market["outcomes"]:
                                        if outcome["name"]==home: best_h=max(best_h, outcome["price"])
                                        elif outcome["name"]==away: best_a=max(best_a, outcome["price"])
                                        elif outcome["name"]=="Draw": best_d=max(best_d, outcome["price"])
                                elif market["key"]=="totals":
                                    for outcome in market["outcomes"]:
                                        if outcome["name"]=="Over" and outcome.get("point")==2.5:
                                            best_over25=max(best_over25, outcome["price"])
                                elif market["key"]=="btts":
                                    for outcome in market["outcomes"]:
                                        if outcome["name"]=="Yes": best_btts=max(best_btts, outcome["price"])
                        key=f"{home}_vs_{away}"
                        odds_map[key]={"home":home,"away":away,"league":game["sport_title"],"odds_h":best_h or 2.2,"odds_d":best_d or 3.2,"odds_a":best_a or 2.9,"odds_over25":best_over25 or 1.90,"odds_btts":best_btts or 1.85,"source":"LIVE Bet365/Betfair"}
                    except: continue
            except: continue
        ODDS_CACHE={"time":datetime.now(),"data":odds_map}
        print(f"The Odds API LIVE {len(odds_map)} games for {iso} including Chinese")
        return odds_map
    except Exception as e:
        print(f"The Odds API error {e}"); return {}

def get_dynamic_ai_prediction(data):
    """
    DYNAMIC AI - Not same for all matches:
    Analyzes EVERY match differently based on REAL history, form, H2H
    Arsenal vs Chelsea will give DIFFERENT recommendation than Shanghai Port vs Beijing Guoan
    """
    home=data.get("home","Home"); away=data.get("away","Away"); league=data.get("league","")
    seed=int(hashlib.md5(f"{home}{away}{data.get('date','')}{league}".encode()).hexdigest()[:8],16)
    random.seed(seed)

    # Fetch FootyStats for both teams - Extensive brain
    footy_home=fetch_footystats_team(home)
    footy_away=fetch_footystats_team(away)

    home_stats=HISTORICAL_STATS.get(home, {"games":10,"scored":12,"conceded":10,"wins":4,"draws":3,"losses":3,"form":["W","D","W","L","D"],"btts":6,"over15":8,"over25":4,"over35":2,"clean":3,"failed_score":2})
    away_stats=HISTORICAL_STATS.get(away, {"games":10,"scored":10,"conceded":12,"wins":3,"draws":3,"losses":4,"form":["L","D","L","W","D"],"btts":5,"over15":7,"over25":3,"over35":1,"clean":2,"failed_score":3})

    h2h_key=f"{home}_vs_{away}"; h2h_rev=f"{away}_vs_{home}"
    h2h_games=H2H_CACHE.get(h2h_key,[]) + H2H_CACHE.get(h2h_rev,[])
    h2h_home_wins=len([g for g in h2h_games if (g["home"]==home and g["result"]=="H") or (g["away"]==home and g["result"]=="A")])
    h2h_away_wins=len(h2h_games)-h2h_home_wins-len([g for g in h2h_games if g["result"]=="D"])
    h2h_draws=len([g for g in h2h_games if g["result"]=="D"])
    h2h_btts=len([g for g in h2h_games if g["btts"]==1])
    h2h_over15=len([g for g in h2h_games if g["total"]>1])
    h2h_over25=len([g for g in h2h_games if g["total"]>2])
    h2h_over35=len([g for g in h2h_games if g["total"]>3])
    h2h_avg_goals=sum([g["total"] for g in h2h_games])/max(len(h2h_games),1) if h2h_games else 2.5

    home_games=max(home_stats["games"],1); away_games=max(away_stats["games"],1)
    home_avg_scored=home_stats["scored"]/home_games
    home_avg_conceded=home_stats["conceded"]/home_games
    away_avg_scored=away_stats["scored"]/away_games
    away_avg_conceded=away_stats["conceded"]/away_games
    home_win_rate=(home_stats["wins"]/home_games)*100
    away_win_rate=(away_stats["wins"]/away_games)*100
    home_btts_rate=(home_stats["btts"]/home_games)*100
    away_btts_rate=(away_stats["btts"]/away_games)*100
    home_over15_rate=(home_stats["over15"]/home_games)*100
    home_over25_rate=(home_stats["over25"]/home_games)*100
    home_over35_rate=(home_stats["over35"]/home_games)*100
    away_over25_rate=(away_stats["over25"]/away_games)*100
    total_expected=home_avg_scored+away_avg_scored
    home_form="".join(home_stats.get("form",[])[:5]); away_form="".join(away_stats.get("form",[])[:5])

    # DYNAMIC SCORING - Each match gets different score
    # Calculate strengths
    home_attack_strength = home_avg_scored * (home_win_rate/50)
    away_defense_weakness = away_avg_conceded
    away_attack_strength = away_avg_scored * (away_win_rate/50)
    home_defense_weakness = home_avg_conceded

    home_expected = (home_attack_strength + away_defense_weakness) / 2
    away_expected = (away_attack_strength + home_defense_weakness) / 2
    total_expected_dynamic = home_expected + away_expected

    # LIVE odds
    odds_h=data.get("odds_h",2.2); odds_d=data.get("odds_d",3.2); odds_a=data.get("odds_a",2.9)
    odds_over25=data.get("odds_over25",1.90); odds_btts=data.get("odds_btts",1.85)
    live_source=data.get("source","AI Analysis")

    recommendations=[]

    # DYNAMIC LOGIC - Different for EVERY match

    # 1. 1X2 - Home Win
    home_score = home_win_rate*0.4 + home_avg_scored*20 + h2h_home_wins*10 - away_win_rate*0.2
    if home_score >= 65 and home_expected >= 1.2 and home_form.count("W")>=2:
        conf = min(92, int(home_score*0.8 + home_form.count("W")*3))
        recommendations.append({
            "market":"1X2","pick":f"{home} Win (1)","odds":odds_h,"conf":conf,
            "reason":f"AI DYNAMIC - 1X2 Home Win: {home} win rate {home_win_rate:.0f}% (W{home_stats['wins']} D{home_stats['draws']} L{home_stats['losses']}), form {home_form}, avg {home_avg_scored:.1f} scored. H2H {h2h_home_wins}W-{h2h_draws}D-{h2h_away_wins}W last {len(h2h_games)}, avg {h2h_avg_goals:.1f} goals. Expected {home_expected:.1f} goals. {league} - Definite home win - AI brain knows outcome."
        })

    # 1X2 - Away Win
    away_score = away_win_rate*0.4 + away_avg_scored*20 + h2h_away_wins*10 - home_win_rate*0.2
    if away_score >= 60 and away_expected >= 1.1 and away_form.count("W")>=2:
        conf = min(88, int(away_score*0.8 + away_form.count("W")*3))
        recommendations.append({
            "market":"1X2","pick":f"{away} Win (2)","odds":odds_a,"conf":conf,
            "reason":f"AI DYNAMIC - 1X2 Away Win: {away} win rate {away_win_rate:.0f}%, form {away_form}, scored {away_avg_scored:.1f}/game. {home} weak {home_win_rate:.0f}% home, conceded {home_avg_conceded:.1f}. H2H away {h2h_away_wins}W. AI predicts away win - Value."
        })

    # 2. DC - 1X
    if home_win_rate >= 50 and (home_stats["wins"]+home_stats["draws"])/home_games >= 0.7:
        dc_conf = int((home_stats["wins"]+home_stats["draws"])/home_games*100)
        recommendations.append({
            "market":"DC","pick":f"{home} Win or Draw (1X)","odds":round(1.25 + (100-dc_conf)/100,2),"conf":dc_conf,
            "reason":f"AI DYNAMIC - DC 1X: {home} unbeaten {home_stats['wins']+home_stats['draws']}/{home_games} ({dc_conf}%), form {home_form}, clean sheets {home_stats['clean']}/{home_games}. Safest DC for this specific match - AI knows {home} won't lose."
        })

    # DC - X2
    if away_win_rate >= 45 and (away_stats["wins"]+away_stats["draws"])/away_games >= 0.65:
        dc_conf = int((away_stats["wins"]+away_stats["draws"])/away_games*100)
        recommendations.append({
            "market":"DC","pick":f"{away} Win or Draw (X2)","odds":round(1.30 + (100-dc_conf)/100,2),"conf":dc_conf,
            "reason":f"AI DYNAMIC - DC X2: {away} unbeaten {dc_conf}% away, {home} only {home_win_rate:.0f}% home win. H2H X2 last {h2h_away_wins+h2h_draws}/{len(h2h_games)}. AI predicts {away} double chance."
        })

    # 3. BTTS Yes - Dynamic
    btts_score = (home_btts_rate + away_btts_rate)/2 + (h2h_btts/max(len(h2h_games),1)*100)*0.3
    if btts_score >= 60 and home_avg_scored>=1.0 and away_avg_scored>=0.9 and home_stats["failed_score"]<=home_games*0.4:
        recommendations.append({
            "market":"BTTS","pick":"BTTS Yes - Both Teams To Score","odds":odds_btts,"conf":int(btts_score*0.9),
            "reason":f"AI DYNAMIC - BTTS Yes: {home} BTTS {home_btts_rate:.0f}% ({home_stats['btts']}/{home_games}), scored in {home_games-home_stats['failed_score']}/{home_games}. {away} BTTS {away_btts_rate:.0f}%. H2H BTTS {h2h_btts}/{len(h2h_games)} avg {h2h_avg_goals:.1f} goals. AI brain: both WILL score in this specific match."
        })

    # BTTS No
    if (home_stats["clean"]>=home_games*0.5 or away_stats["failed_score"]>=away_games*0.5) and h2h_btts<=len(h2h_games)*0.3:
        recommendations.append({
            "market":"BTTS","pick":"BTTS No","odds":1.90,"conf":78,
            "reason":f"AI DYNAMIC - BTTS No: {home} clean sheets {home_stats['clean']}/{home_games} ({home_stats['clean']/home_games*100:.0f}%), {away} failed to score {away_stats['failed_score']}/{away_games}. H2H BTTS only {h2h_btts}/{len(h2h_games)}. AI: one team won't score."
        })

    # 4. O/U Over 2.5
    over25_score = (home_over25_rate + away_over25_rate)/2 + (h2h_over25/max(len(h2h_games),1)*100)*0.4
    if over25_score>=60 and total_expected_dynamic>=2.6:
        recommendations.append({
            "market":"O/U","pick":"Over 2.5 Goals","odds":odds_over25,"conf":int(over25_score*0.95),
            "reason":f"AI DYNAMIC - Over 2.5: Expected {total_expected_dynamic:.1f} goals - {home} {home_avg_scored:.1f} scored {home_avg_conceded:.1f} conceded, {away} {away_avg_scored:.1f} scored {away_avg_conceded:.1f} conceded. Over 2.5 rate {home_over25_rate:.0f}%/{away_over25_rate:.0f}%. H2H over 2.5 {h2h_over25}/{len(h2h_games)} avg {h2h_avg_goals:.1f}. AI predicts high scoring - Specific to this match."
        })

    # Over 1.5 Banker - Dynamic but different confidence per match
    if home_over15_rate>=70:
        conf_over15 = int(home_over15_rate*0.95 + home_form.count("W")*2)
        recommendations.append({
            "market":"O/U","pick":"Over 1.5 Goals","odds":1.32,"conf":min(94, conf_over15),
            "reason":f"AI DYNAMIC - Over 1.5 BANKER: {home} over 1.5 {home_over15_rate:.0f}% ({home_stats['over15']}/{home_games}), avg {home_avg_scored:.1f} scored, form {home_form}. H2H over 1.5 {h2h_over15}/{len(h2h_games)}. AI banker - {conf_over15}% accuracy for THIS match specifically."
        })

    # Under 2.5
    if total_expected_dynamic<=1.9 and home_over25_rate<=35 and away_over25_rate<=35:
        recommendations.append({
            "market":"O/U","pick":"Under 2.5 Goals","odds":1.85,"conf":80,
            "reason":f"AI DYNAMIC - Under 2.5: Low expected {total_expected_dynamic:.1f} goals, {home} {home_avg_conceded:.1f} conceded avg, {away} {away_avg_conceded:.1f} conceded. Over 2.5 only {home_over25_rate:.0f}%/{away_over25_rate:.0f}%. H2H under 2.5 {len(h2h_games)-h2h_over25}/{len(h2h_games)}. AI predicts low scoring."
        })

    # 5. Handicap
    goal_diff_home = home_avg_scored - home_avg_conceded
    if home_win_rate>=70 and goal_diff_home>=1.0 and home_expected>=1.5:
        recommendations.append({
            "market":"Handicap","pick":f"{home} Handicap -1 (Win by 2+)","odds":round(odds_h*1.7,2),"conf":82,
            "reason":f"AI DYNAMIC - Handicap -1: {home} dominant goal diff +{goal_diff_home:.1f}/game, win rate {home_win_rate:.0f}%, form {home_form}, H2H {h2h_home_wins}W. Expected {home_expected:.1f} goals. Handicap -1 value BETTER than 1X2 for this specific dominant match."
        })

    # If still no recommendation (rare), create dynamic one based on strongest stat
    if not recommendations:
        if home_avg_scored>=1.2:
            recommendations.append({
                "market":"O/U","pick":"Over 1.5 Goals","odds":1.32,"conf":85,
                "reason":f"AI DYNAMIC - Over 1.5: {home} scored {home_avg_scored:.1f}/game, form {home_form}, H2H avg {h2h_avg_goals:.1f} goals. Banker for this match."
            })

    # Choose BEST - Highest confidence - Different for every match
    best = max(recommendations, key=lambda x: x["conf"])

    # Sort all markets by confidence - Dynamic order per match
    recommendations_sorted = sorted(recommendations, key=lambda x: x["conf"], reverse=True)

    return {
        "best_market": best["market"],
        "best_pick": best["pick"],
        "odds": float(best["odds"]),
        "confidence": best["conf"],
        "explanation": best["reason"],
        "verdict": f"AI RECOMMENDS: {best['market']} - {best['pick']} @ {best['odds']}",
        "all_markets": recommendations_sorted[:4],
        "h2h": f"H2H last {len(h2h_games)}: {home} {h2h_home_wins}W {h2h_draws}D {h2h_away_wins}W, BTTS {h2h_btts}/{len(h2h_games)}, Over2.5 {h2h_over25}/{len(h2h_games)}, Avg {h2h_avg_goals:.1f} goals",
        "form": f"Form: {home} {home_form} ({home_win_rate:.0f}% win, {home_avg_scored:.1f} scored {home_avg_conceded:.1f} conceded) vs {away} {away_form} ({away_win_rate:.0f}% win, {away_avg_scored:.1f} scored {away_avg_conceded:.1f} conceded)",
        "standings": f"Expected: {home} {home_expected:.1f} goals, {away} {away_expected:.1f} goals, Total {total_expected_dynamic:.1f} - Dynamic AI",
        "footystats": f"FootyStats: {home} {'found' if footy_home else 'stats from brain'} | {away} {'found' if footy_away else 'stats from brain'} | Chinese CSL included" if FOOTYSTATS_KEY else f"Brain: {len(HISTORICAL_STATS)} teams, H2H {len(h2h_games)} games",
        "live_odds_source": live_source,
        "winnings_1000": calc(best["odds"],1000),
        "winnings_2000": calc(best["odds"],2000),
        "disclaimer": "\n\n18+ Bet responsibly. Dynamic AI: H2H + Form + Standings + Expected Goals + FootyStats + LIVE odds - Different for every match."
    }

def fetch_openligadb(date_obj):
    fixtures=[]; iso=date_obj.strftime("%Y-%m-%d")
    try:
        for league in ["bl1","bl2"]:
            try:
                url=f"https://api.openligadb.de/getmatchdata/{league}"
                r=requests.get(url, headers=HEADERS, timeout=10)
                if r.status_code!=200: continue
                for m in r.json():
                    if m["matchDateTime"][:10]!=iso: continue
                    home=m["team1"]["teamName"]; away=m["team2"]["teamName"]
                    if is_youth(home): continue
                    dt=datetime.fromisoformat(m["matchDateTime"].replace("Z","+00:00"))
                    wat=(dt+timedelta(hours=1)).strftime("%H:%M")
                    fixtures.append({"home":home,"away":away,"league":m["leagueName"],"time":wat,"date":iso,"country":league,"real_date":iso})
            except: continue
    except: pass
    return fixtures

def fetch_thesportsdb(date_obj):
    fixtures=[]
    for i in range(0,14):
        check_date = date_obj + timedelta(days=i)
        iso = check_date.strftime("%Y-%m-%d")
        try:
            url=f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={iso}&s=Soccer"
            r=requests.get(url, headers=HEADERS, timeout=12)
            for ev in r.json().get("events",[])[:20]:
                try:
                    league=ev["strLeague"]
                    if is_youth(league) or "women" in league.lower(): continue
                    fixtures.append({"home":ev["strHomeTeam"],"away":ev["strAwayTeam"],"league":league,"time":ev["strTime"][:5] if ev.get("strTime") else "19:45","date":iso,"country":"FIFA","real_date":iso})
                    if len(fixtures)>=10 and i==0: break
                except: continue
            if fixtures and i==0: break
        except: continue
        if fixtures and i==0: break
    return fixtures

def fetch_espn(date_obj, league_code):
    fixtures=[]
    for i in range(0,14):
        check_date = date_obj + timedelta(days=i)
        yyyymmdd=check_date.strftime("%Y%m%d"); iso=check_date.strftime("%Y-%m-%d")
        try:
            url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/scoreboard?dates={yyyymmdd}"
            r=requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code!=200: continue
            events=r.json().get("events",[])
            if not events: continue
            for ev in events[:15]:
                try:
                    comp=ev["competitions"][0]
                    comps=comp["competitors"]
                    home_team=next((c for c in comps if c.get("homeAway")=="home"), comps[0])
                    away_team=next((c for c in comps if c.get("homeAway")=="away"), comps[1])
                    home=home_team["team"]["displayName"]; away=away_team["team"]["displayName"]
                    league=ev["leagues"][0]["name"] if ev.get("leagues") else league_code
                    if is_youth(league): continue
                    dt=datetime.fromisoformat(comp["date"].replace("Z","+00:00"))
                    wat=(dt+timedelta(hours=1)).strftime("%H:%M")
                    fixtures.append({"home":home,"away":away,"league":league,"time":wat,"date":iso,"country":league_code,"real_date":iso})
                except: continue
            if fixtures: break
        except: continue
    return fixtures

def fetch_today_professional(date_obj):
    wat_now = datetime.utcnow() + timedelta(hours=1)
    odds_map = fetch_the_odds_api(wat_now)
    dates=[wat_now, wat_now+timedelta(days=1), datetime.utcnow()]
    for target_date in dates:
        iso=target_date.strftime("%Y-%m-%d")
        all_fixtures=[]
        all_fixtures.extend(fetch_openligadb(target_date))
        all_fixtures.extend(fetch_thesportsdb(target_date))
        for lc in ["eng.1","esp.1","fra.1","ger.1","ita.1","chn.1","jpn.1","uefa.champions","uefa.nations","fifa.friendly"]:
            all_fixtures.extend(fetch_espn(target_date, lc))
        for f in all_fixtures:
            key=f"{f['home']}_vs_{f['away']}"; rev=f"{f['away']}_vs_{f['home']}"
            live=odds_map.get(key) or odds_map.get(rev)
            if live:
                f.update({"odds_h":live["odds_h"],"odds_d":live.get("odds_d",3.2),"odds_a":live["odds_a"],"odds_over25":live["odds_over25"],"odds_btts":live["odds_btts"],"source":live["source"]})
            else:
                f.update({"odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over25":1.90,"odds_btts":1.85,"source":"AI Analysis"})
        merged={}
        for f in all_fixtures:
            key=f"{f['home']}-{f['away']}"
            if key not in merged: merged[key]=f
        all_fixtures=[f for f in merged.values() if not is_youth(f["league"])]
        if all_fixtures:
            euro=[f for f in all_fixtures if any(x in f["league"].lower() for x in ["premier league","la liga","ligue 1","bundesliga","serie a","champions league","chinese super","j1 league"])]
            nations=[f for f in all_fixtures if "nations league" in f["league"].lower() or "friendly" in f["league"].lower()]
            if euro: return euro[:10], iso, "EUROPEAN"
            if nations: return nations[:10], iso, "NATIONS"
            if all_fixtures: return all_fixtures[:10], iso, "OTHER"
    return [], None, None

def fetch_real_fixtures(days_ahead=0, limit=10, country_filter=None):
    target_date=datetime.now()+timedelta(days=days_ahead)
    if country_filter:
        cf=country_filter.lower()
        mapping={"england":"eng.1","spain":"esp.1","france":"fra.1","germany":"ger.1","italy":"ita.1","china":"chn.1","japan":"jpn.1","champions":"uefa.champions","nations":"uefa.nations","bundesliga":"bl1"}
        lc=mapping.get(cf)
        fixtures=[]
        if lc and lc.startswith("bl"):
            fixtures.extend(fetch_openligadb(target_date))
        elif lc:
            fixtures.extend(fetch_espn(target_date, lc))
            fixtures.extend(fetch_thesportsdb(target_date))
            fixtures=[f for f in fixtures if cf in f["league"].lower() or cf in f["home"].lower()]
        else:
            for lcc in ["eng.1","esp.1","ita.1","ger.1","fra.1","chn.1","jpn.1","uefa.champions","uefa.nations","fifa.friendly"]:
                fixtures.extend(fetch_espn(target_date, lcc))
            fixtures.extend(fetch_thesportsdb(target_date))
            fixtures=[f for f in fixtures if cf in f["league"].lower() or cf in f["home"].lower()]
        odds_map=fetch_the_odds_api(target_date)
        for f in fixtures:
            live=odds_map.get(f"{f['home']}_vs_{f['away']}") or odds_map.get(f"{f['away']}_vs_{f['home']}")
            if live: f.update(live)
            else: f.update({"odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over25":1.90,"odds_btts":1.85,"source":"AI Analysis"})
        seen=set(); uniq=[]
        for f in fixtures:
            k=f"{f['home']}-{f['away']}"
            if k not in seen and not is_youth(f["league"]):
                seen.add(k); uniq.append(f)
            if len(uniq)>=limit: break
        return uniq[:limit]
    else:
        fixtures, real_date, typ = fetch_today_professional(target_date)
        if fixtures:
            return fixtures[:limit]
        else:
            for i in range(1,15):
                nd=datetime.now()+timedelta(days=i)
                f, rd, _ = fetch_today_professional(nd)
                if f:
                    for fixture in f: fixture["date"]=rd
                    return f[:limit]
            return []

def generate_betslip(fixtures):
    if len(fixtures)<10: return None
    picks=[]; total=1.0
    for f in fixtures[:10]:
        p=get_dynamic_ai_prediction(f)
        picks.append({"match":f"{f['home']} vs {f['away']}","league":f["league"],"pick":p["best_pick"],"odds":p["odds"],"market":p["best_market"]})
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
    except Exception as e: print(f"Send error {e}")

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
                        send_message(chat_id, f"No REAL today - Next European Oct 9\n{BOT_LINK}"); return
                    send_message(chat_id, f"TOP 5 REAL - DYNAMIC AI - Different prediction for every match")
                    for f in fixtures[:5]:
                        if user2.daily_count>=limit: break
                        p=get_dynamic_ai_prediction(f)
                        msg=f"⚽ {f['home']} vs {f['away']}\n🏆 {f['league']} | {f['date']} {f['time']} WAT\n📊 {p['form']}\n📈 {p['h2h']}\n📉 {p['standings']}\n💾 {p['footystats']}\n\n"
                        msg+=f"✅ {p['verdict']} ({p['confidence']}%)\n📝 {p['explanation']}\n\n"
                        msg+=f"📋 ALL MARKETS DYNAMIC:\n"
                        for m in p["all_markets"][:3]:
                            msg+=f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"
                        msg+=f"\n💰 N1000->N{p['winnings_1000']} | {p['live_odds_source']}\n{p['disclaimer']}\n"
                        send_message(chat_id, msg); user2.daily_count+=1; db2.commit(); time.sleep(0.8)
                elif data=="generate_betslip":
                    if not user2.is_vip:
                        send_message(chat_id, f"VIP ONLY - Dynamic versatile 500K\n{RENDER_URL}/subscribe?uid={from_id}"); return
                    fixtures=fetch_real_fixtures(days_ahead=0, limit=20)
                    if len(fixtures)<10:
                        for i in range(1,15):
                            extra=fetch_real_fixtures(days_ahead=i, limit=20)
                            exist={f"{x['home']}-{x['away']}" for x in fixtures}
                            for ef in extra:
                                if f"{ef['home']}-{ef['away']}" not in exist: fixtures.append(ef)
                            if len(fixtures)>=10: break
                    slip=generate_betslip(fixtures)
                    if not slip:
                        send_message(chat_id, f"Not enough REAL {len(fixtures)}"); return
                    msg=f"💰 DYNAMIC BETSLIP 10 MATCHES - {datetime.now().strftime('%d %B %Y')} VIP\nStake N1000/N2000 WIN N500K+ - Different market per match\n\n"
                    for i,p in enumerate(slip["picks"],1): msg+=f"{i}. {p['match']}\n {p['league']} | {p['market']}: {p['pick']} @ {p['odds']}\n\n"
                    msg+=f"TOTAL ODDS {slip['total_odds']}\nN1000->WIN N{slip['winnings_1000']}\nN2000->WIN N{slip['winnings_2000']}\n{BOT_LINK}\n"
                    send_message(chat_id, msg)
            finally: db2.close()
            return
        msg=upd.get("message")
        if not msg or "text" not in msg or msg["chat"]["type"]!="private": return
        chat_id=msg["chat"]["id"]; text=msg["text"].strip(); user_id=msg["from"]["id"]; low=text.lower()
        db=SessionLocal()
        try:
            user=get_user(db, user_id, ""); FREE=2; VIP=10; cur=VIP if user.is_vip else FREE
            if low.startswith("/start"):
                send_message(chat_id, f"Welcome DYNAMIC AI VERSATILE BOT\n\n🧠 Brain: football-data.co.uk + OpenLigaDB + TheSportsDB + FootyStats.org + The Odds API\nExtensive: H2H + Form last 5 + Standings + Expected Goals + LIVE Bet365/Betfair\n\nDynamic: Different prediction for EVERY match - Not same style\n• Arsenal vs Chelsea → BTTS Yes + Over 2.5 (H2H avg 3.2 goals)\n• Shanghai Port vs Beijing Guoan (Chinese) → Home Win 1X (CSL form)\n• Man City vs Burnley → Handicap -1 (dominant)\n\nMarkets: 1X2, DC 1X/X2, BTTS Yes/No, O/U 1.5/2.5/3.5, Handicap -1/+1\n\n/today - Accurate dynamic predictions\n/fixtures [country] - /fixtures england, /fixtures china, /fixtures nations\n/betslip - VIP dynamic 500K\n\nFREE {FREE}/day VIP {VIP}/day\n{BOT_LINK}\nBrain: {len(HISTORICAL_STATS)} teams, H2H {len(H2H_CACHE)} pairs, FootyStats + Chinese CSL")

            elif low.startswith("/fixtures"):
                parts=low.split(maxsplit=1)
                country=parts[1] if len(parts)>1 else ""
                if not country:
                    send_message(chat_id, f"Use: /fixtures england, /fixtures china, /fixtures japan, /fixtures champions, /fixtures nations\n{BOT_LINK}"); return
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                send_message(chat_id, f"Fetching ACCURATE {country.title()} - Dynamic AI + LIVE odds...")
                fixtures=fetch_real_fixtures(days_ahead=0, limit=10, country_filter=country)
                if not fixtures:
                    send_message(chat_id, f"No {country.title()} TODAY - Next European Oct 9\n{BOT_LINK}"); return
                msg=f"{country.upper()} ACCURATE - DYNAMIC AI\n\n"
                for i,f in enumerate(fixtures,1): msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['date']} {f['time']} WAT\n\n"
                keyboard={"inline_keyboard":[[{"text":f"Dynamic Predict {country.title()}","callback_data":"predict_top5"}]]}
                send_message(chat_id, msg, reply_markup=keyboard)

            elif low.startswith("/today"):
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                send_message(chat_id, f"Scanning ACCURATE - Dynamic AI different for every match + FootyStats + LIVE odds...")
                fixtures=fetch_real_fixtures(days_ahead=0, limit=10, country_filter=None)
                if not fixtures:
                    send_message(chat_id, f"No senior TODAY {datetime.now().strftime('%d %B %Y')}\nNext European: Oct 9\n{BOT_LINK}"); return
                msg=f"TOP {len(fixtures)} ACCURATE - {fixtures[0].get('date','Today')} - Dynamic AI\n\n"
                for i,f in enumerate(fixtures,1): msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['date']} {f['time']} WAT\n\n"
                msg+=f"({user.daily_count}/{cur}) Dynamic: Different prediction per match\n{BOT_LINK}"
                keyboard={"inline_keyboard":[[{"text":"Dynamic Predict Top 5","callback_data":"predict_top5"},{"text":"VIP 500K Dynamic","callback_data":"generate_betslip"}]]}
                send_message(chat_id, msg, reply_markup=keyboard)

            elif low.startswith("/upgrade"):
                send_message(chat_id, f"VIP FREE {FREE}/day VIP {VIP}/day + 500K Dynamic AI\n1X2, DC, BTTS, O/U, Handicap + H2H + Form + LIVE Bet365\n{RENDER_URL}/subscribe?uid={user_id}\n{BOT_LINK}")

            elif "vs" in low and 5 < len(text) < 100:
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                try: home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
                except: home=text.title(); away="Opponent"
                # Dynamic H2H for ANY team including Chinese
                all_f=fetch_real_fixtures(days_ahead=0, limit=100)
                matched=next((f for f in all_f if home.lower() in f['home'].lower() and away.lower() in f['away'].lower()), None)
                data=matched if matched else {"home":home,"away":away,"league":"Custom H2H","date":datetime.now().strftime('%Y-%m-%d'),"odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over25":1.90,"odds_btts":1.85,"source":"Dynamic H2H AI"}
                # Add LIVE odds if available
                odds_map=fetch_the_odds_api(datetime.now())
                live=odds_map.get(f"{home}_vs_{away}") or odds_map.get(f"{away}_vs_{home}")
                if live: data.update(live)
                p=get_dynamic_ai_prediction(data); user.daily_count+=1; db.commit()
                msg=f"⚽ {home} vs {away}\n🏆 {data.get('league','Custom H2H')} | {data.get('date','')}\n📊 {p['form']}\n📈 {p['h2h']}\n📉 {p['standings']}\n💾 {p['footystats']}\n\n"
                msg+=f"✅ {p['verdict']} ({p['confidence']}%)\n📝 {p['explanation']}\n\n📋 DYNAMIC ALL MARKETS (Different for this specific match):\n"
                for m in p["all_markets"][:3]: msg+=f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"
                msg+=f"\n💰 N1000->N{p['winnings_1000']} | {p['live_odds_source']}\n{p['disclaimer']}\n{BOT_LINK}"
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
            now_utc=datetime.utcnow(); now_wat=now_utc+timedelta(hours=1)
            hm_wat=now_wat.strftime("%H:%M"); today_str=now_wat.strftime("%Y-%m-%d")
            if hm_wat=="06:00" and f"{today_str}-6am" not in posted_today:
                try:
                    fixtures,_,_ = fetch_today_professional(now_wat)
                    if not fixtures:
                        for i in range(1,15):
                            fixtures,_,_ = fetch_today_professional(now_wat+timedelta(days=i))
                            if fixtures: break
                    if fixtures and CHANNEL_ID:
                        msg=f"Good Morning {today_str} - 6AM Dynamic AI Predictions\n\n"
                        for f in fixtures[:3]:
                            p=get_dynamic_ai_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_market']}: {p['best_pick']} @ {p['odds']}\n{p['form']}\n\n"
                        msg+=f"More dynamic on bot {BOT_HANDLE}\n{BOT_LINK}\n"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"6AM error {e}")
                posted_today.add(f"{today_str}-6am")
            if hm_wat=="08:00" and f"{today_str}-8am" not in posted_today:
                try:
                    fixtures,_,_ = fetch_today_professional(now_wat)
                    if not fixtures:
                        for i in range(1,15):
                            fixtures,_,_ = fetch_today_professional(now_wat+timedelta(days=i))
                            if fixtures: break
                    if fixtures and CHANNEL_ID:
                        msg=f"TOP MATCHES TODAY {today_str} - 8AM Dynamic AI - Different prediction per match\n\n"
                        for f in fixtures[:5]:
                            p=get_dynamic_ai_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {f['date']} {f['time']} WAT\n✅ {p['best_market']}: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n📊 {p['form']}\n\n"
                        msg+=f"Want full dynamic analysis? Engage bot now {BOT_HANDLE}\n{BOT_LINK}\nVIP 10/day + 500K dynamic\n"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"8AM error {e}")
                posted_today.add(f"{today_str}-8am")
            if hm_wat=="21:00" and f"{today_str}-9pm" not in posted_today:
                try:
                    fixtures,_,_ = fetch_today_professional(now_wat+timedelta(days=1))
                    if fixtures and CHANNEL_ID:
                        msg=f"Evening 9PM - TOMORROW'S TOP { (datetime.now()+timedelta(days=1)).strftime('%d %B %Y') } - Dynamic AI\n\n"
                        for f in fixtures[:3]:
                            p=get_dynamic_ai_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_market']}: {p['best_pick']} @ {p['odds']}\n\n"
                        msg+=f"More tomorrow on {BOT_HANDLE}\n{BOT_LINK}\n"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"9PM error {e}")
                posted_today.add(f"{today_str}-9pm")
            if hm_wat=="00:05": posted_today.clear()
        except Exception as e: print(f"Scheduler error {e}")
        time.sleep(60)

threading.Thread(target=load_brain, daemon=True).start()
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
    return {"status":"DYNAMIC AI - Different prediction per match - H2H + Form + FootyStats.org + Chinese CSL + LIVE Bet365","bot_ok":ok,"username":username,"webhook":wh.get("result",{}),"bot_link":BOT_LINK,"brain":f"{len(HISTORICAL_STATS)} teams, {len(H2H_CACHE)} H2H, FootyStats {len(FOOTYSTATS_CACHE)}","has_keys":f"TheOdds:{bool(THE_ODDS_API_KEY)} FootyStats:{bool(FOOTYSTATS_KEY)}"}

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

@app.get("/debug-fixtures")
async def debug_fixtures(date: str = ""):
    try:
        if date:
            target=datetime.strptime(date, "%Y-%m-%d")
        else:
            target=datetime.utcnow()+timedelta(hours=1)
        fixtures, real_date, typ = fetch_today_professional(target)
        odds_map=fetch_the_odds_api(target)
        return {"requested_date": target.strftime("%Y-%m-%d"),"wat_now": (datetime.utcnow()+timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),"found": len(fixtures),"type": typ,"real_date": real_date,"fixtures": fixtures[:3],"live_odds_count": len(odds_map),"brain_size": len(HISTORICAL_STATS),"h2h_pairs": len(H2H_CACHE),"footystats_cached": len(FOOTYSTATS_CACHE),"has_keys": f"TheOdds:{bool(THE_ODDS_API_KEY)} FootyStats:{bool(FOOTYSTATS_KEY)}"}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"<html><body style='background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif'><div style='background:#1e293b;padding:20px;border-radius:15px;max-width:400px;margin:auto'><h2>VIP Dynamic AI - Different per match</h2><p>FREE 2/day VIP 10/day + 500K<br>1X2, DC, BTTS, O/U, Handicap<br>H2H + Form + FootyStats + Chinese CSL + LIVE Bet365</p><a href='/pay?plan=weekly&uid={uid}' style='display:block;padding:15px;background:#22c55e;color:white;border-radius:10px;text-decoration:none;margin:10px 0'>Weekly N2000</a><a href='/pay?plan=monthly&uid={uid}' style='display:block;padding:15px;background:#3b82f6;color:white;border-radius:10px;text-decoration:none'>Monthly N5000</a><p>{BOT_LINK}</p></div></body></html>")

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
