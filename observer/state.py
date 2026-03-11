"""Game state model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Street(Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class Position(Enum):
    BTN = "BTN"
    SB = "SB"
    BB = "BB"
    UTG = "UTG"
    UTG1 = "UTG+1"
    MP = "MP"
    MP1 = "MP+1"
    HJ = "HJ"
    CO = "CO"


# Position order clockwise from the dealer for different table sizes.
POSITION_ORDER_6MAX = [Position.BTN, Position.SB, Position.BB, Position.UTG, Position.HJ, Position.CO]
POSITION_ORDER_9MAX = [
    Position.BTN, Position.SB, Position.BB,
    Position.UTG, Position.UTG1, Position.MP, Position.MP1,
    Position.HJ, Position.CO,
]


def positions_for_table(num_players: int) -> list[Position]:
    """Return the position labels for a given table size (2-9 players)."""
    if num_players <= 2:
        return [Position.BTN, Position.BB]
    if num_players == 3:
        return [Position.BTN, Position.SB, Position.BB]
    if num_players <= 6:
        return POSITION_ORDER_6MAX[:num_players]
    return POSITION_ORDER_9MAX[:num_players]


@dataclass
class Card:
    rank: str  # "2"-"9", "T", "J", "Q", "K", "A"
    suit: str  # "h", "d", "c", "s"

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"


@dataclass
class PlayerInfo:
    name: str
    stack: float
    position: Position
    is_active: bool  # still in hand
    current_bet: float = 0.0


@dataclass
class Action:
    player: str
    type: str  # "fold", "check", "call", "bet", "raise"
    amount: float = 0.0
    street: Street = Street.PREFLOP  # which street this action occurred on

    def __str__(self) -> str:
        if self.type in ("fold", "check"):
            return f"{self.player} {self.type}s"
        return f"{self.player} {self.type}s {self.amount}"


@dataclass
class GameState:
    # My info
    my_cards: list[Card] = field(default_factory=list)
    my_name: str = ""
    my_stack: float = 0.0
    my_position: Position = Position.BB

    # Table info
    community_cards: list[Card] = field(default_factory=list)
    pot: float = 0.0
    street: Street = Street.PREFLOP
    num_players: int = 0
    players: list[PlayerInfo] = field(default_factory=list)

    # Action info
    current_bet: float = 0.0  # amount to call
    min_raise: float = 0.0
    action_history: list[Action] = field(default_factory=list)

    # Meta
    hand_number: int = 0
    big_blind: float = 0.0
    small_blind: float = 0.0

    @property
    def spr(self) -> float:
        """Stack-to-pot ratio."""
        if self.pot == 0:
            return float("inf")
        return self.my_stack / self.pot

    @property
    def active_players(self) -> int:
        return sum(1 for p in self.players if p.is_active)

    @property
    def is_my_turn(self) -> bool:
        """Heuristic: we have cards and there's a bet to act on or we're in an active hand."""
        return len(self.my_cards) == 2
