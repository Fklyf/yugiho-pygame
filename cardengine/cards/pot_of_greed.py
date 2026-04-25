"""
cardengine/cards/pot_of_greed.py
---------------------------------
Effect implementation for Pot of Greed (id: 55144522).

Card text:
    Draw 2 cards.

Card type: Normal Spell
    Normal Spells can only be activated during your own Main Phase 1 or 2.
    They resolve immediately and are sent to the GY after resolution.

Hook used: on_spell_activate
    Called by game.py/_handle_activate when this card is played.

    context keys read:
        "active_player"   — "player" | "opponent"
        "game_state"      — serialised state dict (used for phase check)
    context keys written:
        "draw_count"      — int: number of cards to draw this resolution
        "effect_message"  — human-readable result string for the game log
        "announcement_title" / "announcement_body" / "announcement_kind"
                          — read by Main.py to trigger draw_announcement()

    Returns: None  (all output is via context mutation)
"""

from __future__ import annotations
from cardengine.effects import register, PhaseError

print("[POG module] pot_of_greed.py was imported")

# ── Card identity ─────────────────────────────────────────────────────────────

CARD_ID   = "55144522"
CARD_NAME = "Pot of Greed"

# ── Constants ─────────────────────────────────────────────────────────────────

_DRAW_AMOUNT  = 2
_VALID_PHASES = {"Main"}


# ── Phase guard (mirrors dark_magic_attack.py) ────────────────────────────────

def _require_phase(context: dict, *allowed: str) -> None:
    """
    Raises PhaseError if the current phase is not in *allowed*.
    Fails open (allows) when game_state is absent — safe for tests/sandbox.
    """
    game_state = context.get("game_state", {})
    if not game_state:
        return

    phase = game_state.get("phase", "")
    if phase and phase not in allowed:
        allowed_str = " / ".join(allowed)
        raise PhaseError(
            f"{CARD_NAME} can only be activated during {allowed_str} "
            f"(current phase: {phase})."
        )


# ── Effect implementation ─────────────────────────────────────────────────────

def _on_spell_activate(card, context: dict) -> None:
    """
    on_spell_activate handler for Pot of Greed.

    Steps
    -----
    1. Phase guard — Main Phase 1 or 2 only.
    2. Queue 2 draws via context["draw_count"].
    3. Set context["effect_message"] for the game log.
    4. Set announcement keys for Main.py's draw_announcement().

    No activation condition beyond phase — Pot of Greed has no prerequisite.
    """
    active_player = context.get("active_player", "player")

    # ── 1. Phase guard ────────────────────────────────────────────────────
    _require_phase(context, *_VALID_PHASES)

    # ── 2. Queue draws ────────────────────────────────────────────────────
    # game.py / apply_result should read context["draw_count"] and draw
    # that many cards for the active player.  We add to any existing value
    # so stacking multiple draw effects in the same resolution works safely.
    existing_draws = context.get("draw_count", 0) or 0
    context["draw_count"] = existing_draws + _DRAW_AMOUNT

    # ── 3. Effect message ─────────────────────────────────────────────────
    who = "Player" if active_player == "player" else "Opponent"
    context["effect_message"] = (
        f"{CARD_NAME}: {who} draws {_DRAW_AMOUNT} cards."
    )

    # ── 4. Announcement (read by Main.py → draw_announcement()) ──────────
    context["announcement_title"] = f"✦ {CARD_NAME} ✦"
    context["announcement_body"]  = [
        f"{who} activates Pot of Greed!",
        f"Draw {_DRAW_AMOUNT} cards.",
    ]
    context["announcement_kind"]  = "spell"


# ── Registration ──────────────────────────────────────────────────────────────
# Register under both 8-digit and 7-digit forms to match however metadata.json
# stores the id (string "55144522" vs int 55144522 → str → same key here).
register(CARD_ID,             "on_spell_activate", _on_spell_activate)
register(CARD_ID.lstrip("0"), "on_spell_activate", _on_spell_activate)
