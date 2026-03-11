"""Postflop heuristics for GTO-ish play."""

from __future__ import annotations

from observer.state import Card, GameState, Position


def classify_board(cards: list[Card]) -> str:
    """Classify board texture as 'dry', 'semi_wet', or 'wet'.

    Dry: no flush draws, no straight draws, unpaired, widely spread
    Semi-wet: one draw present
    Wet: multiple draws, connected, two-tone or monotone
    """
    if len(cards) < 3:
        return "dry"

    suits = [c.suit for c in cards]
    rank_values = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
                   "8": 8, "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
    ranks = sorted([rank_values[c.rank] for c in cards])

    wetness = 0

    # Flush draw check: 2+ cards of the same suit
    from collections import Counter
    suit_counts = Counter(suits)
    max_suit = max(suit_counts.values())
    if max_suit >= 3:
        wetness += 2  # monotone or flush possible
    elif max_suit == 2:
        wetness += 1  # flush draw possible (two-tone)

    # Straight draw check: look for connectedness
    # Count how many gaps of 1-2 exist between consecutive cards
    connections = 0
    for i in range(len(ranks) - 1):
        gap = ranks[i + 1] - ranks[i]
        if gap <= 2:
            connections += 1

    if connections >= 2:
        wetness += 2
    elif connections == 1:
        wetness += 1

    # Paired board
    rank_counts = Counter(ranks)
    if max(rank_counts.values()) >= 2:
        wetness -= 1  # paired boards are slightly drier

    if wetness >= 3:
        return "wet"
    elif wetness >= 1:
        return "semi_wet"
    return "dry"


def is_in_position(state: GameState) -> bool:
    """Check if we're in position (act last) relative to remaining active players."""
    pos_order = [Position.SB, Position.BB, Position.UTG, Position.UTG1,
                 Position.MP, Position.MP1, Position.HJ, Position.CO, Position.BTN]
    my_idx = pos_order.index(state.my_position) if state.my_position in pos_order else 0
    for p in state.players:
        if p.is_active and p.name != state.my_name:
            p_idx = pos_order.index(p.position) if p.position in pos_order else 0
            if p_idx > my_idx:
                return False
    return True


def get_postflop_action(state: GameState, equity: float, hand_desc: str) -> dict:
    """Determine postflop action based on equity and board texture.

    Returns:
        {
            "action": "fold" | "check" | "call" | "bet" | "raise",
            "amount": float,
            "reasoning": str,
        }
    """
    pot = state.pot or 1
    to_call = state.current_bet
    spr = state.spr
    board_type = classify_board(state.community_cards)
    in_pos = is_in_position(state)
    num_active = state.active_players
    multiway = num_active > 2

    # Pot odds
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

    # Adjust equity threshold for multiway
    equity_adj = equity
    if multiway:
        equity_adj *= 0.85  # discount equity multiway

    # Strong hands (equity > 0.70)
    if equity_adj > 0.70:
        if to_call > 0:
            # Facing a bet with a strong hand: raise for value
            raise_amt = pot * 0.75
            return {
                "action": "raise",
                "amount": round(to_call + raise_amt, 0),
                "reasoning": (
                    f"{hand_desc} with {equity:.0%} equity. Strong hand, raise for value. "
                    f"Board: {board_type}."
                ),
            }
        # No bet to face: bet for value
        if board_type == "dry":
            bet_size = round(pot * 0.33, 0)
        else:
            bet_size = round(pot * 0.67, 0)
        return {
            "action": "bet",
            "amount": bet_size,
            "reasoning": (
                f"{hand_desc} with {equity:.0%} equity. Bet for value. "
                f"Board: {board_type}, sizing {'small on dry' if board_type == 'dry' else 'larger on wet'}."
            ),
        }

    # Medium hands (equity 0.40-0.70)
    if equity_adj > 0.40:
        if to_call > 0:
            if equity > pot_odds:
                return {
                    "action": "call",
                    "amount": to_call,
                    "reasoning": (
                        f"{hand_desc} with {equity:.0%} equity. "
                        f"Pot odds: {pot_odds:.0%}. Equity > pot odds, call."
                    ),
                }
            else:
                return {
                    "action": "fold",
                    "amount": 0,
                    "reasoning": (
                        f"{hand_desc} with {equity:.0%} equity. "
                        f"Pot odds: {pot_odds:.0%}. Not getting right price, fold."
                    ),
                }
        # No bet: check or small bet in position
        if in_pos and not multiway and board_type in ("dry", "semi_wet"):
            bet_size = round(pot * 0.33, 0)
            return {
                "action": "bet",
                "amount": bet_size,
                "reasoning": (
                    f"{hand_desc} with {equity:.0%} equity. "
                    f"In position on {board_type} board, small bet."
                ),
            }
        return {
            "action": "check",
            "amount": 0,
            "reasoning": (
                f"{hand_desc} with {equity:.0%} equity. Medium strength, check."
            ),
        }

    # Weak hands (equity < 0.40)
    if to_call > 0:
        # Check if we're getting amazing pot odds
        if pot_odds < 0.20 and equity > 0.15:
            return {
                "action": "call",
                "amount": to_call,
                "reasoning": (
                    f"{hand_desc} with {equity:.0%} equity. "
                    f"Great pot odds ({pot_odds:.0%}), cheap call."
                ),
            }
        return {
            "action": "fold",
            "amount": 0,
            "reasoning": (
                f"{hand_desc} with {equity:.0%} equity. Weak hand, fold."
            ),
        }

    # No bet and weak hand: check
    return {
        "action": "check",
        "amount": 0,
        "reasoning": (
            f"{hand_desc} with {equity:.0%} equity. Weak hand, check."
        ),
    }
