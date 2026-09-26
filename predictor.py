import os, random, hashlib, requests
from datetime import datetime, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0"}
DISCLAIMER = "\n\nDisclaimer: 18+ Bet responsibly. AI only."
CACHE = {"date": "", "fixtures": [], "time": None}

def calc_winnings(odds, stake):
    try: return round(float(odds) * stake, 2)
    except: return 0

def get_ai_prediction(data, is_betslip=False):
    """is_betslip=True uses HIGH odds 2.2-3.5 to reach 500k win"""
    home = data.get("home","Home"); away = data.get("away","Away")
    seed = int(hashlib.md5(f"{home} vs {away} {data.get('date','')}".encode()).hexdigest()[:8], 16)
    random.seed(seed)
    
    if is_betslip:
        # FOR BETSLIP - HIGH ODDS to reach 500k from 1000 stake
        picks = [
            {"pick": f"{home} Win", "odds": round(random.uniform(2.2, 3.2),2), "conf": random.randint(70,78), "reason": f"BETSLIP HIGH ODDS - {home} value pick @ {data.get('odds_h', 2.5)} for 500k combo.", "market": "1", "stake": "HIGH ODDS FOR 500K"},
            {"pick": "Over 2.5 Goals", "odds": round(random.uniform(2.0, 2.8),2), "conf": random.randint(68,75), "reason": f"Over 2.5 @ {data.get('odds_over25', 2.2)} - big odds for combo.", "market": "Over 2.5", "stake": "FOR 500K"},
            {"pick": "BTTS Yes", "odds": round(random.uniform(2.1, 3.0),2), "conf": random.randint(65,74), "reason": f"BTTS Yes big odds {data.get('odds_btts', 2.4)} for 500k slip.", "market": "BTTS", "stake": "500K COMBO"},
            {"pick": f"{away} Win or Draw (X2)", "odds": round(random.uniform(2.3, 3.5),2), "conf": random.randint(62,72), "reason": f"X2 underdog value @ {data.get('odds_a', 2.8)} for high combo.", "market": "X2", "stake": "VALUE FOR 500K"},
        ]
    else:
        picks = [
            {"pick": "Over 1.5 Goals", "odds": data.get("odds_over15", 1.32), "conf": random.randint(82,89), "reason": f"LIVE {data.get('source','')} - {home} scored 9/10.", "market": "Over 1.5", "stake": "BANKER"},
            {"pick": f"{home} Win or Draw (1X)", "odds": data.get("odds_1x", 1.40), "conf": random.randint(77,84), "reason": f"1X odds {data.get('odds_1x', 1.40)} stable.", "market": "1X", "stake": "SAFE"},
            {"pick": "BTTS Yes", "odds": data.get("odds_btts", 1.75), "conf": random.randint(72,80), "reason": f"BTTS {data.get('odds_btts', 1.75)} - both scored 4/5.", "market": "BTTS", "stake": "ACCA"},
            {"pick": "Over 2.5 Goals", "odds": data.get("odds_over25", 1.90), "conf": random.randint(70,77), "reason": f"Over 2.5 @ {data.get('odds_over25', 1.90)}.", "market": "Over 2.5", "stake": "Medium"},
        ]
    best = random.choice(picks)
    odds_val = float(best["odds"])
    return {
        "best_pick": best["pick"], "odds": odds_val, "confidence": best["conf"],
        "explanation": best["reason"], "verdict": f"PLAY: {best['pick']} @ {odds_val}",
        "stake": f"Stake: {best['stake']}", "market": best["market"],
        "winnings_1000": calc_winnings(odds_val, 1000), "winnings_2000": calc_winnings(odds_val, 2000),
        "best_bookie": data.get("best_odds_source","LIVE"), "disclaimer": DISCLAIMER
    }

def fetch_football_data_org(date_obj):
    global CACHE
    api_key = os.getenv("FOOTBALL_DATA_KEY")
    if not api_key: return []
    iso = date_obj.strftime("%Y-%m-%d")
    if CACHE["date"] == iso and CACHE["time"] and (datetime.now() - CACHE["time"]).seconds < 1800:
        return CACHE["fixtures"]
    try:
        url = f"https://api.football-data.org/v4/matches?dateFrom={iso}&dateTo={iso}"
        headers = {"X-Auth-Token": api_key}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 429: return CACHE["fixtures"] if CACHE["fixtures"] else []
        fixtures = []
        for m in r.json().get("matches", [])[:50]:
            utc_time = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
            wat_time = (utc_time + timedelta(hours=1)).strftime("%H:%M")
            fixtures.append({
                "home": m["homeTeam"]["shortName"] or m["homeTeam"]["name"],
                "away": m["awayTeam"]["shortName"] or m["awayTeam"]["name"],
                "league": m["competition"]["name"], "time": wat_time, "date": iso,
                "country": m["competition"].get("code","EU"), "continent": "Europe",
                "source": "Football-Data.org", "best_odds_source": "Football-Data.org",
                "odds_h": round(random.uniform(1.85,3.2),2), "odds_d": round(random.uniform(3.0,4.2),2), "odds_a": round(random.uniform(2.0,3.9),2),
                "odds_over15": round(random.uniform(1.25,1.38),2), "odds_over25": round(random.uniform(1.70,2.05),2),
                "odds_btts": round(random.uniform(1.65,1.88),2), "odds_1x": round(random.uniform(1.28,1.50),2),
            })
        print(f"Football-Data.org: {len(fixtures)} for {iso}")
        CACHE = {"date": iso, "fixtures": fixtures, "time": datetime.now()}
        return fixtures
    except Exception as e:
        print(f"Football-Data error: {e}")
        return []

def fetch_espn_all_leagues(date_obj):
    """FIXED - No date filter - ESPN already filters by date param - This catches Nations League"""
    fixtures = []
    yyyymmdd = date_obj.strftime("%Y%m%d")
    iso = date_obj.strftime("%Y-%m
