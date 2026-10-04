# scrapers.py — separate module for bookmaker scrapers

def scrape_sportybet_odds():
    """Scrape SportyBet Nigeria pre-match odds."""
    try:
        url = "https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents"
        params = {"sportId": "sr:sport:1", "marketId": "1,18,10,14,29"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return {}
        return parse_sportybet_response(r.json())
    except Exception as e:
        print(f"SportyBet scrape error: {e}")
        return {}

def scrape_bet9ja_odds(league="premier_league"):
    """Scrape Bet9ja odds via NaijaBet_Api."""
    try:
        from NaijaBet_Api.bookmakers import Bet9ja
        from NaijaBet_Api.id import Betid
        bet9ja = Bet9ja()
        league_map = {
            "premier_league": Betid.PREMIERLEAGUE,
            "laliga": Betid.LALIGA,
            "seriea": Betid.SERIEA,
        }
        rows = bet9ja.get_league(league_map.get(league, Betid.PREMIERLEAGUE))
        return {row["match"]: row for row in rows}
    except Exception as e:
        print(f"Bet9ja scrape error: {e}")
        return {}