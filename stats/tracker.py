"""Track comprehensive poker statistics for all players across hands.

Metrics tracked per player:
- VPIP%  : Voluntarily Put $ In Pot (didn't fold preflop, excluding BB checks)
- PFR%   : Pre-Flop Raise (raised preflop)
- 3-Bet% : Re-raised a raise preflop
- C-Bet% : Preflop raiser bet the flop
- WTSD%  : Went To ShowDown (of hands played)
- W$SD%  : Won $ at ShowDown (of showdowns reached)

Architecture:
  The tracker uses DEFERRED FINALIZATION. During a live game, each hand is
  polled many times (every ~1s). Rather than processing on the first poll
  (which would capture only blinds), we accumulate the latest data for the
  current hand. When the hand number changes (new hand starts), we FINALIZE
  the previous hand with its most-complete data.

  get_all_stats() returns finalized stats PLUS a live preview of the
  current in-progress hand, so the dashboard always shows something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from observer.state import Street, Card


@dataclass
class PlayerStats:
    # Basic counters
    hands_dealt: int = 0
    hands_voluntarily_played: int = 0  # VPIP: put money in preflop voluntarily
    times_pfr: int = 0  # raised preflop

    # 3-bet tracking
    times_faced_raise: int = 0  # had opportunity to 3-bet
    times_3bet: int = 0  # re-raised a raiser preflop
    times_called_3bet: int = 0  # called after a 3-bet

    # C-bet tracking
    times_could_cbet: int = 0  # was preflop raiser and saw flop
    times_cbet: int = 0  # bet the flop as preflop raiser

    # Open raise / limp
    times_open_raised: int = 0
    times_limped: int = 0

    # Showdown stats
    hands_to_showdown: int = 0
    hands_won_at_showdown: int = 0

    @property
    def vpip(self) -> float:
        return (self.hands_voluntarily_played / self.hands_dealt * 100) if self.hands_dealt > 0 else 0.0

    @property
    def pfr(self) -> float:
        return (self.times_pfr / self.hands_dealt * 100) if self.hands_dealt > 0 else 0.0

    @property
    def three_bet_pct(self) -> float:
        return (self.times_3bet / self.times_faced_raise * 100) if self.times_faced_raise > 0 else 0.0

    @property
    def cbet_pct(self) -> float:
        return (self.times_cbet / self.times_could_cbet * 100) if self.times_could_cbet > 0 else 0.0

    @property
    def wtsd(self) -> float:
        return (self.hands_to_showdown / self.hands_voluntarily_played * 100) if self.hands_voluntarily_played > 0 else 0.0

    @property
    def wssd(self) -> float:
        return (self.hands_won_at_showdown / self.hands_to_showdown * 100) if self.hands_to_showdown > 0 else 0.0


def _street_eq(val, target_str: str) -> bool:
    """Check if a street value matches a target string, handling both enum and str."""
    if val is None:
        return target_str == "preflop"
    if isinstance(val, Street):
        return val.value == target_str
    return str(val).lower().strip() == target_str


class StatsTracker:
    """Accumulates per-player statistics across hands with deferred finalization.

    Instead of locking in stats on the first poll of a hand (when only blinds
    may have been posted), we accumulate the most complete action data
    throughout the hand and only finalize when the hand number changes.
    """

    def __init__(self) -> None:
        self._stats: dict[str, PlayerStats] = {}
        self._finalized_hands: set[int] = set()

        # Current in-progress hand accumulator
        self._current_hand_num: int = 0
        self._pending_players: set[str] = set()
        self._pending_actions: list[dict] = []
        self._pending_showdown: dict[str, list] = {}
        self._pending_winners: dict[str, float] = {}

    def update(
        self,
        hand_number: int,
        players: list[dict],
        actions: list[dict],
        showdown_cards: dict[str, list] | None = None,
        winners: dict[str, float] | None = None,
    ) -> None:
        """Process incoming data each poll cycle.

        Called every ~1s. Accumulates data for the current hand and
        finalizes the previous hand when hand_number changes.
        """
        showdown_cards = showdown_cards or {}
        winners = winners or {}
        player_names = {p["name"] for p in players if p.get("name")}

        # Always ensure every seated player exists in stats (so they show in UI)
        for name in player_names:
            if name not in self._stats:
                self._stats[name] = PlayerStats()

        if hand_number <= 0:
            # No hand number yet — just track players
            return

        # Hand changed → finalize previous, start new
        if hand_number != self._current_hand_num:
            # Finalize the previous hand with accumulated data
            if self._current_hand_num > 0 and self._current_hand_num not in self._finalized_hands:
                self._finalize_hand()

            # Start accumulating for the new hand
            self._current_hand_num = hand_number
            self._pending_players = player_names
            self._pending_actions = list(actions)
            self._pending_showdown = dict(showdown_cards)
            self._pending_winners = dict(winners)
        else:
            # Same hand — update with latest (most complete) data
            # Player list: always use latest
            self._pending_players = player_names

            # Actions: keep whichever list is longer/newer (more complete)
            if len(actions) >= len(self._pending_actions):
                self._pending_actions = list(actions)

            # Showdown/winners: merge (they appear late in the hand)
            if showdown_cards:
                self._pending_showdown.update(showdown_cards)
            if winners:
                self._pending_winners.update(winners)

    def _finalize_hand(self) -> None:
        """Process the completed hand and update permanent stats."""
        self._finalized_hands.add(self._current_hand_num)

        players = self._pending_players
        actions = self._pending_actions
        showdown_cards = self._pending_showdown
        winners = self._pending_winners

        if not players:
            return

        # Separate actions by street
        preflop_actions = [a for a in actions if _street_eq(a.get("street"), "preflop")]
        flop_actions = [a for a in actions if _street_eq(a.get("street"), "flop")]

        # Analyze preflop action sequence
        preflop_analysis = self._analyze_preflop(preflop_actions, players)

        # Analyze flop c-bet
        flop_analysis = self._analyze_flop_cbet(flop_actions, preflop_analysis, preflop_actions)

        # Update each player's permanent stats
        for name in players:
            s = self._stats.setdefault(name, PlayerStats())
            s.hands_dealt += 1

            pa = preflop_analysis.get(name, {})

            if pa.get("vpip"):
                s.hands_voluntarily_played += 1
            if pa.get("raised"):
                s.times_pfr += 1
            if pa.get("faced_raise"):
                s.times_faced_raise += 1
            if pa.get("three_bet"):
                s.times_3bet += 1
            if pa.get("called_3bet"):
                s.times_called_3bet += 1
            if pa.get("open_raised"):
                s.times_open_raised += 1
            if pa.get("limped"):
                s.times_limped += 1

            fa = flop_analysis.get(name, {})
            if fa.get("could_cbet"):
                s.times_could_cbet += 1
            if fa.get("did_cbet"):
                s.times_cbet += 1

            if name in showdown_cards and showdown_cards[name]:
                s.hands_to_showdown += 1
            if name in winners and name in showdown_cards:
                s.hands_won_at_showdown += 1

    def _analyze_preflop(
        self, preflop_actions: list[dict], player_names: set[str]
    ) -> dict[str, dict]:
        """Analyze preflop actions to determine VPIP, PFR, 3-bet, etc."""
        result: dict[str, dict] = {name: {} for name in player_names}

        folders = set()
        raise_count = 0
        first_raiser = None
        actors_who_put_money_in = set()

        for action in preflop_actions:
            player = action.get("player", "")
            atype = action.get("type", "")

            if atype == "fold":
                folders.add(player)
            elif atype in ("raise", "bet"):
                raise_count += 1
                actors_who_put_money_in.add(player)
                if raise_count == 1:
                    first_raiser = player
                    result.setdefault(player, {})["open_raised"] = True
                elif raise_count == 2:
                    result.setdefault(player, {})["three_bet"] = True
                result.setdefault(player, {})["raised"] = True
            elif atype == "call":
                actors_who_put_money_in.add(player)
                if raise_count == 0:
                    result.setdefault(player, {})["limped"] = True
                elif raise_count >= 2:
                    result.setdefault(player, {})["called_3bet"] = True

        # Mark faced_raise for everyone except the first raiser
        if raise_count >= 1:
            for name in player_names:
                if name != first_raiser:
                    result.setdefault(name, {})["faced_raise"] = True

        # VPIP: voluntarily put money in preflop
        for name in player_names:
            if name in actors_who_put_money_in:
                result.setdefault(name, {})["vpip"] = True

        return result

    def _analyze_flop_cbet(
        self, flop_actions: list[dict], preflop_analysis: dict[str, dict],
        preflop_actions: list[dict] | None = None,
    ) -> dict[str, dict]:
        """Analyze flop actions for c-bet tracking."""
        result: dict[str, dict] = {}

        # Find the last preflop raiser (the person who has c-bet opportunity)
        preflop_raiser = None
        if preflop_actions:
            for action in preflop_actions:
                if action.get("type") in ("raise", "bet"):
                    preflop_raiser = action.get("player")
        else:
            for name, info in preflop_analysis.items():
                if info.get("three_bet"):
                    preflop_raiser = name
            if not preflop_raiser:
                for name, info in preflop_analysis.items():
                    if info.get("open_raised"):
                        preflop_raiser = name

        if not preflop_raiser or not flop_actions:
            return result

        result[preflop_raiser] = {"could_cbet": True, "did_cbet": False}

        for action in flop_actions:
            if action.get("player") == preflop_raiser and action.get("type") in ("bet", "raise"):
                result[preflop_raiser]["did_cbet"] = True
                break

        return result

    def _compute_live_preview(self) -> dict[str, dict]:
        """Compute stats for the current in-progress hand (not yet finalized).

        Returns a dict keyed by player name with their contribution from the
        current hand only. This is merged into get_all_stats() output so
        the dashboard shows responsive data during a hand.
        """
        if self._current_hand_num <= 0 or not self._pending_players:
            return {}
        if self._current_hand_num in self._finalized_hands:
            return {}

        actions = self._pending_actions
        showdown_cards = self._pending_showdown
        winners = self._pending_winners
        players = self._pending_players

        preflop_actions = [a for a in actions if _street_eq(a.get("street"), "preflop")]
        flop_actions = [a for a in actions if _street_eq(a.get("street"), "flop")]

        preflop_analysis = self._analyze_preflop(preflop_actions, players)
        flop_analysis = self._analyze_flop_cbet(flop_actions, preflop_analysis, preflop_actions)

        preview: dict[str, dict] = {}
        for name in players:
            pa = preflop_analysis.get(name, {})
            fa = flop_analysis.get(name, {})
            preview[name] = {
                "vpip": pa.get("vpip", False),
                "raised": pa.get("raised", False),
                "faced_raise": pa.get("faced_raise", False),
                "three_bet": pa.get("three_bet", False),
                "called_3bet": pa.get("called_3bet", False),
                "open_raised": pa.get("open_raised", False),
                "limped": pa.get("limped", False),
                "could_cbet": fa.get("could_cbet", False),
                "did_cbet": fa.get("did_cbet", False),
                "showdown": name in showdown_cards and bool(showdown_cards[name]),
                "won_showdown": name in winners and name in showdown_cards,
            }
        return preview

    def get_all_stats(self) -> dict[str, dict]:
        """Return stats dict suitable for JSON serialization.

        Includes finalized stats PLUS a live preview of the current hand
        so that the dashboard shows responsive, up-to-date information.
        """
        # Compute live preview for current in-progress hand
        preview = self._compute_live_preview()

        result = {}
        for name, s in self._stats.items():
            # Start with finalized counts
            hands = s.hands_dealt
            vol_played = s.hands_voluntarily_played
            pfr_count = s.times_pfr
            faced = s.times_faced_raise
            three_bet_count = s.times_3bet
            could_cbet = s.times_could_cbet
            did_cbet = s.times_cbet
            showdowns = s.hands_to_showdown
            won_sd = s.hands_won_at_showdown

            # Add current hand's contribution if it hasn't been finalized
            if name in preview:
                p = preview[name]
                hands += 1
                if p["vpip"]:
                    vol_played += 1
                if p["raised"]:
                    pfr_count += 1
                if p["faced_raise"]:
                    faced += 1
                if p["three_bet"]:
                    three_bet_count += 1
                if p["could_cbet"]:
                    could_cbet += 1
                if p["did_cbet"]:
                    did_cbet += 1
                if p["showdown"]:
                    showdowns += 1
                if p["won_showdown"]:
                    won_sd += 1

            vpip_pct = (vol_played / hands * 100) if hands > 0 else 0.0
            pfr_pct = (pfr_count / hands * 100) if hands > 0 else 0.0
            three_bet_pct = (three_bet_count / faced * 100) if faced > 0 else 0.0
            cbet_pct = (did_cbet / could_cbet * 100) if could_cbet > 0 else 0.0
            wtsd_pct = (showdowns / vol_played * 100) if vol_played > 0 else 0.0
            wssd_pct = (won_sd / showdowns * 100) if showdowns > 0 else 0.0

            result[name] = {
                "hands": hands,
                "vpip": round(vpip_pct, 1),
                "pfr": round(pfr_pct, 1),
                "three_bet_pct": round(three_bet_pct, 1),
                "cbet_pct": round(cbet_pct, 1),
                "wtsd": round(wtsd_pct, 1),
                "wssd": round(wssd_pct, 1),
                # Legacy field
                "raise_pct": round(pfr_pct, 1),
            }

        # Also include players who are in the current hand but have
        # no finalized stats yet (brand new players at the table)
        for name in preview:
            if name not in result:
                p = preview[name]
                vpip_pct = 100.0 if p["vpip"] else 0.0
                pfr_pct = 100.0 if p["raised"] else 0.0
                result[name] = {
                    "hands": 1,
                    "vpip": round(vpip_pct, 1),
                    "pfr": round(pfr_pct, 1),
                    "three_bet_pct": 0.0,
                    "cbet_pct": 0.0,
                    "wtsd": 0.0,
                    "wssd": 0.0,
                    "raise_pct": round(pfr_pct, 1),
                }

        return result
