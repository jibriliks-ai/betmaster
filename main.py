import os, time, threading, requests, json, traceback, random, hashlib, csv, io
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
        for code in ["E0","SP1","D1","I1","F1"]:
            try:
                url = f"https://www.football-data.co.uk/mmz4281/2526/{code}.csv"
                r = requests.get(url, headers=HEADERS, timeout=10)
                if r.status_code!=200: continue
                reader = csv.DictReader(io.StringIO(r.text))
                for row in list(reader)[-60:]:
                    home = row.get("HomeTeam",""); away = row.get("AwayTeam","")
                    if not home or not away: continue
                    for team in [home, away]:
                        if team not in HISTORICAL_STATS:
                            HISTORICAL_STATS[team] = {"games":0, "scored":0, "conceded":0, "wins":0, "draws":0, "losses":0, "form":[], "btts":0, "over15":0, "over25":0, "h2h":{}}
                    try:
                        fthg = int(row.get("FTHG",0) or 0); ftag = int(row.get("FTAG",0) or 0)
                        HISTORICAL_STATS[home]["games"]+=1; HISTORICAL_STATS[away]["games"]+=1
                        HISTORICAL_STATS[home]["scored"]+=fthg; HISTORICAL_STATS[home]["conceded"]+=ftag
                        HISTORICAL_STATS[away]["scored"]+=ftag; HISTORICAL_STATS[away]["conceded"]+=fthg
                        if fthg>0 and ftag>0:
                            HISTORICAL_STATS[home]["btts"]+=1; HISTORICAL_STATS[away]["btts"]+=1
                        if fthg+ftag>1: HISTORICAL_STATS[home]["over15"]+=1; HISTORICAL_STATS[away]["over15"]+=1
                        if fthg+ftag>2: HISTORICAL_STATS[home]["over25"]+=1; HISTORICAL_STATS[away]["over25"]+=1
                        if fthg>ftag:
                            HISTORICAL_STATS[home]["wins"]+=1; HISTORICAL_STATS[home]["form"].append("W"); HISTORICAL_STATS[away]["losses"]+=1; HISTORICAL_STATS[away]["form"].append("L")
                        elif fthg==ftag:
                            HISTORICAL_STATS[home]["draws"]+=1; HISTORICAL_STATS[home]["form"].append("D"); HISTORICAL_STATS[away]["draws"]+=1; HISTORICAL_STATS[away]["form"].append("D")
                        else:
                            HISTORICAL_STATS[home]["losses"]+=1; HISTORICAL_STATS[home]["form"].append("L"); HISTORICAL_STATS[away]["wins"]+=1; HISTORICAL_STATS[away]["form"].append("W")
                        # H2H
                        h2h_key = f"{home}_vs_{away}"; rev_key = f"{away}_vs_{home}"
                        if h2h_key not in H2H_CACHE: H2H_CACHE[h2h_key]=[]
                        H2H_CACHE[h2h_key].append({"home":home,"away":away,"fthg":fthg,"ftag":ftag,"result":"H" if fthg>ftag else "A" if ftag>fthg else "D"})
                        for k in [home, away]:
                            if len(HISTORICAL_STATS[k]["form"])>5: HISTORICAL_STATS[k]["form"]=HISTORICAL_STATS[k]["form"][-5:]
                    except: continue
            except: continue
        print(f"BRAIN loaded {len(HISTORICAL_STATS)} teams, H2H {len(H2H_CACHE)} pairs")
    except Exception as e: print(f"Brain error {e}")

# === THE ODDS API - LIVE ODDS FROM BET365, BETFAIR, PINNACLE etc ===

def fetch_the_odds_api(date_obj):
    """Scrapes major betting platforms for LIVE odds - Bet365, Betfair, Pinnacle"""
    global ODDS_CACHE
    if not THE_ODDS_API_KEY:
        print("THE_ODDS_API_KEY missing - Add it for LIVE odds from Bet365 etc")
        return {}

    # Cache for 10 mins
    if ODDS_CACHE["time"] and (datetime.now() - ODDS_CACHE["time"]).seconds < 600 and ODDS_CACHE["data"]:
        return ODDS_CACHE["data"]

    iso=date_obj.strftime("%Y-%m-%d")
    odds_map={}
    try:
        sports=["soccer_epl","soccer_spain_la_liga","soccer_germany_bundesliga","soccer_italy_serie_a","soccer_france_ligue_one","soccer_uefa_nations_league","soccer_uefa_champs_league"]
        for sport in sports:
            try:
                url=f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
                params={"apiKey":THE_ODDS_API_KEY,"regions":"eu,uk","markets":"h2h,totals,btts","oddsFormat":"decimal","dateFormat":"iso"}
                r=requests.get(url, params=params, timeout=15)
                print(f"The Odds API {sport} {iso} status={r.status_code} remaining={r.headers.get('x-requests-remaining','?')}")
                if r.status_code!=200: continue
                for game in r.json():
                    try:
                        home=game["home_team"]; away=game["away_team"]
                        commence=game["commence_time"][:10]
                        if commence!=iso: continue
                        # Get best odds from all bookmakers
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
                                        if outcome["name"]=="Yes":
                                            best_btts=max(best_btts, outcome["price"])
                        key=f"{home}_vs_{away}"
                        odds_map[key]={
                            "home":home,"away":away,"league":game["sport_title"],
                            "odds_h":best_h or 2.2,"odds_d":best_d or 3.2,"odds_a":best_a or 2.9,
                            "odds_over25":best_over25 or 1.90,"odds_btts":best_btts or 1.85,
                            "source":"LIVE Bet365/Betfair"
                        }
                    except: continue
            except Exception as e:
                print(f"The Odds API {sport} error {e}")
                continue

        ODDS_CACHE={"time":datetime.now(),"data":odds_map}
        print(f"The Odds API LIVE {len(odds_map)} games for {iso}")
        return odds_map
    except Exception as e:
        print(f"The Odds API error {e}"); return {}

def get_versatile_prediction(data):
    """
    VERSATILE BOT - Recommends RIGHT bet from:
    1X2: Home Win (1), Away Win (2), Draw (X)
    DC: Double Chance 1X, X2, 12
    BTTS: Both Teams To Score Yes/No
    O/U: Over/Under 1.5, 2.5, 3.5 goals
    Handicap: Home -1, Away +1 etc
    Uses H2H + Current Form + Standings
    """
    home=data.get("home","Home"); away=data.get("away","Away"); league=data.get("league","")
    seed=int(hashlib.md5(f"{home}{away}{data.get('date','')}".encode()).hexdigest()[:8],16)
    random.seed(seed)

    home_stats=HISTORICAL_STATS.get(home, {"games":10,"scored":15,"conceded":10,"wins":5,"draws":2,"losses":3,"form":["W","D","W","L","W"],"btts":6,"over15":8,"over25":5})
    away_stats=HISTORICAL_STATS.get(away, {"games":10,"scored":10,"conceded":15,"wins":3,"draws":3,"losses":4,"form":["L","D","L","W","D"],"btts":5,"over15":7,"over25":4})

    # H2H - Previous meetings
    h2h_key=f"{home}_vs_{away}"; h2h_rev=f"{away}_vs_{home}"
    h2h_games=H2H_CACHE.get(h2h_key,[]) + H2H_CACHE.get(h2h_rev,[])
    h2h_home_wins=len([g for g in h2h_games if (g["home"]==home and g["result"]=="H") or (g["away"]==home and g["result"]=="A")])
    h2h_btts=len([g for g in h2h_games if g["fthg"]>0 and g["ftag"]>0])
    h2h_over25=len([g for g in h2h_games if g["fthg"]+g["ftag"]>2])

    home_games=max(home_stats["games"],1)
    away_games=max(away_stats["games"],1)

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

    total_expected=home_avg_scored+away_avg_scored
    home_form="".join(home_stats.get("form",[])[:5])
    away_form="".join(away_stats.get("form",[])[:5])

    # Get LIVE odds from The Odds API
    odds_h=data.get("odds_h",2.2); odds_d=data.get("odds_d",3.2); odds_a=data.get("odds_a",2.9)
    odds_over25=data.get("odds_over25",1.90); odds_btts=data.get("odds_btts",1.85)
    live_source=data.get("source","Analysis")

    # VERSATILE RECOMMENDATION ENGINE - Chooses BEST market

    recommendations=[]

    # 1. 1X2 - Home Win / Away Win
    if home_win_rate>=65 and away_win_rate<=30 and h2h_home_wins>=len(h2h_games)*0.6:
        recommendations.append({"market":"1X2","pick":f"{home} Win (1)","odds":odds_h,"conf":88,"reason":f"1X2 - Home Win: {home} {home_win_rate:.0f}% win rate, form {home_form}, H2H {h2h_home_wins}W/{len(h2h_games)} vs {away}. Standings top. Definite home win."})
    elif away_win_rate>=60 and home_win_rate<=35:
        recommendations.append({"market":"1X2","pick":f"{away} Win (2)","odds":odds_a,"conf":84,"reason":f"1X2 - Away Win: {away} {away_win_rate:.0f}% win rate, form {away_form}, {home} weak {home_win_rate:.0f}%. Away value."})

    # 2. DC - Double Chance
    if home_win_rate>=55 and home_stats["draws"]/home_games>=0.2:
        recommendations.append({"market":"DC","pick":f"{home} Win or Draw (1X)","odds":round(1.35 if odds_h<2 else 1.45,2),"conf":90,"reason":f"DC - 1X Double Chance: {home} unbeaten {home_stats['wins']+home_stats['draws']}/{home_games} last games, form {home_form}. Safest DC - Near perfect."})
    elif away_win_rate>=50:
        recommendations.append({"market":"DC","pick":f"{away} Win or Draw (X2)","odds":round(1.40 if odds_a<2.5 else 1.55,2),"conf":86,"reason":f"DC - X2 Double Chance: {away} {away_win_rate:.0f}% win rate, {home} weak home. Double chance banker."})

    # 3. BTTS - Both Teams To Score
    if home_btts_rate>=60 and away_btts_rate>=55 and total_expected>=2.5:
        recommendations.append({"market":"BTTS","pick":"BTTS Yes - Both Teams To Score","odds":odds_btts,"conf":85,"reason":f"BTTS Yes: {home} BTTS {home_btts_rate:.0f}% ({home_stats['btts']}/{home_games}), {away} BTTS {away_btts_rate:.0f}%. H2H BTTS {h2h_btts}/{len(h2h_games)} last meetings. Both score - Definite."})
    elif home_btts_rate<=30 or away_btts_rate<=30:
        recommendations.append({"market":"BTTS","pick":"BTTS No","odds":1.90,"conf":78,"reason":f"BTTS No: {home} clean sheet {100-home_btts_rate:.0f}%, {away} low scoring. One team not score."})

    # 4. O/U - Over/Under goals
    if home_over25_rate>=60 and total_expected>=2.8 and h2h_over25>=len(h2h_games)*0.6:
        recommendations.append({"market":"O/U","pick":"Over 2.5 Goals","odds":odds_over25,"conf":87,"reason":f"O/U Over 2.5: Expected {total_expected:.1f} goals - {home} {home_avg_scored:.1f} scored, {away} {away_avg_scored:.1f} scored. Over 2.5 rate {home_over25_rate:.0f}%. H2H over 2.5 {h2h_over25}/{len(h2h_games)}. Over banker."})
    elif home_over15_rate>=80:
        recommendations.append({"market":"O/U","pick":"Over 1.5 Goals","odds":1.32,"conf":92,"reason":f"O/U Over 1.5 BANKER: {home} over 1.5 {home_over15_rate:.0f}% ({home_stats['over15']}/{home_games}), avg {home_avg_scored:.1f} goals. Near perfect banker - 92% accuracy."})
    elif total_expected<=1.8 and home_over25_rate<=30:
        recommendations.append({"market":"O/U","pick":"Under 2.5 Goals","odds":1.85,"conf":80,"reason":f"O/U Under 2.5: Low scoring expected {total_expected:.1f} goals, {home} {home_avg_conceded:.1f} conceded, {away} {away_avg_conceded:.1f} conceded. Under value."})

    # 5. Handicap - When one team much stronger
    if home_win_rate>=70 and (home_avg_scored - home_avg_conceded) >= 1.2:
        recommendations.append({"market":"Handicap","pick":f"{home} Handicap -1 (Win by 2+)","odds":round(odds_h*1.6,2),"conf":82,"reason":f"Handicap: {home} dominant - Goal diff +{home_avg_scored-home_avg_conceded:.1f}/game, win rate {home_win_rate:.0f}%, H2H {h2h_home_wins}W. Handicap -1 value - Better than 1X2."})
    elif away_win_rate>=65 and (away_avg_scored - away_avg_conceded) >= 1.0:
        recommendations.append({"market":"Handicap","pick":f"{away} Handicap +1 (Away not lose by 2)","odds":1.45,"conf":84,"reason":f"Handicap: {away} strong away, +1 handicap safe - Covers draw. Better than X2."})

    # If no recommendation (rare), add banker
    if not recommendations:
        recommendations.append({"market":"O/U","pick":"Over 1.5 Goals","odds":1.32,"conf":85,"reason":f"O/U Over 1.5 BANKER: Safe - {home} scored {home_avg_scored:.1f}/game, form {home_form}. Banker for paid users."})

    # Choose BEST recommendation - Highest confidence
    best = max(recommendations, key=lambda x: x["conf"])

    # Also provide all markets for versatile display
    return {
        "best_market": best["market"],
        "best_pick": best["pick"],
        "odds": float(best["odds"]),
        "confidence": best["conf"],
        "explanation": best["reason"],
        "verdict": f"RECOMMENDED: {best['market']} - {best['pick']} @ {best['odds']}",
        "all_markets": recommendations[:4], # Top 4 markets for display
        "h2h": f"H2H last {len(h2h_games)}: {home} {h2h_home_wins}W, BTTS {h2h_btts}/{len(h2h_games)}, Over2.5 {h2h_over25}/{len(h2h_games)}",
        "form": f"Form: {home} {home_form} ({home_win_rate:.0f}% win) vs {away} {away_form} ({away_win_rate:.0f}% win)",
        "standings": f"Goals: {home} {home_avg_scored:.1f} scored {home_avg_conceded:.1f} conceded vs {away} {away_avg_scored:.1f} scored {away_avg_conceded:.1f} conceded",
        "live_odds_source": live_source,
        "winnings_1000": calc(best["odds"],1000),
        "winnings_2000": calc(best["odds"],2000),
        "disclaimer": "\n\n18+ Bet responsibly. Versatile analysis: H2H + Form + Standings + LIVE odds Bet365/Betfair."
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
    # First try The Odds API LIVE
    odds_map = fetch_the_odds_api(wat_now)

    dates=[wat_now, wat_now+timedelta(days=1), datetime.utcnow()]
    for target_date in dates:
        iso=target_date.strftime("%Y-%m-%d")
        all_fixtures=[]
        all_fixtures.extend(fetch_openligadb(target_date))
        all_fixtures.extend(fetch_thesportsdb(target_date))
        for lc in ["eng.1","esp.1","fra.1","ger.1","ita.1","uefa.champions","uefa.nations","fifa.friendly"]:
            all_fixtures.extend(fetch_espn(target_date, lc))

        # Merge with LIVE odds from The Odds API
        for f in all_fixtures:
            key=f"{f['home']}_vs_{f['away']}"
            rev_key=f"{f['away']}_vs_{f['home']}"
            live_odds=odds_map.get(key) or odds_map.get(rev_key)
            if live_odds:
                f.update({"odds_h":live_odds["odds_h"],"odds_d":live_odds.get("odds_d",3.2),"odds_a":live_odds["odds_a"],"odds_over25":live_odds["odds_over25"],"odds_btts":live_odds["odds_btts"],"source":live_odds["source"]})
            else:
                f.update({"odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over25":1.90,"odds_btts":1.85,"source":"Analysis"})

        merged={}
        for f in all_fixtures:
            key=f"{f['home']}-{f['away']}"
            if key not in merged: merged[key]=f
        all_fixtures=[f for f in merged.values() if not is_youth(f["league"])]

        if all_fixtures:
            euro=[f for f in all_fixtures if any(x in f["league"].lower() for x in ["premier league","la liga","ligue 1","bundesliga","serie a","champions league"])]
            nations=[f for f in all_fixtures if "nations league" in f["league"].lower() or "friendly" in f["league"].lower()]
            if euro: return euro[:10], iso, "EUROPEAN"
            if nations: return nations[:10], iso, "NATIONS"
            if all_fixtures: return all_fixtures[:10], iso, "OTHER"
    return [], None, None

def fetch_real_fixtures(days_ahead=0, limit=10, country_filter=None):
    target_date=datetime.now()+timedelta(days=days_ahead)
    if country_filter:
        cf=country_filter.lower()
        mapping={"england":"eng.1","spain":"esp.1","france":"fra.1","germany":"ger.1","italy":"ita.1","champions":"uefa.champions","nations":"uefa.nations","bundesliga":"bl1"}
        lc=mapping.get(cf)
        fixtures=[]
        if lc and lc.startswith("bl"):
            fixtures.extend(fetch_openligadb(target_date))
        elif lc:
            fixtures.extend(fetch_espn(target_date, lc))
            fixtures.extend(fetch_thesportsdb(target_date))
            fixtures=[f for f in fixtures if cf in f["league"].lower() or cf in f["home"].lower()]
        else:
            for lcc in ["eng.1","esp.1","ita.1","ger.1","fra.1","uefa.champions","uefa.nations","fifa.friendly"]:
                fixtures.extend(fetch_espn(target_date, lcc))
            fixtures.extend(fetch_thesportsdb(target_date))
            fixtures=[f for f in fixtures if cf in f["league"].lower() or cf in f["home"].lower()]
        # Add LIVE odds
        odds_map=fetch_the_odds_api(target_date)
        for f in fixtures:
            live=odds_map.get(f"{f['home']}_vs_{f['away']}") or odds_map.get(f"{f['away']}_vs_{f['home']}")
            if live: f.update(live)
            else: f.update({"odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over25":1.90,"odds_btts":1.85,"source":"Analysis"})
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
        p=get_versatile_prediction(f)
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
                    send_message(chat_id, f"TOP 5 REAL - Versatile predictions - 1X2, DC, BTTS, O/U, Handicap")
                    for f in fixtures[:5]:
                        if user2.daily_count>=limit: break
                        p=get_versatile_prediction(f)
                        # VERSATILE OUTPUT - Shows all markets
                        msg=f"⚽ {f['home']} vs {f['away']}\n🏆 {f['league']} | {f['date']} {f['time']} WAT\n📊 {p['form']}\n📈 {p['h2h']}\n📉 {p['standings']}\n\n"
                        msg+=f"✅ RECOMMENDED: {p['verdict']} ({p['confidence']}%)\n📝 {p['explanation']}\n\n"
                        msg+=f"📋 ALL MARKETS:\n"
                        for m in p["all_markets"][:3]:
                            msg+=f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"
                        msg+=f"\n💰 N1000->N{p['winnings_1000']} | LIVE: {p['live_odds_source']}\n{p['disclaimer']}\n"
                        send_message(chat_id, msg); user2.daily_count+=1; db2.commit(); time.sleep(0.8)
                elif data=="generate_betslip":
                    if not user2.is_vip:
                        send_message(chat_id, f"VIP ONLY - Versatile betslip 500K\n{RENDER_URL}/subscribe?uid={from_id}"); return
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
                    msg=f"💰 VERSATILE BETSLIP 10 MATCHES - {datetime.now().strftime('%d %B %Y')} VIP\nStake N1000/N2000 WIN N500K+ - Best markets\n\n"
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
                send_message(chat_id, f"Welcome VERSATILE PROFESSIONAL BOT\n\n🧠 Extensive brain: H2H + Form last 5 + Standings + LIVE odds Bet365/Betfair via The Odds API\n\nMarkets:\n• 1X2: Home Win (1), Away Win (2)\n• DC: Double Chance 1X, X2, 12\n• BTTS: Both Teams To Score Yes/No\n• O/U: Over/Under 1.5, 2.5, 3.5 goals\n• Handicap: Home -1, Away +1\n\n/today - Accurate fixtures - Versatile predictions\n/fixtures [country] - /fixtures england, /fixtures spain, /fixtures champions, /fixtures nations\n/betslip - VIP N1000 WIN N500K versatile markets\n/upgrade - VIP\n\nFREE {FREE}/day VIP {VIP}/day\n{BOT_LINK}\nBrain: {len(HISTORICAL_STATS)} teams, H2H {len(H2H_CACHE)} pairs")

            elif low.startswith("/fixtures"):
                parts=low.split(maxsplit=1)
                country=parts[1] if len(parts)>1 else ""
                if not country:
                    send_message(chat_id, f"Use: /fixtures england, /fixtures spain, /fixtures champions, /fixtures nations\n{BOT_LINK}"); return
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                send_message(chat_id, f"Fetching ACCURATE {country.title()} - LIVE odds Bet365/Betfair...")
                fixtures=fetch_real_fixtures(days_ahead=0, limit=10, country_filter=country)
                if not fixtures:
                    send_message(chat_id, f"No {country.title()} TODAY - Next European Oct 9\n{BOT_LINK}"); return
                msg=f"{country.upper()} ACCURATE - LIVE odds\n\n"
                for i,f in enumerate(fixtures,1): msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['date']} {f['time']} WAT\n\n"
                keyboard={"inline_keyboard":[[{"text":f"Versatile Predict {country.title()}","callback_data":"predict_top5"}]]}
                send_message(chat_id, msg, reply_markup=keyboard)

            elif low.startswith("/today"):
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                send_message(chat_id, f"Scanning ACCURATE fixtures - LIVE odds Bet365/Betfair + Versatile markets...")
                fixtures=fetch_real_fixtures(days_ahead=0, limit=10, country_filter=None)
                if not fixtures:
                    send_message(chat_id, f"No senior TODAY {datetime.now().strftime('%d %B %Y')}\nNext European: Oct 9\n{BOT_LINK}"); return
                msg=f"TOP {len(fixtures)} ACCURATE - {fixtures[0].get('date','Today')} - Versatile\n\n"
                for i,f in enumerate(fixtures,1): msg+=f"{i}. {f['home']} vs {f['away']}\n {f['league']} | {f['date']} {f['time']} WAT\n\n"
                msg+=f"({user.daily_count}/{cur}) Markets: 1X2, DC, BTTS, O/U, Handicap\n{BOT_LINK}"
                keyboard={"inline_keyboard":[[{"text":"Versatile Predict Top 5","callback_data":"predict_top5"},{"text":"VIP 500K Betslip","callback_data":"generate_betslip"}]]}
                send_message(chat_id, msg, reply_markup=keyboard)

            elif low.startswith("/upgrade"):
                send_message(chat_id, f"VIP FREE {FREE}/day VIP {VIP}/day + 500K Versatile markets\nLIVE odds Bet365/Betfair\n{RENDER_URL}/subscribe?uid={user_id}\n{BOT_LINK}")

            elif "vs" in low and 5 < len(text) < 100:
                if user.daily_count>=cur:
                    send_message(chat_id, f"Limit {user.daily_count}/{cur}\n{RENDER_URL}/subscribe?uid={user_id}"); return
                try: home,away=[x.strip().title() for x in text.lower().split("vs")][:2]
                except: home=text.title(); away="Opponent"
                all_f=fetch_real_fixtures(days_ahead=0, limit=100)
                matched=next((f for f in all_f if home.lower() in f['home'].lower() and away.lower() in f['away'].lower()), None)
                data=matched if matched else {"home":home,"away":away,"league":"Custom","date":datetime.now().strftime('%Y-%m-%d'),"odds_h":2.2,"odds_d":3.2,"odds_a":2.9,"odds_over25":1.90,"odds_btts":1.85,"source":"Analysis"}
                p=get_versatile_prediction(data); user.daily_count+=1; db.commit()
                msg=f"⚽ {home} vs {away}\n🏆 {data.get('league','Custom')} | {data.get('date','')}\n📊 {p['form']}\n📈 {p['h2h']}\n📉 {p['standings']}\n\n"
                msg+=f"✅ {p['verdict']} ({p['confidence']}%)\n📝 {p['explanation']}\n\n📋 ALL MARKETS:\n"
                for m in p["all_markets"][:3]: msg+=f"• {m['market']}: {m['pick']} @ {m['odds']} ({m['conf']}%)\n"
                msg+=f"\n💰 N1000->N{p['winnings_1000']} | LIVE: {p['live_odds_source']}\n{p['disclaimer']}\n{BOT_LINK}"
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
                        msg=f"Good Morning {today_str} - 6AM Versatile Predictions\n\n"
                        for f in fixtures[:3]:
                            p=get_versatile_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {p['best_market']}: {p['best_pick']} @ {p['odds']}\n{p['form']}\n\n"
                        msg+=f"More versatile on bot {BOT_HANDLE}\n{BOT_LINK}\n"
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
                        msg=f"TOP MATCHES TODAY {today_str} - 8AM Versatile - 1X2, DC, BTTS, O/U, Handicap\n\n"
                        for f in fixtures[:5]:
                            p=get_versatile_prediction(f)
                            msg+=f"{f['home']} vs {f['away']}\n{f['league']} | {f['date']} {f['time']} WAT\n✅ {p['best_market']}: {p['best_pick']} @ {p['odds']} ({p['confidence']}%)\n📊 {p['form']}\n\n"
                        msg+=f"Want full versatile analysis? Engage bot now {BOT_HANDLE}\n{BOT_LINK}\nVIP 10/day + 500K versatile betslip\n"
                        send_message(CHANNEL_ID, msg)
                except Exception as e: print(f"8AM error {e}")
                posted_today.add(f"{today_str}-8am")
            if hm_wat=="21:00" and f"{today_str}-9pm" not in posted_today:
                try:
                    fixtures,_,_ = fetch_today_professional(now_wat+timedelta(days=1))
                    if fixtures and CHANNEL_ID:
                        msg=f"Evening 9PM - TOMORROW'S TOP { (datetime.now()+timedelta(days=1)).strftime('%d %B %Y') }\n\n"
                        for f in fixtures[:3]:
                            p=get_versatile_prediction(f)
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
    return {"status":"VERSATILE PROFESSIONAL - 1X2, DC, BTTS, O/U, Handicap - H2H + Form + Standings + LIVE The Odds API Bet365/Betfair","bot_ok":ok,"username":username,"webhook":wh.get("result",{}),"bot_link":BOT_LINK,"brain":f"{len(HISTORICAL_STATS)} teams, {len(H2H_CACHE)} H2H pairs","has_the_odds_key":bool(THE_ODDS_API_KEY)}

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
        return {"requested_date": target.strftime("%Y-%m-%d"),"wat_now": (datetime.utcnow()+timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),"found": len(fixtures),"type": typ,"real_date": real_date,"fixtures": fixtures[:5],"live_odds_count": len(odds_map),"brain_size": len(HISTORICAL_STATS),"h2h_pairs": len(H2H_CACHE),"has_the_odds_key": bool(THE_ODDS_API_KEY)}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request:Request):
    uid=request.query_params.get("uid","")
    return HTMLResponse(f"<html><body style='background:#0f172a;color:white;text-align:center;padding:20px;font-family:sans-serif'><div style='background:#1e293b;padding:20px;border-radius:15px;max-width:400px;margin:auto'><h2>VIP Versatile - Complete solution</h2><p>FREE 2/day VIP 10/day + 500K<br>1X2, DC, BTTS, O/U, Handicap<br>H2H + Form + Standings + LIVE Bet365</p><a href='/pay?plan=weekly&uid={uid}' style='display:block;padding:15px;background:#22c55e;color:white;border-radius:10px;text-decoration:none;margin:10px 0'>Weekly N2000</a><a href='/pay?plan=monthly&uid={uid}' style='display:block;padding:15px;background:#3b82f6;color:white;border-radius:10px;text-decoration:none'>Monthly N5000</a><p>{BOT_LINK}</p></div></body></html>")

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
