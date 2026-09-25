                    elif low.startswith("/today"):
                        limit = 10 # ALWAYS 10 for advertising!
                        send_message(chat_id, f"📅 Fetching TOP 10 fixtures for TODAY {datetime.now().strftime('%d %b %Y')} - 100% LIVE from ESPN + SuperSport...")
                        fixtures = fetch_real_fixtures(days_ahead=0, limit=10, fav_league=user.favorite_league if user.is_vip else None)

                        # Send 10 fixtures with dates first
                        list_msg = f"📅 **TOP 10 FIXTURES TODAY - {datetime.now().strftime('%d %B %Y')}**\n\n"
                        for i, f in enumerate(fixtures, 1):
                            list_msg += f"{i}. **{f['home']} vs {f['away']}**\n 🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n\n"
                        list_msg += f"💡 Tap below to get predictions for top 5!\n💬 More: {BOT_HANDLE} | {BOT_HANDLE_2}"

                        # Send with inline button
                        try:
                            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                            keyboard = {"inline_keyboard": [[{"text": "🔮 Predict Top 5 Matches", "callback_data": "predict_top5"}]]}
                            requests.post(url, json={"chat_id": chat_id, "text": list_msg, "parse_mode": "Markdown", "reply_markup": keyboard}, timeout=10)
                        except:
                            send_message(chat_id, list_msg)

                        user.daily_count += 1
                        db.commit()
