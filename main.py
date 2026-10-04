# Add to imports
import numpy as np
from scipy.stats import poisson

# Add API-Football fetch function
def fetch_api_football_fixtures(date_obj, league_id=None, country=None):
    """Fetch fixtures from API-Football v3."""
    if not API_FOOTBALL_KEY:
        return []
    iso = date_obj.strftime("%Y-%m-%d")
    params = {"date": iso, "timezone": "Africa/Lagos"}
    if league_id:
        params["league"] = league_id
    try:
        url = "https://v3.football.api-sports.io/fixtures"
        headers = {"x-apisports-key": API_FOOTBALL_KEY}
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return []
        fixtures = []
        for f in r.json().get("response", []):
            fixtures.append({
                "home": f["teams"]["home"]["name"],
                "away": f["teams"]["away"]["name"],
                "league": f["league"]["name"],
                "country": f["league"]["country"],
                "time": f["fixture"]["date"][11:16],
                "date": iso,
                "fixture_id": f["fixture"]["id"],
                "real_date": iso
            })
        return fixtures
    except Exception as e:
        print(f"API-Football error: {e}")
        return []


# Add FIFA fixtures for /national
def fetch_fifa_fixtures(date_obj):
    # (implementation as shown in Section 1)
    ...


# Region command handler
REGION_MAP = {
    "europeanleagues":  "european",
    "asianleagues":     "asian",
    "americanleagues":  "american",
}

# In process_update():
elif low.startswith("/europeanleagues"):
    handle_region(chat_id, user_id, "european")
elif low.startswith("/asianleagues"):
    handle_region(chat_id, user_id, "asian")
elif low.startswith("/americanleagues"):
    handle_region(chat_id, user_id, "american")
elif low.startswith("/national"):
    handle_national(chat_id, user_id)
