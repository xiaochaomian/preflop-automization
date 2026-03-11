"""Top-level decision engine combining preflop and postflop."""

from __future__ import annotations

from observer.state import GameState, Street
from engine.preflop import get_preflop_action
from engine.postflop import get_postflop_action
from engine.hand_evaluator import estimate_equity, classify_hand


def get_recommendation(state: GameState) -> dict:
    """Get a full recommendation for the current game state.

    Returns:
        {
            "action": str,
            "amount": float,
            "confidence": float,
            "reasoning": str,
            "equity": float,
            "hand_category": str,
        }
    """
    if len(state.my_cards) != 2:
        return {
            "action": "wait",
            "amount": 0,
            "confidence": 0,
            "reasoning": "No cards dealt yet. Waiting for next hand.",
            "equity": 0,
            "hand_category": "N/A",
        }

    # Preflop
    if state.street == Street.PREFLOP:
        result = get_preflop_action(state)
        # Estimate preflop equity vs 1 opponent
        equity = estimate_equity(state.my_cards, [], num_opponents=1, simulations=1000)
        hand_cat = f"{state.my_cards[0]}{state.my_cards[1]}"

        confidence = 0.7  # preflop ranges are well-defined
        if result["action"] == "fold":
            confidence = 0.8
        elif result["action"] == "raise":
            confidence = 0.75

        return {
            "action": result["action"],
            "amount": result["amount"],
            "confidence": confidence,
            "reasoning": result["reasoning"],
            "equity": equity,
            "hand_category": hand_cat,
        }

    # Postflop
    num_opps = max(1, state.active_players - 1)
    equity = estimate_equity(
        state.my_cards,
        state.community_cards,
        num_opponents=num_opps,
        simulations=2000,
    )
    hand_cat = classify_hand(state.my_cards, state.community_cards)
    result = get_postflop_action(state, equity, hand_cat)

    # Confidence: higher when equity is clearly strong or weak
    if equity > 0.75 or equity < 0.20:
        confidence = 0.8
    elif equity > 0.55 or equity < 0.30:
        confidence = 0.6
    else:
        confidence = 0.4

    return {
        "action": result["action"],
        "amount": result["amount"],
        "confidence": confidence,
        "reasoning": result["reasoning"],
        "equity": equity,
        "hand_category": hand_cat,
    }
