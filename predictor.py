import os, json

def get_ai_prediction(match_data: dict):
    api_key = os.getenv("OPENROUTER_KEY", "").strip()
    if not api_key:
        return {
            "home_prob": 55, "draw_prob": 25, "away_prob": 20,
            "best_pick": "Over 1.5 Goals",
            "confidence": "Medium",
            "explanation": "Home scores at home, away defence leaks. Over 1.5 safer for small stake.",
            "is_value_bet": False,
            "stake_advice": "Flat 2% bankroll. 18+ Responsible."
        }
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        prompt = f"Match {match_data['home']} vs {match_data['away']} League {match_data['league']}. Odds H{match_data['odds_h']} D{match_data['odds_d']} A{match_data['odds_a']}. Return JSON home_prob,draw_prob,away_prob,best_pick,confidence,explanation,is_value_bet,stake_advice. Safe pick Over 1.5/X2/BTTS. No guarantee."
        res = client.chat.completions.create(
            model="deepseek/deepseek-chat",
            messages=[{"role":"user","content":prompt}],
            temperature=0.2,
            response_format={"type":"json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"AI error: {e}")
        return {
            "home_prob": 55, "draw_prob": 25, "away_prob": 20,
            "best_pick": "Over 1.5 Goals",
            "confidence": "Medium",
            "explanation": "Fallback: Home form better, safe over.",
            "is_value_bet": False,
            "stake_advice": "Flat 2% bankroll."
        }