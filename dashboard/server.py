"""Live HTML dashboard server using aiohttp + Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from aiohttp import web

from observer.state import GameState
from utils.cards import hand_to_category

# Shared state: latest game state + recommendation, updated by main loop
_current_data: dict = {"state": None, "recommendation": None, "debug": [], "player_stats": {}}
_event = asyncio.Event()

# Play mode: "manual" (alerts only) or "autonomous" (auto-raise/fold)
PLAY_MODE: str = "manual"

# Path to persist hand range selections
HAND_RANGE_FILE = Path(__file__).parent.parent / "hand_range.json"

# Default premium hands that trigger the sound alert
DEFAULT_ALERT_HANDS = {
    # All pocket pairs
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
    # Ace-Ten through Ace-King suited
    "AKs", "AQs", "AJs", "ATs",
    # Ace-3 through Ace-5 suited
    "A5s", "A4s", "A3s",
    # Broadway suited connectors
    "KQs", "QJs", "JTs",
    # Suited connectors
    "T9s", "98s", "87s", "76s", "65s", "54s",
    # Ace-Ten through Ace-King offsuit
    "AKo", "AQo", "AJo", "ATo",
    # broadway offsuit
    "KQo", "KJo", "QJo",
    # Queen-Ten suited, King-Ten suited
    "QTs", "KTs",
}


def _load_hand_range() -> set[str]:
    """Load hand range from JSON file, fallback to defaults."""
    try:
        with open(HAND_RANGE_FILE, "r") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else DEFAULT_ALERT_HANDS.copy()
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_ALERT_HANDS.copy()


def _save_hand_range(hands: set[str]) -> None:
    """Persist hand range to JSON file."""
    with open(HAND_RANGE_FILE, "w") as f:
        json.dump(sorted(hands), f, indent=2)


# Initialize ALERT_HANDS from persistent storage
ALERT_HANDS: set[str] = _load_hand_range()


def update_dashboard(
    state: GameState,
    recommendation: dict,
    debug: list[str] | None = None,
    player_stats: dict | None = None,
) -> None:
    """Called by main loop to push new data to the dashboard."""
    serialized = _serialize_state(state)

    # Check if this is an alert hand
    alert = False
    hand_notation = ""
    if len(state.my_cards) == 2:
        c1, c2 = state.my_cards
        hand_notation = hand_to_category(c1.rank, c1.suit, c2.rank, c2.suit)
        alert = hand_notation in ALERT_HANDS
    serialized["hand_notation"] = hand_notation
    serialized["is_alert_hand"] = alert

    _current_data["state"] = serialized
    _current_data["recommendation"] = recommendation
    _current_data["debug"] = debug or []
    _current_data["player_stats"] = player_stats or {}
    _current_data["play_mode"] = PLAY_MODE
    _event.set()


def _serialize_state(state: GameState) -> dict:
    return {
        "my_cards": [{"rank": c.rank, "suit": c.suit} for c in state.my_cards],
        "community_cards": [{"rank": c.rank, "suit": c.suit} for c in state.community_cards],
        "pot": state.pot,
        "my_stack": state.my_stack,
        "my_name": state.my_name,
        "my_position": state.my_position.value,
        "street": state.street.value,
        "current_bet": state.current_bet,
        "big_blind": state.big_blind,
        "spr": round(state.spr, 1) if state.pot > 0 else None,
        "hand_number": state.hand_number,
        "num_players": state.num_players,
        "players": [
            {
                "name": p.name,
                "stack": p.stack,
                "position": p.position.value,
                "is_active": p.is_active,
                "current_bet": p.current_bet,
            }
            for p in state.players
        ],
        "action_history": [
            {"player": a.player, "type": a.type, "amount": a.amount, "street": a.street.value if hasattr(a.street, 'value') else str(a.street)}
            for a in state.action_history
        ],
    }


# ─── SSE & API Endpoints ────────────────────────────────────────────────────


async def handle_index(request: web.Request) -> web.Response:
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path) as f:
        return web.Response(text=f.read(), content_type="text/html")


async def handle_sse(request: web.Request) -> web.StreamResponse:
    """Server-Sent Events endpoint for live updates."""
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    await response.prepare(request)

    try:
        while True:
            # Send current data immediately
            payload = json.dumps(_current_data)
            await response.write(f"data: {payload}\n\n".encode())
            _event.clear()

            # Wait for next update or timeout (for keepalive)
            try:
                await asyncio.wait_for(_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Send keepalive comment
                await response.write(b": keepalive\n\n")
    except (ConnectionResetError, ConnectionError):
        pass

    return response


async def handle_api(request: web.Request) -> web.Response:
    """JSON endpoint for polling fallback."""
    return web.json_response(_current_data)


# ─── Hand Range Endpoints ────────────────────────────────────────────────────


async def handle_get_hand_range(request: web.Request) -> web.Response:
    """Return current alert hand range as JSON list."""
    return web.json_response({
        "hands": sorted(ALERT_HANDS),
        "total": len(ALERT_HANDS),
    })


async def handle_toggle_hand(request: web.Request) -> web.Response:
    """Toggle a single hand in the alert range."""
    global ALERT_HANDS
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    hand = data.get("hand", "")
    enabled = data.get("enabled", True)

    if not hand:
        return web.json_response({"error": "Missing 'hand' field"}, status=400)

    if enabled:
        ALERT_HANDS.add(hand)
    else:
        ALERT_HANDS.discard(hand)

    _save_hand_range(ALERT_HANDS)
    return web.json_response({"status": "ok", "hands": sorted(ALERT_HANDS), "total": len(ALERT_HANDS)})


async def handle_bulk_hand_range(request: web.Request) -> web.Response:
    """Replace the entire alert hand range."""
    global ALERT_HANDS
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    new_hands = data.get("hands", [])
    ALERT_HANDS = set(new_hands)
    _save_hand_range(ALERT_HANDS)
    return web.json_response({"status": "ok", "hands": sorted(ALERT_HANDS), "total": len(ALERT_HANDS)})


# ─── Play Mode Endpoints ─────────────────────────────────────────────────────


async def handle_get_mode(request: web.Request) -> web.Response:
    """Return current play mode."""
    return web.json_response({"mode": PLAY_MODE})


async def handle_set_mode(request: web.Request) -> web.Response:
    """Set play mode to 'manual' or 'autonomous'."""
    global PLAY_MODE
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    mode = data.get("mode", "")
    if mode not in ("manual", "autonomous"):
        return web.json_response({"error": "Mode must be 'manual' or 'autonomous'"}, status=400)

    PLAY_MODE = mode
    print(f"[Mode] Switched to {PLAY_MODE}")
    return web.json_response({"status": "ok", "mode": PLAY_MODE})


# ─── App Setup ───────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/events", handle_sse)
    app.router.add_get("/api/state", handle_api)
    # Hand range management
    app.router.add_get("/api/hand-range", handle_get_hand_range)
    app.router.add_post("/api/hand-range/toggle", handle_toggle_hand)
    app.router.add_post("/api/hand-range/bulk", handle_bulk_hand_range)
    # Play mode
    app.router.add_get("/api/mode", handle_get_mode)
    app.router.add_post("/api/mode", handle_set_mode)
    return app


async def start_server(host: str = "0.0.0.0", port: int = 8080) -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Dashboard server running at http://localhost:{port}")
    print(f"Alert hands loaded: {len(ALERT_HANDS)} hands from {HAND_RANGE_FILE}")
    return runner
