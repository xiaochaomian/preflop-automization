"""PokerNow Bot - Entry point."""

from __future__ import annotations

import asyncio
import argparse
import sys

from observer.browser import PokerNowObserver
from observer.state import Street, Card
from engine.decision import get_recommendation
from dashboard.server import start_server, update_dashboard, ALERT_HANDS
import dashboard.server as dashboard_module
from utils.cards import hand_to_category
from stats.tracker import StatsTracker
from stats.database import init_db, record_hand
from config import GAME_URL, PLAYER_NAME, POLL_INTERVAL


async def main(game_url: str, player_name: str, poll_interval: float, port: int) -> None:
    if not game_url:
        print("Error: No game URL provided. Set GAME_URL in .env or pass --url")
        sys.exit(1)
    if not player_name:
        print("Error: No player name provided. Set PLAYER_NAME in .env or pass --name")
        sys.exit(1)

    # Patch config so observer picks up CLI args
    import config
    config.PLAYER_NAME = player_name

    # Initialize persistent database
    init_db()
    print("SQLite database initialized (hands.db)")

    # Start dashboard server
    runner = await start_server(port=port)

    observer = PokerNowObserver()
    stats_tracker = StatsTracker()
    last_acted_cards = ""  # track which hand we already acted on

    # State for hand completion detection
    prev_hand_number = 0
    prev_my_cards: list[Card] = []
    prev_community_cards: list[Card] = []
    prev_pot = 0.0
    prev_players: list = []
    prev_actions: list = []

    print(f"Launching browser for: {game_url}")
    print(f"Player name: {player_name}")
    print(f"Dashboard: http://localhost:{port}")
    print(f"Alert hands: {len(ALERT_HANDS)} hands loaded")
    print(f"Play mode: {dashboard_module.PLAY_MODE} (toggle via dashboard)")
    print("Join the game in the browser window, then the bot will start observing.\n")
    print("Press Ctrl+C to quit.\n")

    try:
        await observer.launch(game_url, headless=False)

        # Give user time to join the game
        await asyncio.sleep(3)

        while True:
            try:
                state = await observer.get_game_state()
                recommendation = get_recommendation(state)
                debug = observer.get_debug_log()
                hand_data = observer.get_hand_data()

                # Extract showdown and winner info from parsed hand data
                showdown_cards = hand_data.get("showdown_cards", {}) if hand_data else {}
                winners = hand_data.get("winners", {}) if hand_data else {}

                # Prepare action dicts with street info for stats tracker
                action_dicts = [
                    {
                        "player": a.player,
                        "type": a.type,
                        "amount": a.amount,
                        "street": a.street,
                    }
                    for a in state.action_history
                ]

                # Update stats tracker with comprehensive data
                stats_tracker.update(
                    hand_number=state.hand_number,
                    players=[{"name": p.name} for p in state.players],
                    actions=action_dicts,
                    showdown_cards=showdown_cards,
                    winners=winners,
                )

                update_dashboard(state, recommendation, debug, stats_tracker.get_all_stats())

                # ──────────────────────────────────────────────────────────
                # HAND COMPLETION DETECTION & DATABASE RECORDING
                # ──────────────────────────────────────────────────────────
                # Detect when a hand ends: hand_number changes OR we had cards
                # and now we don't (hand was completed).
                hand_just_completed = False

                if state.hand_number > 0 and state.hand_number != prev_hand_number and prev_hand_number > 0:
                    hand_just_completed = True
                elif len(prev_my_cards) == 2 and len(state.my_cards) == 0 and prev_hand_number > 0:
                    hand_just_completed = True

                if hand_just_completed and prev_my_cards:
                    try:
                        hand_id = record_hand(
                            hand_number=prev_hand_number,
                            hero_name=player_name,
                            hero_cards=prev_my_cards,
                            board=prev_community_cards,
                            actions=prev_actions,
                            showdown_cards=showdown_cards,
                            winners=winners,
                            pot_size=prev_pot,
                            big_blind=state.big_blind,
                            num_players=len(prev_players),
                        )
                        if showdown_cards:
                            shown_names = ", ".join(f"{p}: {c[0]}{c[1]}" for p, c in showdown_cards.items())
                            print(f"[DB] Hand #{prev_hand_number} recorded (id={hand_id}). Showdown: {shown_names}")
                        else:
                            print(f"[DB] Hand #{prev_hand_number} recorded (id={hand_id}). No showdown.")
                    except Exception as e:
                        print(f"[DB] Error recording hand: {e}")

                # Save current state for next iteration's hand completion detection
                prev_hand_number = state.hand_number
                prev_my_cards = list(state.my_cards)
                prev_community_cards = list(state.community_cards)
                prev_pot = state.pot
                prev_players = [{"name": p.name} for p in state.players]
                prev_actions = list(state.action_history)

                # ──────────────────────────────────────────────────────────
                # MODE-AWARE PREFLOP ACTIONS
                # ──────────────────────────────────────────────────────────
                if len(state.my_cards) == 2 and state.street == Street.PREFLOP:
                    c1, c2 = state.my_cards
                    notation = hand_to_category(c1.rank, c1.suit, c2.rank, c2.suit)
                    card_key = f"{c1}{c2}"
                    mode = dashboard_module.PLAY_MODE

                    if mode == "autonomous":
                        # Autonomous: execute the recommendation action
                        if card_key != last_acted_cards:
                            action = recommendation.get("action", "fold")
                            amount = recommendation.get("amount", 0)

                            if action == "fold":
                                last_acted_cards = card_key
                                print(f"[Auto] {notation} — FOLD (pressing F)")
                                try:
                                    await observer.page.keyboard.press("f")
                                except Exception as e:
                                    print(f"[Auto] Failed to press F: {e}")
                            elif action == "raise" and amount > 0:
                                last_acted_cards = card_key
                                raise_amount = int(amount)
                                print(f"[Auto] {notation} — RAISE to {raise_amount}")
                                try:
                                    # Type raise amount then press Enter
                                    await observer.page.keyboard.type(str(raise_amount))
                                    await asyncio.sleep(0.3)
                                    await observer.page.keyboard.press("Enter")
                                except Exception as e:
                                    print(f"[Auto] Failed to raise: {e}")
                            elif action == "call":
                                last_acted_cards = card_key
                                print(f"[Auto] {notation} — CALL")
                                try:
                                    await observer.page.keyboard.press("c")
                                except Exception as e:
                                    print(f"[Auto] Failed to call: {e}")
                            elif action == "check":
                                last_acted_cards = card_key
                                print(f"[Auto] {notation} — CHECK")
                                try:
                                    await observer.page.keyboard.press("k")
                                except Exception as e:
                                    print(f"[Auto] Failed to check: {e}")
                    else:
                        # Manual mode: auto-fold non-alert hands, alert for premium
                        if notation not in ALERT_HANDS and card_key != last_acted_cards:
                            last_acted_cards = card_key
                            print(f"[Auto-fold] {notation} ({c1}{c2}) — pressing F")
                            try:
                                await observer.page.keyboard.press("f")
                            except Exception as fe:
                                print(f"[Auto-fold] Failed to press F: {fe}")
                elif len(state.my_cards) == 0:
                    last_acted_cards = ""  # reset between hands

            except Exception as e:
                print(f"[Warning] Scraping error: {e}")

            await asyncio.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await observer.close()
        await runner.cleanup()


def cli() -> None:
    parser = argparse.ArgumentParser(description="PokerNow Bot - GTO Advisor")
    parser.add_argument("--url", default=GAME_URL, help="PokerNow game URL")
    parser.add_argument("--name", default=PLAYER_NAME, help="Your player name")
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL, help="Poll interval in seconds")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard server port")
    args = parser.parse_args()

    asyncio.run(main(args.url, args.name, args.interval, args.port))


if __name__ == "__main__":
    cli()
