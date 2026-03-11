"""SQLite database for persistent hand tracking and player profiling.

Stores every hand that reaches showdown (or is otherwise completed) with:
- Full action history tagged by street
- Showdown card reveals
- Winner information
- Preflop action classification (3-bet, call 3-bet, open raise, limp)

This builds a persistent profile of each player's tendencies that survives
across sessions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from observer.state import Card, Street, Action
from utils.cards import hand_to_category, RANK_VALUES

DB_PATH = Path(__file__).parent.parent / "hands.db"


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database schema if tables don't exist."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS hands (
            hand_id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_number INTEGER,
            timestamp TEXT NOT NULL,
            hero_name TEXT,
            hero_cards TEXT,
            board TEXT,
            pot_size REAL DEFAULT 0,
            big_blind REAL DEFAULT 0,
            num_players INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id INTEGER NOT NULL,
            street TEXT NOT NULL,
            action_order INTEGER NOT NULL,
            player TEXT NOT NULL,
            action_type TEXT NOT NULL,
            amount REAL DEFAULT 0,
            FOREIGN KEY(hand_id) REFERENCES hands(hand_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS showdowns (
            showdown_id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            card1 TEXT NOT NULL,
            card2 TEXT NOT NULL,
            hand_notation TEXT NOT NULL,
            won INTEGER DEFAULT 0,
            FOREIGN KEY(hand_id) REFERENCES hands(hand_id)
        )
    """)

    # Denormalized table tracking what hands each player took specific actions with
    # at showdown. This is the key table for building opponent ranges.
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_shown_hands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            hand_notation TEXT NOT NULL,
            card1 TEXT NOT NULL,
            card2 TEXT NOT NULL,
            preflop_action TEXT NOT NULL,
            won INTEGER DEFAULT 0,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(hand_id) REFERENCES hands(hand_id)
        )
    """)

    # Indexes for fast queries
    c.execute("CREATE INDEX IF NOT EXISTS idx_showdowns_player ON showdowns(player)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_actions_hand ON actions(hand_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_player_shown_player ON player_shown_hands(player)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_player_shown_action ON player_shown_hands(preflop_action)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hands_number ON hands(hand_number)")

    conn.commit()
    conn.close()


def record_hand(
    hand_number: int,
    hero_name: str,
    hero_cards: list[Card],
    board: list[Card],
    actions: list[Action] | list[dict],
    showdown_cards: dict[str, list[Card]],
    winners: dict[str, float],
    pot_size: float,
    big_blind: float,
    num_players: int,
) -> int:
    """Record a completed hand to the database.

    Args:
        hand_number: The hand number from the game.
        hero_name: Our player name.
        hero_cards: Our hole cards.
        board: Community cards.
        actions: All actions in the hand (Action objects or dicts).
        showdown_cards: {player: [Card, Card]} for shown hands.
        winners: {player: amount_won} for pot winners.
        pot_size: Total pot at end.
        big_blind: Big blind size.
        num_players: Number of players dealt in.

    Returns:
        The hand_id of the recorded hand.
    """
    conn = get_connection()
    c = conn.cursor()
    timestamp = datetime.now().isoformat()

    hero_cards_str = "".join(f"{card.rank}{card.suit}" for card in hero_cards) if hero_cards else ""
    board_str = ",".join(f"{card.rank}{card.suit}" for card in board) if board else ""

    c.execute("""
        INSERT INTO hands (hand_number, timestamp, hero_name, hero_cards, board, pot_size, big_blind, num_players)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (hand_number, timestamp, hero_name, hero_cards_str, board_str, pot_size, big_blind, num_players))
    hand_id = c.lastrowid

    # Record all actions
    for i, action in enumerate(actions):
        if isinstance(action, Action):
            street_str = action.street.value if isinstance(action.street, Street) else str(action.street)
            player = action.player
            atype = action.type
            amount = action.amount
        else:
            street_val = action.get("street", "preflop")
            street_str = street_val.value if isinstance(street_val, Street) else str(street_val)
            player = action.get("player", "")
            atype = action.get("type", "")
            amount = action.get("amount", 0)

        c.execute("""
            INSERT INTO actions (hand_id, street, action_order, player, action_type, amount)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (hand_id, street_str, i, player, atype, amount))

    # Classify preflop actions for each player who showed
    preflop_classifications = _classify_preflop_actions(actions)

    # Record showdown cards
    for player, cards in showdown_cards.items():
        if not cards or len(cards) < 2:
            continue
        c1_str = f"{cards[0].rank}{cards[0].suit}"
        c2_str = f"{cards[1].rank}{cards[1].suit}"
        notation = hand_to_category(cards[0].rank, cards[0].suit, cards[1].rank, cards[1].suit)
        won = 1 if player in winners else 0

        c.execute("""
            INSERT INTO showdowns (hand_id, player, card1, card2, hand_notation, won)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (hand_id, player, c1_str, c2_str, notation, won))

        # Record in player_shown_hands with their preflop action classification
        preflop_action = preflop_classifications.get(player, "unknown")
        c.execute("""
            INSERT INTO player_shown_hands (hand_id, player, hand_notation, card1, card2, preflop_action, won, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (hand_id, player, notation, c1_str, c2_str, preflop_action, won, timestamp))

    conn.commit()
    conn.close()
    return hand_id


def _classify_preflop_actions(actions: list[Action] | list[dict]) -> dict[str, str]:
    """Classify each player's preflop action into categories.

    Categories:
    - 'open_raise': First raise preflop
    - '3bet': Re-raised after an initial raise
    - '4bet': Re-raised a 3-bet
    - 'call_open': Called an open raise
    - 'call_3bet': Called a 3-bet
    - 'limp': Called the big blind without raising
    - 'fold': Folded preflop
    - 'check': BB checked (no raise)
    """
    classifications: dict[str, str] = {}
    raise_count = 0

    for action in actions:
        if isinstance(action, Action):
            street = action.street
            player = action.player
            atype = action.type
        else:
            street_val = action.get("street", "preflop")
            street = street_val if isinstance(street_val, Street) else Street.PREFLOP
            player = action.get("player", "")
            atype = action.get("type", "")

        # Only look at preflop
        street_str = street.value if isinstance(street, Street) else str(street)
        if street_str != "preflop":
            continue

        if atype in ("raise", "bet"):
            raise_count += 1
            if raise_count == 1:
                classifications[player] = "open_raise"
            elif raise_count == 2:
                classifications[player] = "3bet"
            elif raise_count == 3:
                classifications[player] = "4bet"
            else:
                classifications[player] = f"{raise_count + 1}bet"
        elif atype == "call":
            if raise_count == 0:
                classifications[player] = "limp"
            elif raise_count == 1:
                classifications[player] = "call_open"
            elif raise_count == 2:
                classifications[player] = "call_3bet"
            else:
                classifications[player] = f"call_{raise_count + 1}bet"
        elif atype == "fold":
            classifications[player] = "fold"
        elif atype == "check":
            classifications.setdefault(player, "check")

    return classifications


# ─── Query Functions ─────────────────────────────────────────────────────────


def get_player_hands_by_action(player_name: str, preflop_action: str) -> dict[str, int]:
    """Get frequency of hand notations a player showed for a given preflop action.

    Example: get_player_hands_by_action("Villain", "3bet")
    Returns: {"AKs": 3, "QQ": 2, "JTs": 1, ...}
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT hand_notation, COUNT(*) as freq
        FROM player_shown_hands
        WHERE player = ? AND preflop_action = ?
        GROUP BY hand_notation
        ORDER BY freq DESC
    """, (player_name, preflop_action))
    results = {row["hand_notation"]: row["freq"] for row in c.fetchall()}
    conn.close()
    return results


def get_player_all_shown_hands(player_name: str) -> list[dict]:
    """Get all hands a player has ever shown at showdown.

    Returns list of dicts with: hand_notation, preflop_action, won, timestamp, card1, card2
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT hand_notation, preflop_action, won, timestamp, card1, card2
        FROM player_shown_hands
        WHERE player = ?
        ORDER BY timestamp DESC
    """, (player_name,))
    results = [dict(row) for row in c.fetchall()]
    conn.close()
    return results


def get_player_range_summary(player_name: str) -> dict[str, dict[str, int]]:
    """Get a comprehensive range summary for a player.

    Returns: {
        "3bet": {"AKs": 3, "QQ": 2},
        "call_3bet": {"JTs": 1, "TT": 2},
        "open_raise": {"ATo": 5, "KQs": 3},
        "limp": {"87s": 1},
        ...
    }
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT preflop_action, hand_notation, COUNT(*) as freq
        FROM player_shown_hands
        WHERE player = ?
        GROUP BY preflop_action, hand_notation
        ORDER BY preflop_action, freq DESC
    """, (player_name,))

    summary: dict[str, dict[str, int]] = {}
    for row in c.fetchall():
        action = row["preflop_action"]
        notation = row["hand_notation"]
        freq = row["freq"]
        if action not in summary:
            summary[action] = {}
        summary[action][notation] = freq

    conn.close()
    return summary


def get_all_players() -> list[str]:
    """Get list of all players who have shown hands at showdown."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT player FROM player_shown_hands ORDER BY player")
    players = [row["player"] for row in c.fetchall()]
    conn.close()
    return players


def get_hand_count() -> int:
    """Get total number of hands recorded."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM hands")
    count = c.fetchone()["cnt"]
    conn.close()
    return count


def get_recent_showdowns(limit: int = 20) -> list[dict]:
    """Get the most recent showdown records."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT
            h.hand_number,
            s.player,
            s.hand_notation,
            s.card1,
            s.card2,
            s.won,
            h.board,
            h.pot_size,
            h.timestamp
        FROM showdowns s
        JOIN hands h ON s.hand_id = h.hand_id
        ORDER BY h.timestamp DESC
        LIMIT ?
    """, (limit,))
    results = [dict(row) for row in c.fetchall()]
    conn.close()
    return results
