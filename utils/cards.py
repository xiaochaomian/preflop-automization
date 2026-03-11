"""Card and deck representations and utilities."""

from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "hdcs"  # hearts, diamonds, clubs, spades

RANK_VALUES = {r: i for i, r in enumerate(RANKS, 2)}

SUIT_SYMBOLS = {"h": "\u2665", "d": "\u2666", "c": "\u2663", "s": "\u2660"}
SUIT_COLORS = {"h": "red", "d": "red", "c": "white", "s": "white"}


def card_to_notation(rank: str, suit: str) -> str:
    """Convert rank+suit to standard two-char notation like 'Ah', 'Ts'."""
    return f"{rank}{suit}"


def hand_to_category(card1_rank: str, card1_suit: str, card2_rank: str, card2_suit: str) -> str:
    """Convert two hole cards into standard hand notation (e.g. 'AKs', 'TT', 'Q9o').

    Always puts the higher rank first.
    """
    v1 = RANK_VALUES[card1_rank]
    v2 = RANK_VALUES[card2_rank]

    if v1 < v2:
        card1_rank, card2_rank = card2_rank, card1_rank
        card1_suit, card2_suit = card2_suit, card1_suit

    if card1_rank == card2_rank:
        return f"{card1_rank}{card2_rank}"
    elif card1_suit == card2_suit:
        return f"{card1_rank}{card2_rank}s"
    else:
        return f"{card1_rank}{card2_rank}o"


def pretty_card(rank: str, suit: str) -> str:
    """Return a card string with suit symbol, e.g. 'A♠'."""
    return f"{rank}{SUIT_SYMBOLS.get(suit, suit)}"
