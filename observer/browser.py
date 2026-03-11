"""Playwright browser connection and DOM scraping for PokerNow."""

from __future__ import annotations

import re
from playwright.async_api import Page, Browser, async_playwright, Playwright

from observer.state import (
    GameState, Card, PlayerInfo, Action, Street, Position,
    positions_for_table,
)
from observer.log_parser import (
    parse_action_line, is_hand_start, parse_hand_number,
    parse_board_from_log, parse_actions_with_streets,
    parse_showdown_line, parse_winner_line, extract_hand_data,
)
import config


class PokerNowObserver:
    """Scrapes PokerNow DOM to build a GameState."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None
        self._debug_log: list[str] = []
        self._current_hand_lines: list[str] = []  # raw log lines for current hand
        self._last_hand_data: dict | None = None  # parsed hand data (actions, showdowns, etc.)

    async def launch(self, url: str, headless: bool = False) -> Page:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=headless)
        context = await self._browser.new_context()
        self.page = await context.new_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        return self.page

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def get_game_state(self) -> GameState:
        """Scrape the current game state from the PokerNow page."""
        if not self.page:
            return GameState()

        state = GameState(
            my_name=config.PLAYER_NAME,
            big_blind=config.BIG_BLIND,
            small_blind=config.SMALL_BLIND,
        )
        self._debug_log = []

        data = await self.page.evaluate(r"""() => {
            const result = { debug: [] };

            const RANK_MAP = {'A':'A','K':'K','Q':'Q','J':'J','T':'T','10':'T',
                '2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9'};

            function extractCardFromContainer(container) {
                const cls = container.className || '';
                const rankMatch = cls.match(/card-s-(\w+)/);
                const suitMatch = cls.match(/(?:^|\s)card-([hcds])(?:\s|$)/);
                let rank = null, suit = null;
                if (rankMatch) {
                    const r = rankMatch[1];
                    rank = RANK_MAP[r] || RANK_MAP[r.toUpperCase()] || null;
                }
                if (suitMatch) suit = suitMatch[1];
                if (rank && suit) return { rank, suit, source: 'container-class' };

                const cardDiv = container.querySelector('.card');
                if (cardDiv) {
                    const valueEl = cardDiv.querySelector('.value');
                    const suitEl = cardDiv.querySelector('.suit');
                    if (valueEl && suitEl) {
                        const r = (valueEl.textContent || '').trim();
                        const s = (suitEl.textContent || '').trim();
                        rank = RANK_MAP[r] || RANK_MAP[r.toUpperCase()] || null;
                        suit = (s.length === 1 && 'hdcs'.includes(s)) ? s : null;
                        if (rank && suit) return { rank, suit, source: 'inner-value-suit' };
                    }
                }
                return null;
            }

            function getTextExcluding(el, excludeSelectors) {
                const clone = el.cloneNode(true);
                for (const sel of excludeSelectors) {
                    clone.querySelectorAll(sel).forEach(e => e.remove());
                }
                return clone.textContent || '';
            }

            // ============================================================
            // PLAYERS
            // ============================================================
            result.players = [];
            const playerEls = document.querySelectorAll('.table-player');
            result.debug.push('Players: ' + playerEls.length);

            let meIndex = -1;
            playerEls.forEach((el, idx) => {
                const p = { cards: [] };

                const nameEl = el.querySelector('.player-name');
                p.name = nameEl ? nameEl.textContent.trim() : '';

                const betEl = el.querySelector(
                    '.table-player-bet-value .normal-value, .table-player-bet-value .chips-value'
                );
                p.bet = betEl ? betEl.textContent.trim() : '0';

                const stackText = getTextExcluding(el, [
                    '.table-player-bet-value',
                    '.table-player-cards',
                    '.card-container',
                    '.emoji-container',
                    '.player-table-signals-container',
                ]);
                const cleanText = stackText.replace(p.name, '').replace(/Select/gi, '').trim();
                const stackNums = cleanText.match(/[\d,]+/g);
                if (stackNums) {
                    const parsed = stackNums
                        .map(n => parseInt(n.replace(/,/g, ''), 10))
                        .filter(n => !isNaN(n) && n > 0);
                    p.stack = parsed.length > 0 ? String(Math.max(...parsed)) : '0';
                } else {
                    p.stack = '0';
                }

                p.isDealer = el.querySelector(
                    '.dealer-button-ctn, .dealer-button, [class*="dealer"]'
                ) !== null;

                p.isFolded = el.classList.contains('folded')
                    || el.querySelector('.folded, [class*="fold"]') !== null;

                const isMe = el.classList.contains('you-player');
                p.isMe = isMe;
                if (isMe) meIndex = idx;

                const cardContainers = el.querySelectorAll('.card-container');
                cardContainers.forEach(cc => {
                    const card = extractCardFromContainer(cc);
                    if (card) p.cards.push(card);
                });

                result.debug.push('P' + idx + ': ' + p.name +
                    ' stack=' + p.stack + ' bet=' + p.bet +
                    ' cards=' + p.cards.length +
                    (p.cards.length > 0 ? ' [' + p.cards.map(c => c.rank + c.suit).join(',') + ']' : '') +
                    ' me=' + p.isMe + ' dealer=' + p.isDealer);
                result.players.push(p);
            });
            result.meIndex = meIndex;

            // ============================================================
            // MY CARDS
            // ============================================================
            result.myCards = [];
            if (meIndex >= 0 && result.players[meIndex].cards.length > 0) {
                result.myCards = result.players[meIndex].cards;
            } else {
                document.querySelectorAll('.you-player .card-container').forEach(cc => {
                    const card = extractCardFromContainer(cc);
                    if (card) result.myCards.push(card);
                });
            }
            result.debug.push('My cards: ' + result.myCards.length +
                (result.myCards.length > 0
                    ? ' [' + result.myCards.map(c => c.rank + c.suit).join(',') + ']'
                    : ''));

            // ============================================================
            // COMMUNITY CARDS — try many selectors + broad fallback
            // ============================================================
            result.communityCards = [];

            // All card-containers NOT inside a table-player are board cards
            const allCardContainers = document.querySelectorAll('.card-container');
            const playerCardContainers = document.querySelectorAll('.table-player .card-container');
            const playerCardSet = new Set();
            playerCardContainers.forEach(c => playerCardSet.add(c));

            const boardContainers = [];
            allCardContainers.forEach(cc => {
                if (!playerCardSet.has(cc)) {
                    boardContainers.push(cc);
                }
            });

            if (boardContainers.length > 0) {
                boardContainers.forEach(cc => {
                    // Skip cards that are face-down / not flipped
                    const cls = cc.className || '';
                    if (cls.includes('flipped') || !cls.includes('not-flipped')) {
                        const card = extractCardFromContainer(cc);
                        if (card) result.communityCards.push(card);
                    }
                });
                if (result.communityCards.length > 0) {
                    result.debug.push('Board (non-player cards): ' +
                        result.communityCards.map(c => c.rank + c.suit).join(','));
                }
            }

            // Fallback: try specific selectors
            if (result.communityCards.length === 0) {
                const boardSels = [
                    '.community-cards .card-container',
                    '.board-cards .card-container',
                    '[class*="community"] .card-container',
                    '.table-center .card-container',
                    '.flop-cards .card-container',
                ];
                for (const sel of boardSels) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        els.forEach(cc => {
                            const card = extractCardFromContainer(cc);
                            if (card) result.communityCards.push(card);
                        });
                        if (result.communityCards.length > 0) {
                            result.debug.push('Board (' + sel + '): ' +
                                result.communityCards.map(c => c.rank + c.suit).join(','));
                            break;
                        }
                    }
                }
            }

            if (result.communityCards.length === 0) {
                // Debug: dump all card-container locations for diagnosis
                const locs = [];
                allCardContainers.forEach(cc => {
                    const inPlayer = playerCardSet.has(cc);
                    const parent = cc.parentElement;
                    const pCls = parent ? parent.className : 'none';
                    const gpCls = parent && parent.parentElement ? parent.parentElement.className : 'none';
                    locs.push((inPlayer ? '[player]' : '[OTHER]') +
                        ' parent="' + (pCls || '').substring(0, 60) + '"' +
                        ' gp="' + (gpCls || '').substring(0, 60) + '"');
                });
                result.debug.push('Board: 0 cards. All card-containers (' + locs.length + '):');
                locs.forEach((l, i) => { if (i < 10) result.debug.push('  ' + l); });
            }

            // ============================================================
            // POT — prefer the "total" label value (includes current bets)
            // ============================================================
            result.pot = '0';

            // PokerNow shows two numbers: a main pot and a "total X" above it.
            // The "total" value is the full pot including current-street bets.
            const totalEl = document.querySelector('.table-pot-size .total-pot-val, .total-pot-value, [class*="total-pot"]');
            if (totalEl && totalEl.textContent.trim()) {
                result.pot = totalEl.textContent.trim();
                result.debug.push('Pot (total): ' + result.pot);
            } else {
                // Fallback: look for any pot element but prefer the one with "total" text
                const potContainer = document.querySelector('.table-pot-size, [class*="table-pot"]');
                if (potContainer) {
                    const fullText = potContainer.textContent || '';
                    // Try to find "total X" pattern first
                    const totalMatch = fullText.match(/total\s*([\d,]+)/i);
                    if (totalMatch) {
                        result.pot = totalMatch[1];
                        result.debug.push('Pot (total regex): ' + result.pot);
                    } else {
                        // Get the largest number in the pot area (that's the total)
                        const nums = fullText.match(/[\d,]+/g);
                        if (nums && nums.length > 0) {
                            const parsed = nums.map(n => parseInt(n.replace(/,/g, ''), 10)).filter(n => !isNaN(n));
                            if (parsed.length > 0) {
                                result.pot = String(Math.max(...parsed));
                            }
                        }
                        result.debug.push('Pot (max num): ' + result.pot + ' from "' + fullText.trim().substring(0, 60) + '"');
                    }
                }
            }

            // ============================================================
            // GAME LOG
            // ============================================================
            result.log = [];
            const lSels = ['.game-log-container .log-message', '.hand-history .message',
                '[class*="game-log"] [class*="message"]', '.log-message'];
            for (const sel of lSels) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    els.forEach(e => result.log.push(e.textContent.trim()));
                    result.debug.push('Log: ' + els.length + ' entries');
                    break;
                }
            }

            return result;
        }""")

        self._debug_log = data.get("debug", [])

        # Parse cards from DOM
        state.my_cards = self._cards_from_dicts(data.get("myCards", []))
        state.community_cards = self._cards_from_dicts(data.get("communityCards", []))

        # Parse log
        log_lines = data.get("log", [])
        current_hand_lines: list[str] = []
        for line in reversed(log_lines):
            if is_hand_start(line):
                hn = parse_hand_number(line)
                if hn:
                    state.hand_number = hn
                break
            current_hand_lines.insert(0, line)

        # Store raw lines for external consumers (stats tracker, database)
        self._current_hand_lines = current_hand_lines

        # Use street-aware action parsing
        state.action_history = parse_actions_with_streets(current_hand_lines)

        # Extract comprehensive hand data (showdowns, winners, etc.)
        self._last_hand_data = extract_hand_data(current_hand_lines)

        # If DOM scraping missed board cards, parse from game log as fallback
        if not state.community_cards:
            log_board = parse_board_from_log(current_hand_lines)
            if log_board:
                state.community_cards = log_board
                self._debug_log.append(
                    f"Board (from log): {' '.join(str(c) for c in log_board)}"
                )

        # Street
        nc = len(state.community_cards)
        if nc == 0:
            state.street = Street.PREFLOP
        elif nc == 3:
            state.street = Street.FLOP
        elif nc == 4:
            state.street = Street.TURN
        elif nc >= 5:
            state.street = Street.RIVER

        # Pot
        state.pot = self._parse_number(data.get("pot", "0"))

        # Blinds
        sb_name, bb_name = self._find_blinds_from_log(current_hand_lines)
        self._debug_log.append(f"Blinds: SB={sb_name} BB={bb_name}")

        # Players
        raw_players = data.get("players", [])
        state.num_players = len(raw_players)
        me_index = data.get("meIndex", -1)
        positions = self._assign_positions(raw_players, sb_name, bb_name)

        for i, rp in enumerate(raw_players):
            stack = self._parse_number(rp.get("stack", "0"))
            bet = self._parse_number(rp.get("bet", "0"))
            name = rp.get("name", f"Player{i}")
            is_folded = rp.get("isFolded", False)
            pos = positions[i]

            player = PlayerInfo(
                name=name, stack=stack, position=pos,
                is_active=not is_folded, current_bet=bet,
            )
            state.players.append(player)

            if rp.get("isMe") or name == config.PLAYER_NAME or i == me_index:
                state.my_stack = stack
                state.my_position = pos
                if not state.my_cards:
                    state.my_cards = self._cards_from_dicts(rp.get("cards", []))

        # Current bet to call
        if state.players:
            max_bet = max(p.current_bet for p in state.players)
            my_bet = 0.0
            for p in state.players:
                if p.name == config.PLAYER_NAME:
                    my_bet = p.current_bet
                    break
            state.current_bet = max(0, max_bet - my_bet)

        state.min_raise = max(state.big_blind, state.current_bet * 2)
        return state

    def _find_blinds_from_log(self, lines: list[str]) -> tuple[str | None, str | None]:
        sb_name = None
        bb_name = None
        for line in lines:
            m = re.search(r'"([^"]+)"\s+posts\s+a\s+small\s+blind', line, re.IGNORECASE)
            if m:
                sb_name = m.group(1).strip()
            m = re.search(r'"([^"]+)"\s+posts\s+a\s+big\s+blind', line, re.IGNORECASE)
            if m:
                bb_name = m.group(1).strip()
            if not sb_name:
                m = re.search(r'(\S+)\s+posts\s+a\s+small\s+blind', line, re.IGNORECASE)
                if m:
                    sb_name = m.group(1).strip().strip('"')
            if not bb_name:
                m = re.search(r'(\S+)\s+posts\s+a\s+big\s+blind', line, re.IGNORECASE)
                if m:
                    bb_name = m.group(1).strip().strip('"')
            if sb_name and bb_name:
                break
        return sb_name, bb_name

    def _assign_positions(
        self, raw_players: list[dict], sb_name: str | None, bb_name: str | None
    ) -> list[Position]:
        n = len(raw_players)
        if n == 0:
            return []

        names = [rp.get("name", f"Player{i}") for i, rp in enumerate(raw_players)]
        pos_labels = positions_for_table(n)

        if not sb_name or not bb_name:
            dealer_idx = 0
            for i, rp in enumerate(raw_players):
                if rp.get("isDealer"):
                    dealer_idx = i
                    break
            result = [Position.MP] * n
            for i in range(n):
                pos_idx = (i - dealer_idx) % n
                result[i] = pos_labels[pos_idx] if pos_idx < len(pos_labels) else Position.MP
            return result

        sb_idx = None
        bb_idx = None
        for i, name in enumerate(names):
            if name == sb_name:
                sb_idx = i
            if name == bb_name:
                bb_idx = i
        if sb_idx is None or bb_idx is None:
            for i, name in enumerate(names):
                if sb_name and sb_name in name and sb_idx is None:
                    sb_idx = i
                if bb_name and bb_name in name and bb_idx is None:
                    bb_idx = i

        if sb_idx is None or bb_idx is None:
            return [pos_labels[i % len(pos_labels)] for i in range(n)]

        if n == 2:
            btn_idx = sb_idx
        else:
            btn_idx = (sb_idx - 1) % n

        result = [Position.MP] * n
        for i in range(n):
            seat = (btn_idx + i) % n
            if i < len(pos_labels):
                result[seat] = pos_labels[i]
        return result

    def get_debug_log(self) -> list[str]:
        return self._debug_log

    def get_current_hand_lines(self) -> list[str]:
        """Return raw log lines for the current hand."""
        return self._current_hand_lines

    def get_hand_data(self) -> dict | None:
        """Return parsed hand data including showdown cards and winners."""
        return self._last_hand_data

    def _cards_from_dicts(self, card_dicts: list) -> list[Card]:
        cards = []
        for cd in card_dicts:
            if isinstance(cd, dict) and cd.get("rank") and cd.get("suit"):
                cards.append(Card(rank=cd["rank"], suit=cd["suit"]))
        return cards

    def _parse_number(self, text: str) -> float:
        if not text:
            return 0.0
        cleaned = re.sub(r"[^\d.]", "", str(text))
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
