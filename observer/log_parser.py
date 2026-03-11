"""Parse PokerNow's text-based game log."""

from __future__ import annotations

import re
from observer.state import Action, Card, Street


def parse_card(text: str) -> Card | None:
    """Parse a card string like 'Ah', '10s', 'Td' into a Card."""
    text = text.strip()
    if not text:
        return None
    # PokerNow may use '10' instead of 'T'
    if text.startswith("10"):
        return Card(rank="T", suit=text[2].lower())
    if len(text) >= 2:
        rank = text[0].upper()
        suit = text[1].lower()
        if rank in "23456789TJQKA" and suit in "hdcs":
            return Card(rank=rank, suit=suit)
    return None


def parse_cards_from_text(text: str) -> list[Card]:
    """Extract cards from text like '[Ah, 7c, 2d]' or 'Ah 7c 2d'."""
    # Try bracket notation first
    bracket_match = re.search(r"\[([^\]]+)\]", text)
    if bracket_match:
        card_strs = bracket_match.group(1).split(",")
    else:
        card_strs = re.findall(r"[2-9TJQKA10][hdcsHDCS♥♦♣♠]", text)
        if not card_strs:
            return []
        return [c for s in card_strs if (c := parse_card(s)) is not None]

    return [c for s in card_strs if (c := parse_card(s.strip())) is not None]


def _clean_player_name(name: str) -> str:
    """Strip quotes and whitespace from a captured player name."""
    return name.strip().strip('"').strip()


def parse_action_line(line: str) -> Action | None:
    """Parse a single log line into an Action.

    Examples:
        '"Player1" folds'
        '"Player1" checks'
        '"Player1" calls 200'
        '"Player1" bets 200'
        '"Player1" raises to 400'
    """
    line = line.strip()

    # Fold
    m = re.match(r"(.+?)\s+folds", line)
    if m:
        return Action(player=_clean_player_name(m.group(1)), type="fold")

    # Check
    m = re.match(r"(.+?)\s+checks", line)
    if m:
        return Action(player=_clean_player_name(m.group(1)), type="check")

    # Call
    m = re.match(r"(.+?)\s+calls\s+([\d,.]+)", line)
    if m:
        return Action(player=_clean_player_name(m.group(1)), type="call", amount=_parse_amount(m.group(2)))

    # Raise
    m = re.match(r"(.+?)\s+raises\s+to\s+([\d,.]+)", line)
    if m:
        return Action(player=_clean_player_name(m.group(1)), type="raise", amount=_parse_amount(m.group(2)))

    # Bet
    m = re.match(r"(.+?)\s+bets\s+([\d,.]+)", line)
    if m:
        return Action(player=_clean_player_name(m.group(1)), type="bet", amount=_parse_amount(m.group(2)))

    return None


def is_hand_start(line: str) -> bool:
    """Check if a log line indicates the start of a new hand."""
    return bool(re.search(r"--\s*starting hand\s*#?\d*\s*--", line, re.IGNORECASE))


def parse_hand_number(line: str) -> int | None:
    m = re.search(r"hand\s*#?(\d+)", line, re.IGNORECASE)
    return int(m.group(1)) if m else None


def is_flop_marker(line: str) -> bool:
    """Check if line indicates flop was dealt."""
    return bool(re.search(r"flop\s*(?:\(.*?\))?\s*:?\s*\[", line, re.IGNORECASE))


def is_turn_marker(line: str) -> bool:
    """Check if line indicates turn was dealt."""
    return bool(re.search(r"turn\s*(?:\(.*?\))?\s*:?\s*\[", line, re.IGNORECASE))


def is_river_marker(line: str) -> bool:
    """Check if line indicates river was dealt."""
    return bool(re.search(r"river\s*(?:\(.*?\))?\s*:?\s*\[", line, re.IGNORECASE))


def is_showdown_reveal(line: str) -> bool:
    """Check if line indicates a player showed their cards at showdown."""
    return bool(re.search(r'shows\s*a?\s*hand|shows\s*\[|revealed\s*\[', line, re.IGNORECASE))


def parse_showdown_line(line: str) -> tuple[str, list[Card]] | None:
    """Parse a showdown reveal line to extract player name and cards.

    PokerNow formats:
        '"PlayerName" shows a hand [Ah, Kd]'
        'PlayerName shows [Ah, Kd]'
        '"PlayerName" revealed [Ah, Kd]'
    """
    # Try quoted player name first
    m = re.search(r'"([^"]+)"\s+(?:shows|revealed)\s+(?:a\s+hand\s*)?\[([^\]]+)\]', line, re.IGNORECASE)
    if m:
        player = m.group(1).strip()
        cards = parse_cards_from_text(f"[{m.group(2)}]")
        if len(cards) == 2:
            return (player, cards)

    # Try unquoted player name
    m = re.search(r'(.+?)\s+(?:shows|revealed)\s+(?:a\s+hand\s*)?\[([^\]]+)\]', line, re.IGNORECASE)
    if m:
        player = m.group(1).strip().strip('"')
        cards = parse_cards_from_text(f"[{m.group(2)}]")
        if len(cards) == 2:
            return (player, cards)

    return None


def parse_winner_line(line: str) -> tuple[str, float] | None:
    """Parse a line indicating who won the pot.

    PokerNow formats:
        '"PlayerName" collected 1200 from pot'
        'PlayerName wins 1200'
    """
    m = re.search(r'"([^"]+)"\s+collected\s+([\d,.]+)', line, re.IGNORECASE)
    if m:
        return (m.group(1).strip(), _parse_amount(m.group(2)))

    m = re.search(r'(.+?)\s+(?:collected|wins)\s+([\d,.]+)', line, re.IGNORECASE)
    if m:
        return (m.group(1).strip().strip('"'), _parse_amount(m.group(2)))

    return None


def parse_actions_with_streets(lines: list[str]) -> list[Action]:
    """Parse action history from log lines, tagging each action with its street.

    Detects flop/turn/river markers in the log to assign the correct street
    to each action.
    """
    actions: list[Action] = []
    current_street = Street.PREFLOP

    for line in lines:
        # Check for street transitions
        if is_flop_marker(line):
            current_street = Street.FLOP
            continue
        elif is_turn_marker(line):
            current_street = Street.TURN
            continue
        elif is_river_marker(line):
            current_street = Street.RIVER
            continue

        # Skip showdown/winner lines
        if is_showdown_reveal(line):
            continue

        # Parse action and tag with current street
        action = parse_action_line(line)
        if action:
            action.street = current_street
            actions.append(action)

    return actions


def parse_board_from_log(lines: list[str]) -> list[Card]:
    """Parse community cards from game log lines.

    PokerNow log format:
        Flop:  [Ah, 7c, 2d]
        Turn:  [Ah, 7c, 2d, Ks]
        River: [Ah, 7c, 2d, Ks, 3h]
    """
    board: list[Card] = []
    for line in reversed(lines):
        # Match flop/turn/river lines with bracket notation
        m = re.search(r"(?:flop|turn|river)\s*(?:\(.*?\))?\s*:?\s*\[([^\]]+)\]", line, re.IGNORECASE)
        if m:
            board = parse_cards_from_text(m.group(0))
            if board:
                return board
        # Also match: "Board: Ah 7c 2d"
        m = re.search(r"board\s*:?\s*\[([^\]]+)\]", line, re.IGNORECASE)
        if m:
            board = parse_cards_from_text(m.group(0))
            if board:
                return board
    return board


def _parse_amount(text: str) -> float:
    return float(text.replace(",", ""))


def extract_hand_data(lines: list[str]) -> dict:
    """Extract comprehensive hand data from log lines for a single hand.

    Returns a dict with:
        - actions: list of Actions with street tags
        - showdown_cards: {player_name: [Card, Card]}
        - winners: {player_name: amount_won}
        - board: [Card, ...]
    """
    actions = parse_actions_with_streets(lines)
    board = parse_board_from_log(lines)

    showdown_cards: dict[str, list[Card]] = {}
    winners: dict[str, float] = {}

    for line in lines:
        # Parse showdown reveals
        result = parse_showdown_line(line)
        if result:
            player, cards = result
            showdown_cards[player] = cards

        # Parse winners
        winner = parse_winner_line(line)
        if winner:
            player, amount = winner
            winners[player] = winners.get(player, 0) + amount

    return {
        "actions": actions,
        "showdown_cards": showdown_cards,
        "winners": winners,
        "board": board,
    }
