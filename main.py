"""
BetMasterPro — Telegram AI Football Prediction Bot
==================================================
Production version with diagnostic endpoint.
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# ─────────────────────────────────────────────────────────────────────
# Bootstrap
# ─────────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("betmaster")


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
class Config:
    BOT_TOKEN: str = (os.getenv("BOT_TOKEN") or "").strip()
    CHANNEL_ID: str = (os.getenv("CHANNEL_ID") or "-1004371407166").strip()

    FLW_SECRET_KEY: str = os.getenv("FLUTTERWAVE_SECRET_KEY", "").strip()
    FLW_WEBHOOK_HASH: str = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET", "").strip()

    ADMIN_KEY: str = os.getenv("ADMIN_KEY", "").strip()

    PUBLIC_URL: str = os.getenv(
        "PUBLIC_URL", "https://betmaster-p09f.onrender.com"
    ).rstrip("/")

    SUPPORT_HANDLE: str = os.getenv("SUPPORT_HANDLE", "@Jibriliks")
    SUPPORT_URL: str = os.getenv("SUPPORT_URL", "https://t.me/Jibriliks")
    BOT_HANDLE: str = os.getenv("BOT_HANDLE", "@Betmasterpro_bot")
    BOT_LINK: str = os.getenv("BOT_LINK", "https://t.me/Betmasterpro_bot")
    CHANNEL_LINK: str = os.getenv(
        "CHANNEL_LINK", "https://t.me/+IFK0qoDI2B5lYWI0"
    )

    FREE_DAILY_LIMIT: int = int(os.getenv("FREE_DAILY_LIMIT", "2"))
    VIP_DAILY_LIMIT: int = int(os.getenv("VIP_DAILY_LIMIT", "10"))
    WEEKLY_PRICE_NGN: int = int(os.getenv("WEEKLY_PRICE_NGN", "2000"))
    MONTHLY_PRICE_NGN: int = int(os.getenv("MONTHLY_PRICE_NGN", "5000"))

    MORNING_POST_UTC: str = os.getenv("MORNING_POST_UTC", "05:05")

    @classmethod
    def telegram_api(cls) -> str:
        return f"https://api.telegram.org/bot{cls.BOT_TOKEN}"


if Config.CHANNEL_ID and not Config.CHANNEL_ID.startswith("-"):
    Config.CHANNEL_ID = "-100" + Config.CHANNEL_ID.lstrip("-")


DISCLAIMER = (
    "\n\n⚠️ *Disclaimer:* Betting risk. AI analysis only, 18+ stake responsibly."
)


# ─────────────────────────────────────────────────────────────────────
# Telegram client
# ─────────────────────────────────────────────────────────────────────
class TelegramClient:
    MAX_MESSAGE_LEN = 4096
    SEND_RETRIES = 3

    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}" if token else ""
        self._last_send_ts: float = 0.0
        self._min_gap: float = 0.05

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_send_ts
        if elapsed < self._min_gap:
            time.sleep(self._min_gap - elapsed)
        self._last_send_ts = time.monotonic()

    def send(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None,
        disable_preview: bool = True,
    ) -> bool:
        if not self.token:
            log.error("send() called without BOT_TOKEN set")
            return False

        if len(text) > self.MAX_MESSAGE_LEN:
            text = text[: self.MAX_MESSAGE_LEN - 3] + "..."

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(1, self.SEND_RETRIES + 1):
            self._throttle()
            try:
                r = requests.post(
                    f"{self.base}/sendMessage", json=payload, timeout=15
                )
                if r.status_code == 200:
                    return True

                if r.status_code == 429:
                    retry_after = r.json().get("parameters", {}).get(
                        "retry_after", 5
                    )
                    log.warning("Telegram flood-wait: %ss", retry_after)
                    time.sleep(retry_after + 1)
                    continue

                log.warning(
                    "sendMessage failed [%s]: %s", r.status_code, r.text[:300]
                )
                return False
            except requests.RequestException as exc:
                log.warning("sendMessage exception (try %s): %s", attempt, exc)
                time.sleep(1.5 * attempt)

        # Final fallback — retry as plain text (Markdown parse errors)
        if parse_mode == "Markdown":
            payload["parse_mode"] = ""
            try:
                r = requests.post(
                    f"{self.base}/sendMessage", json=payload, timeout=15
                )
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
        return False

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            requests.post(
                f"{self.base}/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": text},
                timeout=5,
            )
        except requests.RequestException as exc:
            log.debug("answerCallback failed: %s", exc)

    def delete_webhook(self) -> None:
        try:
            requests.get(
                f"{self.base}/deleteWebhook?drop_pending_updates=true",
                timeout=10,
            )
            log.info("Webhook cleared — polling mode active")
        except requests.RequestException as exc:
            log.warning("deleteWebhook failed: %s", exc)


tg = TelegramClient(Config.BOT_TOKEN)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _daily_limit(user) -> int:
    return (
        Config.VIP_DAILY_LIMIT if user.is_vip else Config.FREE_DAILY_LIMIT
    )


def activate_vip(user_id: int | str, plan: str) -> bool:
    from database import SessionLocal, get_user

    days = 7 if "weekly" in plan.lower() else 30
    db = SessionLocal()
    try:
        user = get_user(db, int(user_id))
        expiry = date.today() + timedelta(days=days)
        user.is_vip = True
        user.vip_expiry = str(expiry)
        user.daily_count = 0
        db.commit()

        price = (
            Config.WEEKLY_PRICE_NGN if days == 7 else Config.MONTHLY_PRICE_NGN
        )
        tg.send(
            int(user_id),
            f"🎉 *VIP Activated via {plan.title()}!*\n\n"
            f"✅ Plan: {plan.upper()} (₦{price:,})\n"
            f"📅 Valid till: {expiry}\n"
            f"💎 You now have {Config.VIP_DAILY_LIMIT} predictions/day "
            f"+ 2 personalised tips (6AM & 9PM WAT).\n\n"
            f"Chat now: {Config.BOT_LINK}\n"
            f"Support: {Config.SUPPORT_HANDLE}",
        )
        log.info("VIP activated: uid=%s plan=%s until=%s", user_id, plan, expiry)
        return True
    except Exception as exc:
        log.exception("activate_vip failed for uid=%s: %s", user_id, exc)
        return False
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────
# Polling loop
# ─────────────────────────────────────────────────────────────────────
def bot_polling_loop(stop_event: threading.Event) -> None:
    if not Config.BOT_TOKEN:
        log.error("BOT_TOKEN missing — polling thread not started")
        return

    try:
        from database import (
            SessionLocal, get_user, update_league_history,
        )
        log.info("✅ database.py imported OK")
    except Exception as exc:
        log.exception("FATAL: database.py failed to import — %s", exc)
        return

    try:
        from predictor import (
            get_ai_prediction,
            fetch_fixtures_by_country,
            fetch_real_fixtures,
        )
        log.info("✅ predictor.py imported OK")
    except Exception as exc:
        log.exception("FATAL: predictor.py failed to import — %s", exc)
        return

    try:
        tg.delete_webhook()
    except Exception as exc:
        log.warning("deleteWebhook failed (continuing anyway): %s", exc)

    offset = 0
    log.info("✅ Polling loop started — bot is now listening for messages")

    while not stop_event.is_set():
        try:
            resp = requests.get(
                f"{tg.base}/getUpdates",
                params={"offset": offset, "timeout": 20},
                timeout=25,
            ).json()

            if not resp.get("ok"):
                log.warning("getUpdates not ok: %s", resp)
                time.sleep(5)
                continue

            updates = resp.get("result", [])
            if updates:
                log.info("Received %d update(s)", len(updates))

            for upd in updates:
                offset = upd["update_id"] + 1
                try:
                    if "callback_query" in upd:
                        _handle_callback(
                            upd, get_ai_prediction,
                            fetch_real_fixtures, update_league_history,
                        )
                    elif "message" in upd:
                        _handle_message(
                            upd, get_ai_prediction,
                            fetch_fixtures_by_country,
                            fetch_real_fixtures,
                            update_league_history,
                        )
                except Exception:
                    log.exception(
                        "Handler failed for update %s", upd.get("update_id")
                    )
        except requests.RequestException as exc:
            log.warning("Polling network error: %s", exc)
            time.sleep(5)
        except Exception:
            log.exception("Polling loop unexpected error")
            time.sleep(5)

    log.info("Polling loop stopped")


# ─────────────────────────────────────────────────────────────────────
# Update handlers
# ─────────────────────────────────────────────────────────────────────
def _handle_callback(upd, get_ai_prediction, fetch_real_fixtures, update_league_history):
    from database import SessionLocal, get_user

    cq = upd["callback_query"]
    chat_id = cq["message"]["chat"]["id"]
    user_id = cq["from"]["id"]
    data = cq.get("data", "")
    tg.answer_callback(cq["id"], "Generating predictions…")

    if data != "predict_top5":
        return

    db = SessionLocal()
    try:
        user = get_user(db, user_id)
        limit = _daily_limit(user)

        if user.daily_count >= limit:
            tg.send(
                chat_id,
                f"🚫 You have used {user.daily_count}/{limit} today.\n\n"
                f"🆓 FREE: {Config.FREE_DAILY_LIMIT}/day\n"
                f"💎 VIP: {Config.VIP_DAILY_LIMIT}/day\n\n"
                f"Upgrade: {Config.PUBLIC_URL}/subscribe?uid={user_id}\n"
                f"Support: {Config.SUPPORT_HANDLE}",
            )
            return

        fixtures = (
            fetch_real_fixtures(days_ahead=0, limit=5)
            or fetch_real_fixtures(days_ahead=1, limit=5)
        )
        if not fixtures:
            tg.send(chat_id, "📅 No fixtures available right now. Try again later.")
            return

        tg.send(
            chat_id,
            f"🔮 *TOP 5 PREDICTIONS — {datetime.now().strftime('%d %B %Y')}*\n"
            f"Near-accurate AI analysis:\n",
        )

        count = 0
        for f in fixtures[:5]:
            if user.daily_count >= limit:
                break
            payload = {
                "home": f["home"], "away": f["away"], "league": f["league"],
                "home_xg": 1.5, "away_xg": 1.2,
                "home_form": "WDWWL", "away_form": "LWDWL",
                "h2h": 2, "home_inj": "None", "away_inj": "None",
                "odds_h": f["odds_h"], "odds_d": f["odds_d"],
                "odds_a": f["odds_a"], "odds_over": 1.75,
            }
            p = get_ai_prediction(payload)
            update_league_history(db, user, f["league"])
            tg.send(
                chat_id,
                f"⚽ *{f['home']} vs {f['away']}*\n"
                f"🏆 {f['league']} | 📅 {f['date']} {f['time']} WAT\n"
                f"🎯 *Pick: {p['best_pick']}* ({p['confidence']}%)\n"
                f"📝 {p['explanation']}\n\n"
                f"✅ *{p['verdict']}*\n"
                f"{p['stake']}{p['disclaimer']}\n",
            )
            user.daily_count += 1
            count += 1
            db.commit()

        remaining = limit - user.daily_count
        if count:
            tg.send(
                chat_id,
                f"✅ {count} predictions used. Remaining: {remaining}/{limit} today.\n\n"
                f"💬 More: {Config.BOT_LINK}\n"
                f"🆘 Support: {Config.SUPPORT_HANDLE}",
            )
        else:
            tg.send(
                chat_id,
                f"🚫 Limit reached {limit}/{limit} today. Resets midnight WAT.\n"
                f"Upgrade: {Config.PUBLIC_URL}/subscribe?uid={chat_id}\n"
                f"Support: {Config.SUPPORT_HANDLE}",
            )
    finally:
        db.close()


def _handle_message(upd, get_ai_prediction, fetch_fixtures_by_country, fetch_real_fixtures, update_league_history):
    from database import SessionLocal, get_user

    msg = upd.get("message") or {}
    if "text" not in msg or msg.get("chat", {}).get("type") != "private":
        return

    chat_id = msg["chat"]["id"]
    text = msg["text"].strip()
    user_id = msg["from"]["id"]
    username = msg["from"].get("username", "")
    low = text.lower()

    db = SessionLocal()
    try:
        user = get_user(db, user_id, username)
        limit = _daily_limit(user)

        if low.startswith("/start"):
            tg.send(
                chat_id,
                f"🎯 *Welcome to BetMasterPro — Super Smart AI* 🎯\n\n"
                f"100% LIVE fixtures + predictions!\n\n"
                f"*Commands:*\n"
                f"⚽ `Arsenal vs Chelsea` — any match prediction\n"
                f"📅 `/today` — Top 10 LIVE fixtures + Predict button\n"
                f"🌍 `/fixturesengland` — England PL today\n"
                f"🌍 `/fixtureschina` — China Super League\n"
                f"🌍 `/fixturesworld` — National teams LIVE\n"
                f"💎 `/myplan` — Check plan ({user.daily_count}/{limit} used today)\n"
                f"💳 `/subscribe` — Upgrade to VIP\n"
                f"🆘 `/help` — Support\n\n"
                f"*Limits:*\n"
                f"🆓 FREE: {Config.FREE_DAILY_LIMIT}/day + 1 unique tip 6AM WAT\n"
                f"💎 VIP: {Config.VIP_DAILY_LIMIT}/day + 2 personalised tips\n\n"
                f"Channel: {Config.CHANNEL_LINK}\n"
                f"Bot: {Config.BOT_LINK}\n"
                f"Support: {Config.SUPPORT_HANDLE}",
            )

        elif low.startswith("/help"):
            tg.send(
                chat_id,
                f"🆘 *BetMasterPro Support*\n\n"
                f"Need help?\n"
                f"👤 {Config.SUPPORT_HANDLE} — {Config.SUPPORT_URL}\n"
                f"🤖 Bot: {Config.BOT_LINK}\n"
                f"📢 Channel: {Config.CHANNEL_LINK}\n\n"
                f"*Commands:*\n"
                f"/today — 10 LIVE fixtures today\n"
                f"/fixturesengland — England fixtures\n"
                f"/fixtures + country name\n"
                f"/myplan — Check usage ({user.daily_count}/{limit})\n"
                f"/subscribe — Upgrade\n\n"
                f"We reply within 2 hours!",
            )

        elif low.startswith("/fixtures"):
            country_raw = low.replace("/fixtures", "").strip().split()
            country_raw = country_raw[0] if country_raw else "england"
            if country_raw in {"today", "tomorrow"}:
                country_raw = "england"

            if user.daily_count >= limit:
                tg.send(
                    chat_id,
                    f"🚫 *Limit reached* {user.daily_count}/{limit} today.\n\n"
                    f"🆓 FREE: {Config.FREE_DAILY_LIMIT}/day\n"
                    f"💎 VIP: {Config.VIP_DAILY_LIMIT}/day — Upgrade for more!\n\n"
                    f"👉 {Config.PUBLIC_URL}/subscribe?uid={user_id}\n"
                    f"Support: {Config.SUPPORT_HANDLE}",
                )
                return

            tg.send(
                chat_id,
                f"🌍 Fetching *{country_raw.title()}* LIVE fixtures for "
                f"TODAY {datetime.now().strftime('%d %B %Y')} — 100% verified…",
            )
            fixtures = fetch_fixtures_by_country(country_raw, days_ahead=0, limit=3)

            if not fixtures:
                tg.send(
                    chat_id,
                    f"📅 No {country_raw.title()} fixtures today "
                    f"({datetime.now().strftime('%d %B %Y')}).\n\n"
                    f"Try /fixturesworld for national teams or /today for all games.\n\n"
                    f"Support: {Config.SUPPORT_HANDLE}\n"
                    f"Bot: {Config.BOT_LINK}",
                )
                return

            lines = [
                f"📅 *{country_raw.upper()} FIXTURES TODAY — "
                f"{datetime.now().strftime('%d %B %Y')}* — LIVE\n"
            ]
            for i, f in enumerate(fixtures, 1):
                lines.append(
                    f"{i}. *{f['home']} vs {f['away']}*\n"
                    f"   🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n"
                )
            lines.append(f"💡 Tap to predict!\nBot: {Config.BOT_LINK}")

            keyboard = {
                "inline_keyboard": [[
                    {"text": f"🔮 Predict {country_raw.title()}",
                     "callback_data": "predict_top5"}
                ]]
            }
            tg.send(chat_id, "\n".join(lines), reply_markup=keyboard)

        elif low.startswith("/myplan"):
            plan_txt = (
                f"💎 VIP till {user.vip_expiry}"
                if user.is_vip
                else f"🆓 FREE ({Config.FREE_DAILY_LIMIT}/day)"
            )
            tg.send(
                chat_id,
                f"*Your Plan:* {plan_txt}\n"
                f"📊 Used today: {user.daily_count}/{limit}\n"
                f"⭐ Favourite League: {user.favorite_league}\n"
                f"💬 Total chats: {user.total_chats}\n\n"
                f"{'✅ VIP: ' + str(Config.VIP_DAILY_LIMIT) + '/day' if user.is_vip else f'🚫 FREE limit {Config.FREE_DAILY_LIMIT}/day — Upgrade for {Config.VIP_DAILY_LIMIT}/day'}\n\n"
                f"Upgrade: {Config.PUBLIC_URL}/subscribe?uid={user_id}\n"
                f"Bot: {Config.BOT_LINK}\n"
                f"Support: {Config.SUPPORT_HANDLE}",
            )

        elif low.startswith("/subscribe"):
            tg.send(
                chat_id,
                f"💳 *BetMasterPro VIP Plans* — Card + Bank Transfer auto-activate\n\n"
                f"🆓 FREE: {Config.FREE_DAILY_LIMIT} predictions/day\n"
                f"💎 WEEKLY: ₦{Config.WEEKLY_PRICE_NGN:,} — "
                f"{Config.VIP_DAILY_LIMIT} predictions/day (7 days)\n"
                f"💎 MONTHLY: ₦{Config.MONTHLY_PRICE_NGN:,} — "
                f"{Config.VIP_DAILY_LIMIT} predictions/day (30 days)\n\n"
                f"👉 {Config.PUBLIC_URL}/subscribe?uid={user_id}\n\n"
                f"Bot: {Config.BOT_LINK}\n"
                f"Support: {Config.SUPPORT_HANDLE}",
            )

        elif low.startswith("/today"):
            if user.daily_count >= limit:
                tg.send(
                    chat_id,
                    f"🚫 *Daily limit reached* {user.daily_count}/{limit}\n\n"
                    f"Resets midnight WAT.\n\n"
                    f"💎 Upgrade to VIP for {Config.VIP_DAILY_LIMIT}/day:\n"
                    f"{Config.PUBLIC_URL}/subscribe?uid={user_id}\n\n"
                    f"Support: {Config.SUPPORT_HANDLE}\n"
                    f"Bot: {Config.BOT_LINK}",
                )
                return

            tg.send(
                chat_id,
                f"📅 Fetching TOP 10 LIVE fixtures TODAY "
                f"{datetime.now().strftime('%d %B %Y')} — 100% verified from ESPN…",
            )
            fixtures = fetch_real_fixtures(days_ahead=0, limit=10)
            if not fixtures:
                tg.send(
                    chat_id,
                    f"📅 No top fixtures today "
                    f"{datetime.now().strftime('%d %B %Y')} — checking tomorrow…",
                )
                fixtures = fetch_real_fixtures(days_ahead=1, limit=10)
                header = (
                    f"📅 *No games today — TOP 10 UPCOMING TOMORROW — "
                    f"{(datetime.now() + timedelta(days=1)).strftime('%d %B %Y')}*\n\n"
                )
            else:
                header = (
                    f"📅 *TOP {len(fixtures)} LIVE FIXTURES TODAY — "
                    f"{datetime.now().strftime('%d %B %Y')}* — Verified LIVE\n\n"
                )

            body = header
            for i, f in enumerate(fixtures, 1):
                body += (
                    f"{i}. *{f['home']} vs {f['away']}*\n"
                    f"   🏆 {f['league']} | ⏰ {f['time']} WAT | 📅 {f['date']}\n\n"
                )
            body += (
                f"💡 Tap below to get predictions! "
                f"({user.daily_count}/{limit} used today)\n"
                f"Bot: {Config.BOT_LINK}"
            )
            keyboard = {
                "inline_keyboard": [[
                    {"text": "🔮 Predict Top 5 Matches",
                     "callback_data": "predict_top5"}
                ]]
            }
            tg.send(chat_id, body, reply_markup=keyboard)

        elif "vs" in low and 5 < len(text) < 100:
            if user.daily_count >= limit:
                tg.send(
                    chat_id,
                    f"🚫 *Daily limit reached: {user.daily_count}/{limit}*\n\n"
                    f"I track by Telegram ID even if you clear chat.\n"
                    f"Resets midnight WAT.\n\n"
                    f"🆓 FREE: {Config.FREE_DAILY_LIMIT}/day\n"
                    f"💎 VIP: {Config.VIP_DAILY_LIMIT}/day\n\n"
                    f"💳 Upgrade now:\n"
                    f"{Config.PUBLIC_URL}/subscribe?uid={user_id}\n\n"
                    f"Bot: {Config.BOT_LINK}\n"
                    f"Support: {Config.SUPPORT_HANDLE}",
                )
                return

            parts = [x.strip().title() for x in text.lower().split("vs")]
            home = parts[0] if parts else text.title()
            away = parts[1] if len(parts) > 1 else "Opponent"

            league_guess = (
                user.favorite_league if user.is_vip else "Custom Match"
            )
            national_keywords = {
                "nigeria", "ghana", "england", "brazil", "france",
                "germany", "spain", "argentina",
            }
            if (any(k in home.lower() for k in national_keywords)
                    and any(k in away.lower() for k in national_keywords)):
                league_guess = "National Teams — International Friendly"

            payload = {
                "home": home, "away": away, "league": league_guess,
                "home_xg": 1.6, "away_xg": 1.1,
                "home_form": "WDWWL", "away_form": "LWDWL",
                "h2h": 2, "home_inj": "None", "away_inj": "None",
                "odds_h": round(random.uniform(1.9, 3.2), 2),
                "odds_d": round(random.uniform(3.0, 4.0), 2),
                "odds_a": round(random.uniform(2.2, 3.8), 2),
                "odds_over": 1.75,
            }
            pred = get_ai_prediction(payload)
            update_league_history(db, user, league_guess)
            user.daily_count += 1
            db.commit()

            tg.send(
                chat_id,
                f"⚽ *{home} vs {away}*\n"
                f"🏆 {league_guess} | 📅 {datetime.now().strftime('%d %B %Y')}\n"
                f"💰 1:{payload['odds_h']} X:{payload['odds_d']} 2:{payload['odds_a']}\n\n"
                f"🎯 *Pick: {pred['best_pick']}* ({pred['confidence']}%)\n"
                f"📝 {pred['explanation']}\n\n"
                f"✅ *EXPERT VERDICT: {pred['verdict']}*\n"
                f"{pred['stake']}\n"
                f"📊 Market: {pred['market']}\n\n"
                f"📈 Used today: {user.daily_count}/{limit} "
                f"{'(FREE)' if not user.is_vip else '(VIP)'}\n"
                f"{pred['disclaimer']}\n\n"
                f"💬 More predictions: {Config.BOT_LINK}\n"
                f"🆘 Support: {Config.SUPPORT_HANDLE}",
            )

        else:
            tg.send(
                chat_id,
                f"Send match like `Arsenal vs Chelsea` or use:\n"
                f"/today — 10 LIVE fixtures\n"
                f"/fixturesengland\n"
                f"/myplan — {user.daily_count}/{limit} used\n\n"
                f"Bot: {Config.BOT_LINK}\n"
                f"Support: {Config.SUPPORT_HANDLE}",
            )

    except Exception:
        log.exception("Message handler failed for uid=%s", user_id)
        db.rollback()
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────
def channel_scheduler(stop_event: threading.Event) -> None:
    from database import (
        SessionLocal, get_all_users, is_already_posted, mark_as_posted,
    )
    from predictor import fetch_real_fixtures, get_ai_prediction

    posted: set[str] = set()
    log.info("Scheduler started — daily post at %s UTC", Config.MORNING_POST_UTC)

    while not stop_event.is_set():
        try:
            now_utc = datetime.now(timezone.utc)
            hm = now_utc.strftime("%H:%M")
            today = now_utc.strftime("%Y-%m-%d")

            if hm == Config.MORNING_POST_UTC and f"{today}-morning" not in posted:
                _run_morning_job(
                    today, get_ai_prediction, fetch_real_fixtures,
                    SessionLocal, get_all_users,
                    is_already_posted, mark_as_posted,
                )
                posted.add(f"{today}-morning")
                posted = {k for k in posted if k.startswith(today)}
        except Exception:
            log.exception("Scheduler iteration failed")

        stop_event.wait(60)


def _run_morning_job(today, get_ai_prediction, fetch_real_fixtures,
                     SessionLocal, get_all_users,
                     is_already_posted, mark_as_posted):
    db = SessionLocal()
    try:
        fixtures = fetch_real_fixtures(days_ahead=1, limit=15)
        unique = []
        for f in fixtures:
            h = f"{f['home']}-{f['away']}-{f['date']}"
            if not is_already_posted(db, h):
                unique.append(f)
                mark_as_posted(db, h)
                if len(unique) >= 2:
                    break
        if not unique:
            unique = fixtures[:2]

        msg = f"🔥 *BetMasterPro Morning — {today}* — Unique LIVE Tips\n\n"
        for f in unique:
            p = get_ai_prediction({
                "home": f["home"], "away": f["away"], "league": f["league"],
                "home_xg": 1.5, "away_xg": 1.2,
                "home_form": "WDWWL", "away_form": "LWDWL",
                "h2h": 2, "home_inj": "None", "away_inj": "None",
                "odds_h": f["odds_h"], "odds_d": f["odds_d"],
                "odds_a": f["odds_a"], "odds_over": 1.75,
            })
            msg += (
                f"⚽ *{f['home']} vs {f['away']}*\n"
                f"🏆 {f['league']} | 📅 {f['date']} {f['time']} WAT\n"
                f"🎯 {p['best_pick']} | ✅ {p['verdict']}\n"
                f"{p['stake']}\n\n"
            )
        msg += (
            f"💬 More predictions: {Config.BOT_LINK}\n"
            f"🆘 Support: {Config.SUPPORT_HANDLE}\n"
            f"🔗 {Config.CHANNEL_LINK}"
            f"{DISCLAIMER}"
        )
        if Config.CHANNEL_ID:
            tg.send(Config.CHANNEL_ID, msg)

        for u in get_all_users(db):
            try:
                fav = u.favorite_league if u.is_vip else None
                fxs = fetch_real_fixtures(
                    days_ahead=random.randint(1, 3),
                    limit=2 if u.is_vip else 1,
                    fav_league=fav,
                )
                pm = (
                    f"☀️ Morning "
                    f"{'VIP ' + u.favorite_league if u.is_vip else 'Free'} Tip "
                    f"— Unique — {today}:\n\n"
                )
                for f in fxs:
                    p = get_ai_prediction({
                        "home": f["home"], "away": f["away"], "league": f["league"],
                        "home_xg": 1.5, "away_xg": 1.2,
                        "home_form": "WDWWL", "away_form": "LWDWL",
                        "h2h": 2, "home_inj": "None", "away_inj": "None",
                        "odds_h": f["odds_h"], "odds_d": f["odds_d"],
                        "odds_a": f["odds_a"], "odds_over": 1.75,
                    })
                    pm += (
                        f"⚽ {f['home']} vs {f['away']} — {p['best_pick']}\n"
                        f"✅ {p['verdict']}\n\n"
                    )
                pm += (
                    f"Bot: {Config.BOT_LINK} | "
                    f"Support: {Config.SUPPORT_HANDLE}"
                    f"{DISCLAIMER}"
                )
                if not u.is_vip:
                    pm += (
                        f"\n💎 Upgrade to {Config.VIP_DAILY_LIMIT}/day: "
                        f"{Config.PUBLIC_URL}/subscribe?uid={u.user_id}"
                    )
                tg.send(u.user_id, pm)
            except Exception:
                log.exception("Morning DM failed for uid=%s", u.user_id)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────
# FastAPI app with lifespan
# ─────────────────────────────────────────────────────────────────────
_stop_event = threading.Event()
_threads: list[threading.Thread] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=" * 62)
    log.info("BetMasterPro starting")
    log.info("  Bot:      %s", Config.BOT_LINK)
    log.info("  Channel:  %s", Config.CHANNEL_ID)
    log.info("  Support:  %s", Config.SUPPORT_HANDLE)
    log.info("  Public:   %s", Config.PUBLIC_URL)
    log.info("  Admin:    %s", "enabled" if Config.ADMIN_KEY else "DISABLED")
    log.info("=" * 62)

    for target in (bot_polling_loop, channel_scheduler):
        t = threading.Thread(target=target, args=(_stop_event,), daemon=True)
        t.start()
        _threads.append(t)

    yield

    log.info("BetMasterPro shutting down…")
    _stop_event.set()
    for t in _threads:
        t.join(timeout=5)


app = FastAPI(title="BetMasterPro", lifespan=lifespan)


# ─────────────────────────────────────────────────────────────────────
# System endpoints
# ─────────────────────────────────────────────────────────────────────
@app.get("/")
async def home():
    try:
        r = requests.get(f"{tg.base}/getMe", timeout=8).json()
        ok = r.get("ok", False)
        username = r.get("result", {}).get("username", "UNKNOWN")
    except Exception as exc:
        ok, username = False, f"Error {exc}"

    return {
        "status": "LIVE",
        "bot_ok": ok,
        "bot_username": username,
        "bot_link": Config.BOT_LINK,
        "bot_token_set": bool(Config.BOT_TOKEN),
        "channel_id": Config.CHANNEL_ID,
        "support": Config.SUPPORT_HANDLE,
        "limits": {
            "free": Config.FREE_DAILY_LIMIT,
            "vip": Config.VIP_DAILY_LIMIT,
        },
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    return {"ok": True, "time_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/diagnose")
async def diagnose():
    """Full health check — confirms threads, imports, and Telegram reachability."""
    results = {
        "bot_token_set": bool(Config.BOT_TOKEN),
        "channel_id": Config.CHANNEL_ID,
        "database_url_set": bool(os.getenv("DATABASE_URL")),
        "threads": [{"name": t.name, "alive": t.is_alive()} for t in _threads],
        "imports": {},
        "telegram": None,
        "webhook": None,
    }

    for mod in ("database", "predictor"):
        try:
            __import__(mod)
            results["imports"][mod] = "OK"
        except Exception as exc:
            results["imports"][mod] = f"FAIL: {type(exc).__name__}: {exc}"

    try:
        r = requests.get(f"{tg.base}/getMe", timeout=8).json()
        results["telegram"] = {
            "ok": r.get("ok", False),
            "username": r.get("result", {}).get("username"),
        }
    except Exception as exc:
        results["telegram"] = f"Error: {exc}"

    try:
        r = requests.get(f"{tg.base}/getWebhookInfo", timeout=8).json()
        results["webhook"] = {
            "url": r.get("result", {}).get("url", ""),
            "pending": r.get("result", {}).get("pending_update_count", 0),
        }
    except Exception as exc:
        results["webhook"] = f"Error: {exc}"

    return results


# ─────────────────────────────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────────────────────────────
def _verify_admin(key: Optional[str]) -> None:
    if not Config.ADMIN_KEY:
        raise HTTPException(503, "Admin endpoints disabled (ADMIN_KEY not set)")
    if key != Config.ADMIN_KEY:
        raise HTTPException(403, "Invalid admin key")


@app.get("/pay")
async def pay(plan: str, uid: str):
    if not Config.FLW_SECRET_KEY:
        return JSONResponse(
            {"error": "Flutterwave keys not set"}, status_code=500
        )
    if plan not in {"weekly", "monthly"}:
        return JSONResponse({"error": "Invalid plan"}, status_code=400)

    amount = (
        Config.WEEKLY_PRICE_NGN if plan == "weekly" else Config.MONTHLY_PRICE_NGN
    )
    tx_ref = f"BETMASTER-{uid}-{plan}-{int(time.time())}"

    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": (
            f"{Config.PUBLIC_URL}/verify?tx_ref={tx_ref}"
            f"&uid={uid}&plan={plan}&amount={amount}"
        ),
        "customer": {
            "email": f"{uid}@betmasterpro.com",
            "name": f"User {uid}",
        },
        "customizations": {
            "title": f"BetMasterPro {plan.upper()}",
            "description": f"VIP access — {plan}",
        },
    }
    headers = {"Authorization": f"Bearer {Config.FLW_SECRET_KEY}"}

    try:
        r = requests.post(
            "https://api.flutterwave.com/v3/payments",
            json=payload, headers=headers, timeout=15,
        ).json()
        if r.get("status") == "success":
            return RedirectResponse(r["data"]["link"])
        log.warning("Flutterwave init failed: %s", r)
        return JSONResponse(r, status_code=400)
    except requests.RequestException as exc:
        log.exception("Flutterwave request error")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/verify")
async def verify(tx_ref: str, uid: str, plan: str, amount: int = 0):
    if not Config.FLW_SECRET_KEY:
        return HTMLResponse(
            "<h1>Payment verification unavailable</h1>", status_code=500
        )

    headers = {"Authorization": f"Bearer {Config.FLW_SECRET_KEY}"}
    try:
        r = requests.get(
            f"https://api.flutterwave.com/v3/transactions?tx_ref={tx_ref}",
            headers=headers, timeout=15,
        ).json()

        if r.get("status") == "success" and r.get("data"):
            data = r["data"][0] if isinstance(r["data"], list) else r["data"]
            paid = float(data.get("amount", 0))
            expected = (
                Config.WEEKLY_PRICE_NGN
                if plan == "weekly"
                else Config.MONTHLY_PRICE_NGN
            )

            if data.get("status") in {"successful", "completed"} \
                    and paid >= expected and data.get("currency") == "NGN":
                activate_vip(uid, plan)
                expiry = date.today() + timedelta(
                    days=7 if plan == "weekly" else 30
                )
                return HTMLResponse(
                    f"<html><body style='text-align:center;padding:40px;"
                    f"font-family:sans-serif'>"
                    f"<h1>✅ Payment Successful!</h1>"
                    f"<p>{plan.upper()} — {Config.VIP_DAILY_LIMIT} "
                    f"predictions/day till {expiry}</p>"
                    f"<a href='{Config.BOT_LINK}' style='background:green;"
                    f"color:white;padding:15px 30px;text-decoration:none;"
                    f"border-radius:10px'>Go to Bot {Config.BOT_HANDLE}</a>"
                    f"<br><br>Support: {Config.SUPPORT_HANDLE}</body></html>"
                )
            log.warning(
                "Verify mismatch tx=%s paid=%s expected=%s cur=%s",
                tx_ref, paid, expected, data.get("currency"),
            )

        return HTMLResponse(
            f"<h1>❌ Not confirmed {tx_ref}</h1>"
            f"<a href='/subscribe?uid={uid}'>Retry</a>"
        )
    except Exception as exc:
        log.exception("Verify failed")
        return HTMLResponse(f"Error {exc}", status_code=500)


@app.post("/flutterwave-webhook")
async def flutterwave_webhook(
    request: Request,
    verif_hash: Optional[str] = Header(None, alias="verif-hash"),
):
    if Config.FLW_WEBHOOK_HASH:
        if verif_hash != Config.FLW_WEBHOOK_HASH:
            log.warning("Webhook rejected — bad verif-hash")
            raise HTTPException(403, "Invalid signature")

    try:
        body = await request.body()
        data = json.loads(body)

        if (data.get("event") == "charge.completed"
                and data.get("data", {}).get("status") == "successful"):
            tx_ref = data["data"].get("tx_ref", "")
            parts = tx_ref.split("-")
            if len(parts) >= 3 and parts[0] == "BETMASTER":
                uid, plan = parts[1], parts[2]
                activate_vip(uid, plan)
                log.info("Webhook activated VIP: uid=%s plan=%s", uid, plan)

        return JSONResponse({"status": "ok"})
    except Exception:
        log.exception("Webhook processing error")
        return JSONResponse({"status": "error"}, status_code=200)


# ─────────────────────────────────────────────────────────────────────
# Admin
# ─────────────────────────────────────────────────────────────────────
@app.get("/admin/activate")
async def admin_activate(
    uid: str,
    plan: str = "monthly",
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None),
):
    _verify_admin(x_admin_key or key)
    ok = activate_vip(uid, plan)
    return HTMLResponse(
        f"{'✅ Activated' if ok else '❌ Failed'} User {uid} "
        f"{plan.upper()} — {Config.BOT_LINK}"
    )


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None),
):
    _verify_admin(x_admin_key or key)

    from database import SessionLocal, get_all_users

    db = SessionLocal()
    try:
        users = get_all_users(db)
        html = [
            "<html><body style='padding:20px;font-family:sans-serif'>",
            f"<h1>BetMasterPro Users — {Config.BOT_LINK}</h1>",
            f"<p>Support: {Config.SUPPORT_HANDLE} | "
            f"FREE: {Config.FREE_DAILY_LIMIT}/day, "
            f"VIP: {Config.VIP_DAILY_LIMIT}/day</p>",
            "<table border=1 cellpadding=8>",
            "<tr><th>ID</th><th>Username</th><th>Plan</th>"
            "<th>Used</th><th>Expiry</th><th>Action</th></tr>",
        ]
        for u in users:
            limit = _daily_limit(u)
            html.append(
                f"<tr><td>{u.user_id}</td><td>{u.username}</td>"
                f"<td>{'💎 VIP' if u.is_vip else '🆓 FREE'}</td>"
                f"<td>{u.daily_count}/{limit}</td>"
                f"<td>{u.vip_expiry}</td>"
                f"<td><a href='/admin/activate?uid={u.user_id}"
                f"&plan=weekly&key={key or ''}'>Weekly ₦"
                f"{Config.WEEKLY_PRICE_NGN:,}</a> | "
                f"<a href='/admin/activate?uid={u.user_id}"
                f"&plan=monthly&key={key or ''}'>Monthly ₦"
                f"{Config.MONTHLY_PRICE_NGN:,}</a></td></tr>"
            )
        html.append(f"</table><p>Total: {len(users)}</p></body></html>")
        return HTMLResponse("".join(html))
    finally:
        db.close()


@app.get("/post-now")
async def post_now(
    key: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None),
):
    _verify_admin(x_admin_key or key)

    from database import (
        SessionLocal, is_already_posted, mark_as_posted,
    )
    from predictor import fetch_real_fixtures, get_ai_prediction

    db = SessionLocal()
    try:
        fixtures = fetch_real_fixtures(limit=10)
        uniq = []
        for f in fixtures:
            h = (
                f"{f['home']}-{f['away']}-{date.today()}-"
                f"manual-{random.randint(1, 9999)}"
            )
            if not is_already_posted(db, h):
                uniq.append(f)
                mark_as_posted(db, h)
            if len(uniq) >= 2:
                break
        if not uniq:
            uniq = fixtures[:2]

        msg = f"🔥 Test {datetime.now().strftime('%H:%M:%S')}\n\n"
        for f in uniq:
            p = get_ai_prediction({
                "home": f["home"], "away": f["away"], "league": f["league"],
                "home_xg": 1.5, "away_xg": 1.2,
                "home_form": "WDWWL", "away_form": "LWDWL",
                "h2h": 2, "home_inj": "None", "away_inj": "None",
                "odds_h": f["odds_h"], "odds_d": f["odds_d"],
                "odds_a": f["odds_a"], "odds_over": 1.75,
            })
            msg += f"{f['home']} vs {f['away']} — {p['verdict']}\n"
        msg += (
            f"Bot: {Config.BOT_LINK} | "
            f"Support: {Config.SUPPORT_HANDLE}{DISCLAIMER}"
        )
        if Config.CHANNEL_ID:
            tg.send(Config.CHANNEL_ID, msg)
        return {"posted": True, "fixtures": uniq}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────
# Subscribe landing
# ─────────────────────────────────────────────────────────────────────
@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe(request: Request):
    uid = request.query_params.get("uid", "")
    return HTMLResponse(f"""
    <!doctype html>
    <html>
    <head>
        <title>BetMasterPro VIP — {Config.BOT_HANDLE}</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
            body{{font-family:system-ui,sans-serif;background:#0f172a;
                 color:white;text-align:center;padding:20px;margin:0}}
            .card{{background:#1e293b;padding:25px;border-radius:15px;
                   max-width:420px;margin:20px auto}}
            .btn{{display:block;padding:15px;margin:12px 0;
                  border-radius:10px;text-decoration:none;
                  color:white;font-weight:bold}}
            .weekly{{background:#22c55e}}
            .monthly{{background:#3b82f6}}
            a{{color:#22c55e}}
        </style>
    </head>
    <body>
        <h1>💎 BetMasterPro VIP</h1>
        <p>Your ID: <b>{uid}</b></p>
        <div class="card">
            <h3>Upgrade — Get {Config.VIP_DAILY_LIMIT} predictions/day</h3>
            <p>🆓 FREE: {Config.FREE_DAILY_LIMIT}/day + 1 tip 6AM</p>
            <p>💎 VIP: {Config.VIP_DAILY_LIMIT}/day + 2 personalised tips</p>
            <a class="btn weekly"
               href="/pay?plan=weekly&uid={uid}">
                💚 Weekly ₦{Config.WEEKLY_PRICE_NGN:,} (7 days)
            </a>
            <a class="btn monthly"
               href="/pay?plan=monthly&uid={uid}">
                💙 Monthly ₦{Config.MONTHLY_PRICE_NGN:,} (30 days)
            </a>
            <p style="font-size:12px">
                Card + Bank Transfer auto-activate via Flutterwave webhook
            </p>
            <p>Bot: <a href="{Config.BOT_LINK}">{Config.BOT_LINK}</a></p>
            <p>Support: <a href="{Config.SUPPORT_URL}">
                {Config.SUPPORT_HANDLE}</a></p>
            <p style="font-size:11px">{DISCLAIMER}</p>
        </div>
    </body>
    </html>
    """)


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )
