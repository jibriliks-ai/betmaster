import os, requests
from datetime import date

def get_todays_fixtures():
    key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not key:
        return [
            {"id": 1, "home": "Man City", "away": "Arsenal", "league": "Premier League"},
            {"id": 2, "home": "Barcelona", "away": "Real Madrid", "league": "La Liga"},
            {"id": 3, "home": "Al Nassr", "away": "Al Hilal", "league": "Saudi Pro"},
        ]
    try:
        url = "https://v3.football.api-sports.io/fixtures"
        headers = {"x-apisports-key": key}
        r = requests.get(url, headers=headers, params={"date": date.today().isoformat()}, timeout=10).json()
        fixtures = []
        for f in r.get("response", [])[:10]:
            fixtures.append({
                "id": f["fixture"]["id"],
                "home": f["teams"]["home"]["name"],
                "away": f["teams"]["away"]["name"],
                "league": f["league"]["name"]
            })
        return fixtures or [{"id": 1, "home": "Man City", "away": "Arsenal", "league": "Premier League"}]
    except Exception as e:
        print(f"fetcher error: {e}")
        return [{"id": 1, "home": "Man City", "away": "Arsenal", "league": "Premier League"}]

def get_odds_from_api_football(fixture_id):
    return (2.10, 3.40, 3.20, 1.75)