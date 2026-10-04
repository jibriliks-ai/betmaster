def get_dynamic_ai_prediction(data):
    """Enhanced with Dixon-Coles + xG + API-Football predictions."""
    home = data.get("home", "Home")
    away = data.get("away", "Away")
    
    # 1. Get historical stats (your existing brain)
    home_stats = HISTORICAL_STATS.get(home, {})
    away_stats = HISTORICAL_STATS.get(away, {})
    
    # 2. Try to get xG data from Understat
    home_xg = fetch_understat_xg(home)
    away_xg = fetch_understat_xg(away)
    
    # 3. Run Dixon-Coles model
    dc_result = dixon_coles_predict(
        home_attack=home_stats.get("attack", 0.5),
        away_attack=away_stats.get("attack", 0.4),
        home_defense=home_stats.get("defense", 0.3),
        away_defense=away_stats.get("defense", 0.4),
        home_advantage=0.3,
        rho=-0.05
    )
    
    # 4. Cross-check with API-Football predictions endpoint
    api_pred = None
    if data.get("fixture_id") and API_FOOTBALL_KEY:
        api_pred = fetch_api_football_prediction(data["fixture_id"])
    
    # 5. Blend probabilities
    if api_pred:
        blend_weight = 0.3
        dc_result["home_win"] = dc_result["home_win"] * (1 - blend_weight) + api_pred["home_win"] * blend_weight
        dc_result["draw"] = dc_result["draw"] * (1 - blend_weight) + api_pred["draw"] * blend_weight
        dc_result["away_win"] = dc_result["away_win"] * (1 - blend_weight) + api_pred["away_win"] * blend_weight
    
    # 6. Value bet detection against bookmaker odds
    odds = {
        "home": data.get("odds_h", 2.2),
        "draw": data.get("odds_d", 3.2),
        "away": data.get("odds_a", 2.9)
    }
    value_bets = find_value_bets(dc_result, odds)
    
    # 7. Generate recommendation
    best_market = max(
        [("Home Win", dc_result["home_win"]),
         ("Draw", dc_result["draw"]),
         ("Away Win", dc_result["away_win"])],
        key=lambda x: x[1]
    )
    
    # Build explanation with xG context
    explanation = (
        f"Dixon-Coles model: {home} xG {dc_result['home_xg']:.2f} vs "
        f"{away} xG {dc_result['away_xg']:.2f}. "
        f"Probabilities: Home {dc_result['home_win']}% / Draw {dc_result['draw']}% / "
        f"Away {dc_result['away_win']}%. "
    )
    if value_bets:
        explanation += f"VALUE BET DETECTED: {value_bets[0]['market']} @ {value_bets[0]['odds']} (edge {value_bets[0]['edge']}). "
    if api_pred:
        explanation += f"API-Football cross-check: {api_pred.get('advice', 'N/A')}."
    
    return {
        "best_market": best_market[0],
        "best_pick": f"{best_market[0]}",
        "odds": odds.get("home") if best_market[0] == "Home Win" else odds.get("draw") if best_market[0] == "Draw" else odds.get("away"),
        "confidence": round(best_market[1], 1),
        "explanation": explanation,
        "verdict": f"AI MODEL: {best_market[0]} ({best_market[1]:.1f}%)",
        "all_markets": [
            {"market": "1X2", "pick": "Home Win", "odds": odds["home"], "conf": dc_result["home_win"]},
            {"market": "1X2", "pick": "Draw", "odds": odds["draw"], "conf": dc_result["draw"]},
            {"market": "1X2", "pick": "Away Win", "odds": odds["away"], "conf": dc_result["away_win"]},
        ],
        "value_bets": value_bets,
        "h2h": f"Dixon-Coles top scorelines: {dc_result['top_scorelines']}",
        "form": f"xG: {home} {dc_result['home_xg']:.2f} vs {away} {dc_result['away_xg']:.2f}",
        "standings": f"Model confidence: {best_market[1]:.1f}%",
        "disclaimer": "\n\n18+ Bet responsibly. Model uses Dixon-Coles + xG + API-Football blend."
    }
