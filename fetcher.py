"""
fetcher.py — Global soccer fixture fetcher using APIs that work worldwide.
No API-Football dependency. Sources: ESPN hidden API, TheSportsDB, OpenFootball JSON.
"""

import os
import requests
import json
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
THE_SPORTSDB_KEY = os.getenv("THESPORTSDB_KEY", "3")  # "3" = free public key
TIMEOUT = 15

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def is_youth(team_name: str) -> bool:
    """Return True if team name looks like youth/women team."""
    t = str(team_name).lower()
    youth_keywords = ["u21", "u-21", "u19", "u-20", "u23", "u17", "youth",
                      "under 21", "women", "wfc", "ladies"]
    return any(k in t for k in youth_keywords)


def deduplicate(fixtures: List[Dict]) -> List[Dict]:
    """Remove duplicate fixtures by (home, away, date)."""
    seen = set()
    out = []
    for f in fixtures:
        key = f"{f.get('home','').lower()}-{f.get('away','').lower()}-{f.get('date','')}"
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


# ──────────────────────────────────────────────
# 1. ESPN HIDDEN API FETCHER
# ──────────────────────────────────────────────

# ESPN league codes for all three regions
ESPN_LEAGUES = {
    # Europe
    "eng.1":   "Premier League",
    "esp.1":   "La Liga",
    "fra.1":   "Ligue 1",
    "ger.1":   "Bundesliga",
    "ita.1":   "Serie A",
    "ned.1":   "Eredivisie",
    "por.1":   "Primeira Liga",
    "tur.1":   "Süper Lig",
    "sco.1":   "Scottish Premiership",
    "bel.1":   "Belgian Pro League",
    "gre.1":   "Super League Greece",
    "sui.1":   "Swiss Super League",
    "den.1":   "Danish Superliga",
    "nor.1":   "Eliteserien",
    "swe.1":   "Allsvenskan",
    "rus.1":   "Russian Premier League",
    "ukr.1":   "Ukrainian Premier League",
    # Asia
    "chn.1":   "Chinese Super League",
    "jpn.1":   "J1 League",
    "kor.1":   "K League 1",
    "aus.1":   "A-League",
    "ind.1":   "Indian Super League",
    "sau.1":   "Saudi Pro League",
    "uae.1":   "UAE Pro League",
    "qat.1":   "Qatar Stars League",
    "tha.1":   "Thai League 1",
    # Americas
    "usa.1":   "MLS",
    "mex.1":   "Liga MX",
    "bra.1":   "Brasileirão Série A",
    "arg.1":   "Liga Profesional",
    "col.1":   "Categoría Primera A",
    "chi.1":   "Primera División de Chile",
    "per.1":   "Liga 1",
    "uru.1":   "Primera División Uruguaya",
    # International
    "fifa.world":   "FIFA World Cup",
    "fifa.wwc":     "FIFA Women's World Cup",
    "uefa.nations": "UEFA Nations League",
    "uefa.champions":"UEFA Champions League",
    "uefa.europa":  "UEFA Europa League",
    "concacaf.gold":"CONCACAF Gold Cup",
    "afc.asian":    "AFC Asian Cup",
    "caf.nations":  "Africa Cup of Nations",
}


def fetch_espn(date_obj: date, league_code: str, limit: int = 15) -> List[Dict]:
    """
    Fetch fixtures from ESPN hidden API for a specific league on a specific date.
    No API key required. Works globally.
    """
    fixtures = []
    yyyymmdd = date_obj.strftime("%Y%m%d")
    iso = date_obj.strftime("%Y-%m-%d")

    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"{league_code}/scoreboard?dates={yyyymmdd}"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []

        events = r.json().get("events", [])
        if not events:
            return []

        for ev in events[:limit]:
            try:
                comp = ev["competitions"][0]
                comps = comp["competitors"]

                home_team = next((c for c in comps if c.get("homeAway") == "home"), comps[0])
                away_team = next((c for c in comps if c.get("homeAway") == "away"), comps[1])

                home = home_team["team"]["displayName"]
                away = away_team["team"]["displayName"]

                # Skip youth/women
                if is_youth(home) or is_youth(away):
                    continue

                league_name = ESPN_LEAGUES.get(league_code, league_code)

                # Parse kickoff time (UTC → WAT = UTC+1)
                dt = datetime.fromisoformat(comp["date"].replace("Z", "+00:00"))
                wat_dt = dt + timedelta(hours=1)
                time_str = wat_dt.strftime("%H:%M")

                fixtures.append({
                    "home": home,
                    "away": away,
                    "league": league_name,
                    "time": time_str,
                    "date": iso,
                    "country": league_code.split(".")[0].upper(),
                    "real_date": iso,
                    "source": "ESPN",
                    "fixture_id": ev.get("id", ""),
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[ESPN] {league_code} error: {e}")

    return fixtures


def fetch_espn_all_leagues(date_obj: date, league_codes: List[str],
                            limit_per_league: int = 10) -> List[Dict]:
    """Fetch fixtures from multiple ESPN leagues at once."""
    all_fixtures = []
    for code in league_codes:
        fixtures = fetch_espn(date_obj, code, limit=limit_per_league)
        all_fixtures.extend(fixtures)
    return deduplicate(all_fixtures)


# ──────────────────────────────────────────────
# 2. THESPORTSDB FETCHER
# ──────────────────────────────────────────────

def fetch_thesportsdb(date_obj: date, limit: int = 20) -> List[Dict]:
    """
    Fetch soccer events from TheSportsDB for a given date.
    Free public API key: 3
    """
    fixtures = []
    iso = date_obj.strftime("%Y-%m-%d")

    url = (
        f"https://www.thesportsdb.com/api/v1/json/{THE_SPORTSDB_KEY}/"
        f"eventsday.php?d={iso}&s=Soccer"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []

        events = r.json().get("events") or []
        for ev in events[:limit]:
            try:
                home = ev.get("strHomeTeam", "")
                away = ev.get("strAwayTeam", "")
                league = ev.get("strLeague", "Unknown")

                if not home or not away:
                    continue
                if is_youth(home) or is_youth(away) or is_youth(league):
                    continue

                time_str = (ev.get("strTime") or "19:45")[:5]

                fixtures.append({
                    "home": home,
                    "away": away,
                    "league": league,
                    "time": time_str,
                    "date": iso,
                    "country": ev.get("strCountry", "FIFA"),
                    "real_date": iso,
                    "source": "TheSportsDB",
                    "fixture_id": ev.get("idEvent", ""),
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[TheSportsDB] error: {e}")

    return fixtures


# ──────────────────────────────────────────────
# 3. OPENFOOTBALL JSON FETCHER (National Teams / World Cup)
# ──────────────────────────────────────────────

def fetch_openfootball_national(date_obj: date) -> List[Dict]:
    """
    Fetch national team fixtures from OpenFootball worldcup.json.
    No API key required. Covers World Cups and major international tournaments.
    """
    fixtures = []
    iso = date_obj.strftime("%Y-%m-%d")

    # OpenFootball worldcup.json repo
    base = "https://raw.githubusercontent.com/openfootball/worldcup.json/master"
    # Try current and previous year files
    years_to_try = [date_obj.year, date_obj.year - 1, date_obj.year + 1]

    for year in years_to_try:
        for path in [f"{year}/worldcup.json", f"{year}/worldcup.json"]:
            url = f"{base}/{path}"
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                if r.status_code != 200:
                    continue

                data = r.json()
                matches = data.get("matches", [])
                for m in matches:
                    try:
                        m_date = m.get("date", "")
                        if m_date != iso:
                            continue

                        home = m.get("team1", "")
                        away = m.get("team2", "")

                        if not home or not away:
                            continue
                        if is_youth(home) or is_youth(away):
                            continue

                        fixtures.append({
                            "home": home,
                            "away": away,
                            "league": data.get("name", "FIFA International"),
                            "time": m.get("time", "19:45")[:5],
                            "date": iso,
                            "country": "FIFA",
                            "real_date": iso,
                            "source": "OpenFootball",
                            "fixture_id": "",
                        })
                    except Exception:
                        continue

                if fixtures:
                    return fixtures

            except Exception:
                continue

    return fixtures


# ──────────────────────────────────────────────
# 4. REGION-SPECIFIC FETCHERS (for /europeanleagues, etc.)
# ──────────────────────────────────────────────

REGION_ESPN_LEAGUES = {
    "european": [
        "eng.1", "esp.1", "fra.1", "ger.1", "ita.1",
        "ned.1", "por.1", "tur.1", "sco.1", "bel.1",
        "gre.1", "sui.1", "den.1", "nor.1", "swe.1",
        "rus.1", "ukr.1",
    ],
    "asian": [
        "chn.1", "jpn.1", "kor.1", "aus.1", "ind.1",
        "sau.1", "uae.1", "qat.1", "tha.1",
    ],
    "american": [
        "usa.1", "mex.1", "bra.1", "arg.1", "col.1",
        "chi.1", "per.1", "uru.1",
    ],
    "national": [
        "fifa.world", "uefa.nations", "uefa.champions",
        "concacaf.gold", "afc.asian", "caf.nations",
    ],
}


def fetch_by_region(date_obj: date, region: str,
                    limit: int = 20) -> List[Dict]:
    """
    Fetch fixtures for a specific region.

    region: 'european', 'asian', 'american', 'national'
    """
    region = region.lower()
    if region not in REGION_ESPN_LEAGUES:
        return []

    league_codes = REGION_ESPN_LEAGUES[region]
    all_fixtures = []

    # ESPN
    for code in league_codes:
        fixtures = fetch_espn(date_obj, code, limit=8)
        all_fixtures.extend(fixtures)

    # TheSportsDB (supplementary — catches leagues ESPN misses)
    tsdb = fetch_thesportsdb(date_obj, limit=30)
    all_fixtures.extend(tsdb)

    # OpenFootball for national teams
    if region == "national":
        of = fetch_openfootball_national(date_obj)
        all_fixtures.extend(of)

    # Deduplicate
    all_fixtures = deduplicate(all_fixtures)

    # For non-national regions, filter by region keywords
    if region != "national":
        region_keywords = {
            "european": ["premier league", "la liga", "bundesliga", "serie a",
                         "ligue 1", "eredivisie", "primeira", "süper lig",
                         "scottish", "belgian", "greek", "swiss", "danish",
                         "norwegian", "swedish", "russian", "ukrainian",
                         "champions league", "europa league"],
            "asian": ["chinese super", "j1", "j league", "k league",
                      "a-league", "indian super", "saudi", "uae", "qatar",
                      "thai", "asian"],
            "american": ["mls", "major league soccer", "liga mx", "brasileir",
                         "brazil", "argentina", "colombia", "chile", "peru",
                         "uruguay", "copa libertadores", "copa sudamericana"],
        }
        kws = region_keywords.get(region, [])
        all_fixtures = [
            f for f in all_fixtures
            if any(k in f.get("league", "").lower() for k in kws)
            or any(k in f.get("country", "").lower() for k in kws)
        ]

    return all_fixtures[:limit]


# ──────────────────────────────────────────────
# 5. UNIFIED TODAY FETCHER (replaces fetch_today_professional)
# ──────────────────────────────────────────────

def fetch_today_fixtures(date_obj: Optional[date] = None,
                         limit: int = 10) -> List[Dict]:
    """
    Master fetcher — gets today's fixtures from all free sources.
    Replaces fetch_today_professional().
    """
    if date_obj is None:
        # Use WAT (UTC+1)
        date_obj = (datetime.utcnow() + timedelta(hours=1)).date()

    iso = date_obj.strftime("%Y-%m-%d")
    all_fixtures = []

    # Priority 1: Major European leagues (most popular for betting)
    priority_leagues = [
        "eng.1", "esp.1", "ita.1", "ger.1", "fra.1",
        "chn.1", "jpn.1", "usa.1", "mex.1", "bra.1",
        "uefa.champions", "uefa.nations",
    ]
    for code in priority_leagues:
        fixtures = fetch_espn(date_obj, code, limit=5)
        all_fixtures.extend(fixtures)

    # Priority 2: TheSportsDB for everything else
    tsdb = fetch_thesportsdb(date_obj, limit=20)
    all_fixtures.extend(tsdb)

    # Priority 3: National teams
    national = fetch_openfootball_national(date_obj)
    all_fixtures.extend(national)

    # Deduplicate and filter
    all_fixtures = deduplicate(all_fixtures)
    all_fixtures = [f for f in all_fixtures if not is_youth(f.get("league", ""))]

    # Sort: European top leagues first, then Asian, then American, then other
    def sort_key(f):
        league = f.get("league", "").lower()
        if any(k in league for k in ["premier league", "la liga", "serie a",
                                      "bundesliga", "ligue 1", "champions league"]):
            return 0
        if any(k in league for k in ["chinese", "j1", "k league", "a-league",
                                      "saudi", "j league"]):
            return 1
        if any(k in league for k in ["mls", "liga mx", "brasileir", "argentina"]):
            return 2
        if "nations" in league or "world cup" in league or "fifa" in league:
            return 3
        return 4

    all_fixtures.sort(key=sort_key)
    return all_fixtures[:limit]


# ──────────────────────────────────────────────
# 6. DEBUG / TEST
# ──────────────────────────────────────────────

def debug_fetchers():
    """Quick self-test of all fetchers."""
    today = date.today()
    print(f"=== Testing fetchers for {today} ===\n")

    print("1. ESPN — Premier League:")
    for f in fetch_espn(today, "eng.1", limit=3):
        print(f"   {f['home']} vs {f['away']} @ {f['time']}")

    print("\n2. ESPN — Chinese Super League:")
    for f in fetch_espn(today, "chn.1", limit=3):
        print(f"   {f['home']} vs {f['away']} @ {f['time']}")

    print("\n3. TheSportsDB:")
    for f in fetch_thesportsdb(today, limit=3):
        print(f"   {f['home']} vs {f['away']} @ {f['time']} ({f['league']})")

    print("\n4. Region: European:")
    for f in fetch_by_region(today, "european", limit=3):
        print(f"   {f['home']} vs {f['away']} @ {f['time']} ({f['league']})")

    print("\n5. Today (master):")
    for f in fetch_today_fixtures(today, limit=5):
        print(f"   {f['home']} vs {f['away']} @ {f['time']} ({f['league']})")


if __name__ == "__main__":
    debug_fetchers()