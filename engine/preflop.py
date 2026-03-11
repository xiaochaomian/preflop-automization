"""Preflop GTO ranges for 6-max poker."""

from __future__ import annotations

from observer.state import Position, GameState, Action
from utils.cards import hand_to_category

# RFI (Raise First In) ranges by position
RFI_RANGES: dict[Position, set[str]] = {
    Position.UTG: {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
        "AKs", "AQs", "AJs", "ATs", "A5s", "A4s",
        "KQs", "KJs", "KTs",
        "QJs", "QTs",
        "JTs",
        "T9s",
        "98s",
        "87s",
        "AKo", "AQo",
    },
    Position.HJ: {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66",
        "AKs", "AQs", "AJs", "ATs", "A9s", "A5s", "A4s", "A3s",
        "KQs", "KJs", "KTs", "K9s",
        "QJs", "QTs", "Q9s",
        "JTs", "J9s",
        "T9s", "T8s",
        "98s", "97s",
        "87s", "86s",
        "76s",
        "65s",
        "AKo", "AQo", "AJo",
        "KQo",
    },
    Position.CO: {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55",
        "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
        "KQs", "KJs", "KTs", "K9s", "K8s",
        "QJs", "QTs", "Q9s", "Q8s",
        "JTs", "J9s", "J8s",
        "T9s", "T8s",
        "98s", "97s",
        "87s", "86s",
        "76s", "75s",
        "65s", "64s",
        "54s",
        "AKo", "AQo", "AJo", "ATo",
        "KQo", "KJo",
        "QJo",
    },
    Position.BTN: {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
        "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
        "KQs", "KJs", "KTs", "K9s", "K8s", "K7s", "K6s", "K5s",
        "QJs", "QTs", "Q9s", "Q8s", "Q7s",
        "JTs", "J9s", "J8s", "J7s",
        "T9s", "T8s", "T7s",
        "98s", "97s", "96s",
        "87s", "86s", "85s",
        "76s", "75s",
        "65s", "64s",
        "54s", "53s",
        "43s",
        "AKo", "AQo", "AJo", "ATo", "A9o",
        "KQo", "KJo", "KTo",
        "QJo", "QTo",
        "JTo",
        "T9o",
    },
    Position.SB: {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
        "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
        "KQs", "KJs", "KTs", "K9s", "K8s", "K7s", "K6s",
        "QJs", "QTs", "Q9s", "Q8s",
        "JTs", "J9s", "J8s",
        "T9s", "T8s",
        "98s", "97s",
        "87s", "86s",
        "76s", "75s",
        "65s", "64s",
        "54s",
        "AKo", "AQo", "AJo", "ATo", "A9o",
        "KQo", "KJo", "KTo",
        "QJo", "QTo",
        "JTo",
    },
}

# 3-bet ranges (custom)
# Pocket pairs 88-AA, plus premium suited hands
THREEBET_RANGE = {
    "AA", "KK", "QQ", "JJ", "TT", "99", "88",
    "AKs", "AQs", "AJs", "KQs", "ATs", "A5s", "JTs", "T9s",
}

# BB defense vs open (wide)
BB_DEFEND = {
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
    "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
    "KQs", "KJs", "KTs", "K9s", "K8s", "K7s", "K6s", "K5s", "K4s",
    "QJs", "QTs", "Q9s", "Q8s", "Q7s", "Q6s",
    "JTs", "J9s", "J8s", "J7s",
    "T9s", "T8s", "T7s",
    "98s", "97s", "96s",
    "87s", "86s", "85s",
    "76s", "75s",
    "65s", "64s",
    "54s", "53s",
    "43s",
    "AKo", "AQo", "AJo", "ATo", "A9o", "A8o",
    "KQo", "KJo", "KTo", "K9o",
    "QJo", "QTo", "Q9o",
    "JTo", "J9o",
    "T9o",
}


def _is_unopened(actions: list[Action]) -> bool:
    """Check if the pot is unopened (no raise/bet yet, only folds/checks/blinds)."""
    for a in actions:
        if a.type in ("raise", "bet"):
            return False
    return True


def _has_single_raise(actions: list[Action]) -> bool:
    """Check if there's exactly one raise so far."""
    raise_count = sum(1 for a in actions if a.type in ("raise", "bet"))
    return raise_count == 1


def get_preflop_action(state: GameState) -> dict:
    """Determine the preflop action based on GTO ranges.

    Returns:
        {
            "action": "fold" | "call" | "raise",
            "amount": float,
            "reasoning": str,
        }
    """
    if len(state.my_cards) != 2:
        return {"action": "fold", "amount": 0, "reasoning": "No cards dealt."}

    c1, c2 = state.my_cards
    hand = hand_to_category(c1.rank, c1.suit, c2.rank, c2.suit)
    pos = state.my_position
    bb = state.big_blind or 10

    # Unopened pot: check RFI range
    if _is_unopened(state.action_history):
        rfi = RFI_RANGES.get(pos, RFI_RANGES[Position.UTG])
        if hand in rfi:
            open_size = 3 * bb
            return {
                "action": "raise",
                "amount": open_size,
                "reasoning": f"{hand} is in {pos.value} RFI range. Open raise to {open_size}.",
            }
        # BB can check
        if pos == Position.BB:
            return {
                "action": "check",
                "amount": 0,
                "reasoning": f"{hand} not in raise range. Check from BB.",
            }
        return {
            "action": "fold",
            "amount": 0,
            "reasoning": f"{hand} is not in {pos.value} RFI range. Fold.",
        }

    # Facing a single raise: consider 3-bet or call
    if _has_single_raise(state.action_history):
        if hand in THREEBET_RANGE:
            three_bet_size = state.current_bet * 3
            return {
                "action": "raise",
                "amount": three_bet_size,
                "reasoning": f"{hand} is in 3-bet range. 3-bet to {three_bet_size}.",
            }
        # BB defense
        if pos == Position.BB and hand in BB_DEFEND:
            return {
                "action": "call",
                "amount": state.current_bet,
                "reasoning": f"{hand} is in BB defend range. Call {state.current_bet}.",
            }
        # General calling range: use RFI range as proxy
        rfi = RFI_RANGES.get(pos, set())
        if hand in rfi:
            return {
                "action": "call",
                "amount": state.current_bet,
                "reasoning": f"{hand} is playable from {pos.value}. Call {state.current_bet}.",
            }
        return {
            "action": "fold",
            "amount": 0,
            "reasoning": f"{hand} is not strong enough to continue vs a raise. Fold.",
        }

    # Facing a 3-bet or more: only continue with premiums
    if hand in THREEBET_RANGE:
        return {
            "action": "call",
            "amount": state.current_bet,
            "reasoning": f"{hand} is strong enough to call a 3-bet. Call {state.current_bet}.",
        }

    return {
        "action": "fold",
        "amount": 0,
        "reasoning": f"{hand} is not strong enough vs multiple raises. Fold.",
    }
