"""Hand strength evaluation using treys library + Monte Carlo equity."""

from __future__ import annotations

import random
from treys import Card as TreysCard, Evaluator, Deck

from observer.state import Card, GameState

_evaluator = Evaluator()

HAND_CLASS_NAMES = {
    1: "Straight Flush",
    2: "Four of a Kind",
    3: "Full House",
    4: "Flush",
    5: "Straight",
    6: "Three of a Kind",
    7: "Two Pair",
    8: "One Pair",
    9: "High Card",
}


def card_to_treys(card: Card) -> int:
    """Convert our Card to a treys int representation."""
    rank = card.rank
    suit = card.suit
    return TreysCard.new(f"{rank}{suit}")


def cards_to_treys(cards: list[Card]) -> list[int]:
    return [card_to_treys(c) for c in cards]


def evaluate_hand(hole_cards: list[Card], board: list[Card]) -> int:
    """Return treys hand rank (lower is better, 1 = royal flush)."""
    if len(board) < 3:
        return 7462  # worst possible rank
    t_hole = cards_to_treys(hole_cards)
    t_board = cards_to_treys(board)
    return _evaluator.evaluate(t_board, t_hole)


def hand_rank_class(hole_cards: list[Card], board: list[Card]) -> str:
    """Return human-readable hand category like 'One Pair', 'Flush'."""
    if len(board) < 3:
        return "No board"
    rank = evaluate_hand(hole_cards, board)
    class_int = _evaluator.get_rank_class(rank)
    return HAND_CLASS_NAMES.get(class_int, "Unknown")


def estimate_equity(
    hole_cards: list[Card],
    board: list[Card],
    num_opponents: int = 1,
    simulations: int = 2000,
) -> float:
    """Monte Carlo equity estimation.

    Deals random opponent hands and remaining board cards,
    returns win probability (0.0 to 1.0).
    """
    if len(hole_cards) != 2:
        return 0.0

    t_hole = cards_to_treys(hole_cards)
    t_board = cards_to_treys(board)
    dead = set(t_hole + t_board)

    # Build the remaining deck
    full_deck = Deck.GetFullDeck()
    remaining = [c for c in full_deck if c not in dead]

    wins = 0
    ties = 0

    for _ in range(simulations):
        random.shuffle(remaining)
        idx = 0

        # Deal opponent hands
        opp_hands = []
        for _ in range(num_opponents):
            if idx + 1 >= len(remaining):
                break
            opp_hands.append([remaining[idx], remaining[idx + 1]])
            idx += 2

        # Deal remaining board cards
        cards_needed = 5 - len(t_board)
        sim_board = t_board + remaining[idx: idx + cards_needed]

        if len(sim_board) < 5:
            continue

        my_rank = _evaluator.evaluate(sim_board, t_hole)

        best_opp = 7463
        for oh in opp_hands:
            opp_rank = _evaluator.evaluate(sim_board, oh)
            best_opp = min(best_opp, opp_rank)

        if my_rank < best_opp:
            wins += 1
        elif my_rank == best_opp:
            ties += 1

    total = simulations
    if total == 0:
        return 0.5
    return (wins + ties * 0.5) / total


def classify_hand(hole_cards: list[Card], board: list[Card]) -> str:
    """Give a human-readable description of our holding relative to the board."""
    if len(board) < 3 or len(hole_cards) != 2:
        return "Preflop"

    hand_class = hand_rank_class(hole_cards, board)

    # Additional context
    board_ranks = [c.rank for c in board]
    my_ranks = [c.rank for c in hole_cards]

    rank_values = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
                   "8": 8, "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}

    top_board = max(rank_values[r] for r in board_ranks)
    my_high = max(rank_values[r] for r in my_ranks)

    if hand_class == "One Pair":
        # Is it top pair, middle pair, overpair, etc.?
        if my_high > top_board:
            return "Overpair"
        for r in my_ranks:
            if rank_values[r] == top_board:
                return "Top Pair"
        return "Pair"

    if hand_class == "High Card":
        if my_high > top_board:
            return "Overcards"
        return "High Card"

    return hand_class
