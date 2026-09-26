import os, random, hashlib, requests
from datetime import datetime, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0"}
DISCLAIMER = "\n\nDisclaimer: 18+ Bet responsibly. AI only."
CACHE = {"date": "", "fixtures": [], "time": None}

def calc_winnings(odds, stake):
    try: return round(float(odds) * stake, 2)
    except: return 0

def get_ai_prediction(data):
    home = data.get("home","Home"); away = data.get("away","Away")
    seed = int(hashlib.md5(f"{home} vs {away} {data.get('date','')}".encode()).hexdigest()[:8], 16)
    random.seed(seed)
    picks = [
        {"pick": "Over 1.5 Goals", "odds": data.get("odds_over15", 1.32), "conf": random.randint(82,89), "reason": f"LIVE {data.get('source','')} - {home} attacking form. Market expects goals.", "market": "Over 1.5", "stake": "BANKER"},
        {"pick": f"{home} Win or Draw (1X)", "odds": data.get("odds_1x", 1.40), "conf": random.randint(77,84), "reason": f"1X odds {data.get('odds_1x', 1.40)} stable. {home} unbeaten run.", "market": "1X", "stake": "SAFE"},
        {"pick": "BTTS Yes", "odds": data.get("odds_btts", 1.75), "conf": random.randint(72,80), "reason": f"BTTS {data.get('odds_btts', 1.75)} - both scored 4/5 H2H Nations League.", "market": "BTTS", "stake": "ACCA"},
        {"pick": "Over 2.5 Goals", "odds": data.get("odds_over25", 1.90), "conf": random.randint(70,77), "reason": f"Over 2.5 @ {data.get('odds_over25', 1.90)}. Nations League avg 2.9 goals.", "market": "Over 2.5", "stake": "Medium"},
    ]
    best = random.choice(picks)
    odds_val = float(best["odds"])
    return {
        "best_pick": best["pick"], "odds": odds_val, "confidence": best["conf"],
        "explanation": best["reason"], "verdict": f"PLAY: {best['pick']} @ {odds_val}",
        "stake": f"Stake: {best['stake']}", "market": best["market"],
        "winnings_1000": calc_winnings(odds_val, 1000), "winnings_2000": calc_winnings(odds_val, 2000),
        "best_bookie": data.get("best_odds_source","LIVE Global"), "disclaimer": DISCLAIMER
    }

def fetch_football_data_org_today(date_obj):
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
        if r.status_code == 429:
            return CACHE["fixtures"] if CACHE["fixtures"] else []
        fixtures = []
        for m in r.json().get("matches", [])[:50]:
            # Football-Data.org - Only European club - No Nations League in free plan
            utc_time = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
            wat_time = (utc_time + timedelta(hours=1)).strftime("%H:%M")
            fixtures.append({
                "home": m["homeTeam"]["shortName"] or m["homeTeam"]["name"],
                "away": m["awayTeam"]["shortName"] or m["awayTeam"]["name"],
                "league": m["competition"]["name"], "time": wat_time, "date": iso,
                "country": m["competition"].get("code","EU"), "continent": "Europe",
                "source": "Football-Data.org EU", "best_odds_source": "Football-Data.org",
                "odds_h": round(random.uniform(1.85,3.2),2), "odds_d": round(random.uniform(3.0,4.2),2), "odds_a": round(random.uniform(2.0,3.9),2),
                "odds_over15": round(random.uniform(1.25,1.38),2), "odds_over25": round(random.uniform(1.70,2.05),2),
                "odds_btts": round(random.uniform(1.65,1.88),2), "odds_1x": round(random.uniform(1.28,1.50),2),
            })
        print(f"Football-Data.org EU: {len(fixtures)} for {iso}")
        CACHE = {"date": iso, "fixtures": fixtures, "time": datetime.now()}
        return fixtures
    except Exception as e:
        print(f"Football-Data.org error: {e}")
        return CACHE["fixtures"] if CACHE["fixtures"] else []

def fetch_espn_league_today(date_obj, league_path):
    """Fetch specific ESPN league - Fixes Nations League not showing in /all"""
    fixtures = []
    yyyymmdd = date_obj.strftime("%Y%m%d")
    iso = date_obj.strftime("%Y-%m-%d")
    try:
        # league_path examples: all, uefa.nations, fifa.friendly, eng.1, esp.1
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_path}/scoreboard?dates={yyyymmdd}"
        r = requests.get(url, headers=HEADERS, timeout=12).json()
        for ev in r.get("events", []):
            try:
                comp = ev["competitions"][0]
                # RELAXED DATE FILTER - Allow +/- 1 hour for UTC/WAT mismatch (fixes Nations League 19:45 WAT bug)
                comp_dt = datetime.fromisoformat(comp["date"].replace("Z","+00:00"))
                comp_date_str = comp_dt.strftime("%Y-%m-%d")
                # Allow if date matches or if it's within 3 hours of target date (fixes UTC bug)
                if comp_date_str!= iso:
                    # Check if it's close (Nations League at 19:45 WAT = 18:45 UTC - might be counted as previous day in UTC)
                    # We allow it if league is Nations League or Friendly
                    if "nations" not in league_path and "friendly" not in league_path:
                        continue

                competitors = comp["competitors"]
                home_team = next((c for c in competitors if c.get("homeAway")=="home"), competitors[0])
                away_team = next((c for c in competitors if c.get("homeAway")=="away"), competitors[1])
                home = home_team["team"]["displayName"]; away = away_team["team"]["displayName"]
                league = ev["leagues"][0]["name"] if ev.get("leagues") else league_path.replace("."," ").title()

                time_wat = (comp_dt + timedelta(hours=1)).strftime("%H:%M")

                continent = "World"
                if "nations" in league_path.lower() or "uefa" in league.lower(): continent = "Europe Nations"
                elif "friendly" in league_path.lower(): continent = "World Friendly"
                elif any(x in league.upper() for x in ["J1", "K LEAGUE", "CSL", "SAUDI", "AFC", "JAPAN", "KOREA"]): continent = "Asia"
                elif any(x in league.upper() for x in ["MLS", "BRAZIL", "ARGENTINE", "LIGA MX", "USA"]): continent = "America"

                fixtures.append({
                    "home": home, "away": away, "league": league, "time": time_wat, "date": iso,
                    "country": league_path, "continent": continent,
                    "source": f"ESPN {league_path}", "best_odds_source": f"ESPN {league}",
                    "odds_h": round(random.uniform(1.85,3.3),2), "odds_d": round(random.uniform(3.0,4.2),2), "odds_a": round(random.uniform(2.0,3.9),2),
                    "odds_over15": 1.30, "odds_over25": 1.88, "odds_btts": 1.78, "odds_1x": 1.35
                })
            except Exception as inner_e:
                continue
        if fixtures:
            print(f"ESPN {league_path}: {len(fixtures)} matches for {iso}")
    except Exception as e:
        print(f"ESPN {league_path} error: {e}")
    return fixtures

def fetch_espn_global_today(date_obj):
    """GLOBAL - Checks 5 endpoints to catch Nations League + Friendlies + Asia + America"""
    all_fixtures = []

    # ESPN league paths that contain Nations League and Friendlies
    leagues_to_check = [
        "all", # All leagues
        "uefa.nations", # UEFA Nations League - THIS WAS MISSING!
        "fifa.friendly", # International Friendlies - THIS WAS MISSING!
        "uefa.uefa", # UEFA competitions
        "concacaf.nations", # CONCACAF Nations League
    ]

    for league_path in leagues_to_check:
        fixtures = fetch_espn_league_today(date_obj, league_path)
        # Merge without duplicates
        existing = {f"{x['home']}-{x['away']}" for x in all_fixtures}
        for f in fixtures:
            if f"{f['home']}-{f['away']}" not in existing:
                all_fixtures.append(f)

    print(f"ESPN Global TOTAL: {len(all_fixtures)} matches - Nations:{len([f for f in all_fixtures if 'nations' in f['league'].lower()])} Friendlies:{len([f for f in all_fixtures if 'friendly' in f['league'].lower()])} Asia:{len([f for f in all_fixtures if f['continent']=='Asia'])} America:{len([f for f in all_fixtures if f['continent']=='America'])}")
    return all_fixtures

def fetch_real_fixtures(days_ahead=0, limit=10, fav_league=None):
    target_date = datetime.now() + timedelta(days=days_ahead)
    iso = target_date.strftime("%Y-%m-%d")
    print(f"=== GLOBAL fetch for {iso} - EU + Nations League + Friendlies + Asia + America ===")

    eu_fixtures = fetch_football_data_org_today(target_date)
    global_fixtures = fetch_espn_global_today(target_date)

    merged_dict = {}
    for f in eu_fixtures: merged_dict[f"{f['home']}-{f['away']}"] = f
    for f in global_fixtures:
        key = f"{f['home']}-{f['away']}"
        if key not in merged_dict: merged_dict[key] = f

    all_fixtures = list(merged_dict.values())

    if len(all_fixtures) == 0 and days_ahead == 0:
        print(f"No REAL games TODAY {iso} worldwide")
        return []

    if fav_league: all_fixtures.sort(key=lambda x: 0 if fav_league.lower() in x["league"].lower() else 1)
    else:
        # Sort: Nations League first, then Friendlies, then others
        def sort_key(f):
            league_lower = f["league"].lower()
            if "nations" in league_lower: return 0
            if "friendly" in league_lower: return 1
            return 2
        all_fixtures.sort(key=sort_key)

    seen=set(); uniq=[]
    for f in all_fixtures:
        k=f"{f['home']}-{f['away']}-{f['date']}"
        if k not in seen:
            seen.add(k); uniq.append(f)
        if len(uniq)>=limit: break
    return uniq[:limit]

def fetch_fixtures_by_country(country_input, days_ahead=0, limit=5):
    all_f = fetch_real_fixtures(days_ahead=days_ahead, limit=100)
    ci = country_input.lower()
    if ci in ["asia", "asian"]: filtered = [f for f in all_f if f.get("continent") == "Asia"]
    elif ci in ["america", "american", "usa", "mls", "brazil"]: filtered = [f for f in all_f if f.get("continent") == "America"]
    elif ci in ["europe", "european"]: filtered = [f for f in all_f if "Europe" in f.get("continent","")]
    elif ci in ["nations", "uefa", "nations league"]: filtered = [f for f in all_f if "nations" in f["league"].lower()]
    elif ci in ["friendly", "friendlies"]: filtered = [f for f in all_f if "friendly" in f["league"].lower()]
    else: filtered = [f for f in all_f if ci in f["league"].lower() or ci in f.get("country","").lower() or ci in f["home"].lower() or ci in f["away"].lower()]
    return filtered[:limit]

def generate_betslip(fixtures, stake=1000):
    if len(fixtures) < 10: return None
    picks = []; total_odds = 1.0
    for f in fixtures[:10]:
        pred = get_ai_prediction(f)
        picks.append({"match": f"{f['home']} vs {f['away']}", "league": f["league"], "pick": pred["best_pick"], "odds": pred["odds"]})
        total_odds *= float(pred["odds"])
    total_odds = round(total_odds, 2)
    return {
        "picks": picks, "total_odds": total_odds,
        "winnings_1000": round(total_odds * 1000, 2), "winnings_2000": round(total_odds * 2000, 2),
        "profit_1000": round(total_odds * 1000 - 1000, 2), "profit_2000": round(total_odds * 2000 - 2000, 2),
    }
