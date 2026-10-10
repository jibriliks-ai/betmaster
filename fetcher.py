"""
fetcher.py — Global soccer fixture fetcher
Uses worldwide-accessible APIs:
- ESPN hidden API (no key, 250+ leagues)
- TheSportsDB (free public key "3")
- OpenFootball JSON (public domain)

No API-Football dependency.
Regions supported: european, asian, american, african, national
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
                      "under 21", "women", "wfc", "ladies", "u18", "u16"]
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
# ESPN HIDDEN API
# ──────────────────────────────────────────────
ESPN_LEAGUES = {
    # Europe
    "eng.1":    "Premier League",
    "esp.1":    "La Liga",
    "fra.1":    "Ligue 1",
    "ger.1":    "Bundesliga",
    "ita.1":    "Serie A",
    "ned.1":    "Eredivisie",
    "por.1":    "Primeira Liga",
    "tur.1":    "Süper Lig",
    "sco.1":    "Scottish Premiership",
    "bel.1":    "Belgian Pro League",
    "gre.1":    "Super League Greece",
    "sui.1":    "Swiss Super League",
    "den.1":    "Danish Superliga",
    "nor.1":    "Eliteserien",
    "swe.1":    "Allsvenskan",
    "rus.1":    "Russian Premier League",
    "ukr.1":    "Ukrainian Premier League",
    "aut.1":    "Austrian Bundesliga",
    "cze.1":    "Czech First League",
    "pol.1":    "Ekstraklasa",
    "rom.1":    "Liga I",
    "cro.1":    "HNL",
    "srb.1":    "Serbian SuperLiga",
    # Asia
    "chn.1":    "Chinese Super League",
    "jpn.1":    "J1 League",
    "kor.1":    "K League 1",
    "aus.1":    "A-League",
    "ind.1":    "Indian Super League",
    "sau.1":    "Saudi Pro League",
    "uae.1":    "UAE Pro League",
    "qat.1":    "Qatar Stars League",
    "tha.1":    "Thai League 1",
    "idn.1":    "Liga 1 Indonesia",
    "mys.1":    "Malaysia Super League",
    "vnm.1":    "V.League 1",
    # Americas
    "usa.1":    "MLS",
    "mex.1":    "Liga MX",
    "bra.1":    "Brasileirão Série A",
    "arg.1":    "Liga Profesional Argentina",
    "col.1":    "Categoría Primera A",
    "chi.1":    "Primera División de Chile",
    "per.1":    "Liga 1 Peru",
    "uru.1":    "Primera División Uruguaya",
    "ecu.1":    "LigaPro Ecuador",
    "par.1":    "Primera División Paraguay",
    "ven.1":    "Liga FUTVE",
    "crc.1":    "Liga Promerica",
    # Africa
    "rsa.1":    "South African Premier Division",
    "egy.1":    "Egyptian Premier League",
    "mar.1":    "Botola Pro",
    "nga.1":    "Nigeria Premier League",
    "gha.1":    "Ghana Premier League",
    "ken.1":    "Kenyan Premier League",
    "tun.1":    "Ligue Professionnelle 1",
    "alg.1":    "Ligue Professionnelle 1",
    "civ.1":    "Ligue 1 Côte d'Ivoire",
    "cmr.1":    "Elite One",
    # International
    "fifa.world":     "FIFA World Cup",
    "fifa.wwc":       "FIFA Women's World Cup",
    "fifa.worldq.uefa": "World Cup Qualifier UEFA",
    "fifa.worldq.conmebol": "World Cup Qualifier CONMEBOL",
    "fifa.worldq.caf": "World Cup Qualifier CAF",
    "fifa.worldq.afc": "World Cup Qualifier AFC",
    "fifa.worldq.concacaf": "World Cup Qualifier CONCACAF",
    "uefa.nations":   "UEFA Nations League",
    "uefa.champions": "UEFA Champions League",
    "uefa.europa":    "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    "uefa.euroq":     "UEFA Euro Qualifiers",
    "uefa.euro":      "UEFA Euro",
    "concacaf.gold":  "CONCACAF Gold Cup",
    "concacaf.nations.league": "CONCACAF Nations League",
    "afc.asian":      "AFC Asian Cup",
    "afc.asian.cup":  "AFC Asian Cup",
    "caf.nations":    "Africa Cup of Nations",
    "caf.nations.qual": "Africa Cup of Nations Qualifiers",
    "caf.champions":  "CAF Champions League",
}


def fetch_espn(date_obj: date, league_code: str, limit: int = 15) -> List[Dict]:
    """Fetch fixtures from ESPN hidden API for a specific league on a specific date."""
    fixtures = []
    yyyymmdd = date_obj.strftime("%Y%m%d")
    iso = date_obj.strftime("%Y-%m-%d")

    url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
           f"{league_code}/scoreboard?dates={yyyymmdd}")

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

                if is_youth(home) or is_youth(away):
                    continue

                league_name = ESPN_LEAGUES.get(league_code, league_code)

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
# THESPORTSDB
# ──────────────────────────────────────────────
def fetch_thesportsdb(date_obj: date, limit: int = 30) -> List[Dict]:
    """Fetch soccer events from TheSportsDB for a given date."""
    fixtures = []
    iso = date_obj.strftime("%Y-%m-%d")

    url = (f"https://www.thesportsdb.com/api/v1/json/{THE_SPORTSDB_KEY}/"
           f"eventsday.php?d={iso}&s=Soccer")

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
# OPENFOOTBALL (National teams / World Cup)
# ──────────────────────────────────────────────
def fetch_openfootball_national(date_obj: date) -> List[Dict]:
    """Fetch national team fixtures from OpenFootball JSON."""
    fixtures = []
    iso = date_obj.strftime("%Y-%m-%d")

    base = "https://raw.githubusercontent.com/openfootball/worldcup.json/master"
    years_to_try = [date_obj.year, date_obj.year - 1, date_obj.year + 1]

    for year in years_to_try:
        url = f"{base}/{year}/worldcup.json"
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
# REGION CONFIG
# ──────────────────────────────────────────────
REGION_ESPN_LEAGUES = {
    "european": [
        "eng.1", "esp.1", "fra.1", "ger.1", "ita.1",
        "ned.1", "por.1", "tur.1", "sco.1", "bel.1",
        "gre.1", "sui.1", "den.1", "nor.1", "swe.1",
        "rus.1", "ukr.1", "aut.1", "cze.1", "pol.1",
        "rom.1", "cro.1", "srb.1",
    ],
    "asian": [
        "chn.1", "jpn.1", "kor.1", "aus.1", "ind.1",
        "sau.1", "uae.1", "qat.1", "tha.1", "idn.1",
        "mys.1", "vnm.1",
    ],
    "american": [
        "usa.1", "mex.1", "bra.1", "arg.1", "col.1",
        "chi.1", "per.1", "uru.1", "ecu.1", "par.1",
        "ven.1", "crc.1",
    ],
    "african": [
        "rsa.1", "egy.1", "mar.1", "nga.1", "gha.1",
        "ken.1", "tun.1", "alg.1", "civ.1", "cmr.1",
    ],
    "national": [
        "fifa.world", "fifa.worldq.uefa", "fifa.worldq.conmebol",
        "fifa.worldq.caf", "fifa.worldq.afc", "fifa.worldq.concacaf",
        "uefa.nations", "uefa.champions", "uefa.europa",
        "concacaf.gold", "concacaf.nations.league",
        "afc.asian", "caf.nations", "caf.nations.qual",
    ],
}

REGION_KEYWORDS = {
    "european": ["premier league", "la liga", "bundesliga", "serie a",
                 "ligue 1", "eredivisie", "primeira", "süper lig",
                 "scottish", "belgian", "greek", "swiss", "danish",
                 "norwegian", "swedish", "russian", "ukrainian",
                 "austrian", "czech", "polish", "romanian", "croatian",
                 "serbian", "champions league", "europa league",
                 "conference league", "england", "spain", "italy",
                 "germany", "france", "netherlands", "portugal"],
    "asian": ["chinese super", "j1", "j league", "k league",
              "a-league", "indian super", "saudi", "uae", "qatar",
              "thai", "indonesia", "malaysia", "v.league",
              "asian", "china", "japan", "korea", "australia",
              "india", "saudi arabia"],
    "american": ["mls", "major league soccer", "liga mx", "brasileir",
                 "brazil", "argentina", "colombia", "chile", "peru",
                 "uruguay", "ecuador", "paraguay", "venezuela",
                 "costa rica", "concacaf", "copa libertadores",
                 "copa sudamericana", "usa", "mexico"],
    "african": ["south africa", "egypt", "morocco", "nigeria",
                "ghana", "kenya", "tunisia", "algeria", "ivory coast",
                "cameroon", "caf", "africa", "botola", "premier division",
                "premier league nigeria"],
}


def fetch_by_region(date_obj: date, region: str, limit: int = 20) -> List[Dict]:
    """
    Fetch fixtures for a specific region.
    region: 'european', 'asian', 'american', 'african', 'national'
    """
    region = region.lower()
    if region not in REGION_ESPN_LEAGUES:
        return []

    league_codes = REGION_ESPN_LEAGUES[region]
    all_fixtures = []

    # ESPN (main source)
    for code in league_codes:
        fixtures = fetch_espn(date_obj, code, limit=8)
        all_fixtures.extend(fixtures)

    # TheSportsDB (supplementary)
    tsdb = fetch_thesportsdb(date_obj, limit=40)
    all_fixtures.extend(tsdb)

    # OpenFootball for national
    if region == "national":
        of = fetch_openfootball_national(date_obj)
        all_fixtures.extend(of)

    # Deduplicate
    all_fixtures = deduplicate(all_fixtures)

    # Filter by region keywords (except national)
    if region != "national":
        kws = REGION_KEYWORDS.get(region, [])
        filtered = []
        for f in all_fixtures:
            league_low = f.get("league", "").lower()
            country_low = f.get("country", "").lower()
            if any(k in league_low for k in kws) or any(k in country_low for k in kws):
                filtered.append(f)
        # If filter is too strict, keep all to avoid empty results
        if filtered:
            all_fixtures = filtered

    return all_fixtures[:limit]


# ──────────────────────────────────────────────
# UNIFIED TODAY FETCHER
# ──────────────────────────────────────────────
def fetch_today_fixtures(date_obj: Optional[date] = None,
                         limit: int = 15) -> List[Dict]:
    """
    Master fetcher — gets today's fixtures from all free sources.
    Prioritizes top leagues.
    """
    if date_obj is None:
        date_obj = (datetime.utcnow() + timedelta(hours=1)).date()

    iso = date_obj.strftime("%Y-%m-%d")
    all_fixtures = []

    priority_leagues = [
        "eng.1", "esp.1", "ita.1", "ger.1", "fra.1",
        "chn.1", "jpn.1", "usa.1", "mex.1", "bra.1",
        "uefa.champions", "uefa.nations", "rsa.1", "egy.1",
    ]
    for code in priority_leagues:
        fixtures = fetch_espn(date_obj, code, limit=5)
        all_fixtures.extend(fixtures)

    tsdb = fetch_thesportsdb(date_obj, limit=30)
    all_fixtures.extend(tsdb)

    national = fetch_openfootball_national(date_obj)
    all_fixtures.extend(national)

    all_fixtures = deduplicate(all_fixtures)
    all_fixtures = [f for f in all_fixtures if not is_youth(f.get("league", ""))]

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
        if any(k in league for k in ["africa", "south africa", "egypt", "nigeria"]):
            return 3
        if "nations" in league or "world cup" in league or "fifa" in league:
            return 4
        return 5

    all_fixtures.sort(key=sort_key)
    return all_fixtures[:limit]


# ──────────────────────────────────────────────
# DIAGNOSTIC
# ──────────────────────────────────────────────
def debug_fetchers():
    """Quick self-test of all fetchers."""
    today = date.today()
    print(f"=== Testing fetchers for {today} ===\n")

    for region in ["european", "asian", "american", "african", "national"]:
        print(f"\n{region.upper()}:")
        fxs = fetch_by_region(today, region, limit=5)
        print(f"  Found {len(fxs)}")
        for f in fxs[:3]:
            print(f"   • {f['home']} vs {f['away']} ({f['league']}) @ {f['time']}")

    print(f"\nTODAY (master):")
    fxs = fetch_today_fixtures(today, limit=5)
    for f in fxs[:5]:
        print(f"   • {f['home']} vs {f['away']} @ {f['time']} ({f['league']})")


if __name__ == "__main__":
    debug_fetchers()
