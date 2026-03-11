"""CLI dashboard display using Rich."""

from __future__ import annotations

import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich import box

from observer.state import GameState, Street
from utils.cards import pretty_card, SUIT_COLORS

console = Console()


def _styled_card(rank: str, suit: str) -> Text:
    color = SUIT_COLORS.get(suit, "white")
    return Text(pretty_card(rank, suit), style=f"bold {color}")


def _cards_display(cards: list) -> Text:
    if not cards:
        return Text("--", style="dim")
    result = Text()
    for i, c in enumerate(cards):
        if i > 0:
            result.append("  ")
        result.append_text(_styled_card(c.rank, c.suit))
    return result


def render_dashboard(state: GameState, recommendation: dict | None = None) -> None:
    """Clear screen and render the full dashboard."""
    os.system("clear" if os.name != "nt" else "cls")

    console.print()

    # Header
    header = Text(f"  PokerNow Bot v0.1  |  Hand #{state.hand_number}", style="bold cyan")
    console.print(Panel(header, box=box.DOUBLE))

    # Hand info table
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("label", style="bold white", width=14)
    info_table.add_column("value")

    info_table.add_row("YOUR HAND:", _cards_display(state.my_cards))
    info_table.add_row("BOARD:", _cards_display(state.community_cards))
    info_table.add_row("", Text(""))
    info_table.add_row("Position:", Text(state.my_position.value, style="bold yellow"))
    info_table.add_row("Street:", Text(state.street.value.upper(), style="bold magenta"))

    stack_text = f"${state.my_stack:,.0f}" if state.my_stack else "--"
    pot_text = f"${state.pot:,.0f}" if state.pot else "$0"
    call_text = f"${state.current_bet:,.0f}" if state.current_bet else "$0"
    bb_text = f"${state.big_blind:,.0f}" if state.big_blind else "--"
    spr_text = f"{state.spr:.1f}" if state.pot > 0 else "--"

    info_table.add_row("Stack:", Text(stack_text, style="green"))
    info_table.add_row("Pot:", Text(pot_text, style="yellow"))
    info_table.add_row("To Call:", Text(call_text, style="red" if state.current_bet > 0 else "dim"))
    info_table.add_row("BB:", Text(bb_text))
    info_table.add_row("SPR:", Text(spr_text))

    console.print(Panel(info_table, title="[bold]Game Info[/bold]", box=box.ROUNDED))

    # Players table
    if state.players:
        p_table = Table(box=box.SIMPLE, padding=(0, 1))
        p_table.add_column("Pos", style="cyan", width=5)
        p_table.add_column("Player", width=16)
        p_table.add_column("Stack", justify="right", width=10)
        p_table.add_column("Status", width=10)

        for p in state.players:
            name_style = "bold green" if p.name == state.my_name else "white"
            name_display = f">>> {p.name} <<<" if p.name == state.my_name else p.name
            status = "[green]active[/green]" if p.is_active else "[dim]folded[/dim]"
            stack = f"${p.stack:,.0f}"
            p_table.add_row(
                p.position.value,
                Text(name_display, style=name_style),
                stack,
                status,
            )

        console.print(Panel(p_table, title="[bold]Players[/bold]", box=box.ROUNDED))

    # Recommendation
    if recommendation and recommendation.get("action") != "wait":
        rec = recommendation
        action_text = rec["action"].upper()
        amount = rec.get("amount", 0)

        if amount > 0:
            action_line = Text(f"  {action_text} ${amount:,.0f}", style="bold white on blue")
        else:
            action_line = Text(f"  {action_text}", style="bold white on blue")

        details = Text()
        equity = rec.get("equity", 0)
        hand_cat = rec.get("hand_category", "")
        confidence = rec.get("confidence", 0)
        reasoning = rec.get("reasoning", "")

        details.append(f"Equity: {equity:.1%}", style="bold")
        details.append(f"  |  Hand: {hand_cat}")
        details.append(f"  |  Confidence: {confidence:.0%}\n")
        details.append(reasoning, style="italic")

        rec_panel = Panel(
            Text.assemble(action_line, "\n", details),
            title="[bold]RECOMMENDATION[/bold]",
            border_style="green" if rec["action"] in ("raise", "bet") else "yellow",
            box=box.DOUBLE,
        )
        console.print(rec_panel)
    elif recommendation and recommendation.get("action") == "wait":
        console.print(Panel(
            Text("Waiting for cards...", style="dim italic"),
            title="[bold]STATUS[/bold]",
            box=box.ROUNDED,
        ))

    console.print()
