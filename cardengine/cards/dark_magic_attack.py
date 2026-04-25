"""
cardengine/cards/dark_magic_attack.py
--------------------------------------
Effect implementation for Dark Magic Attack (id: 2314238).

Card text:
    If you control "Dark Magician": Destroy all Spells and Traps
    your opponent controls.

Card type: Normal Spell
    Normal Spells can only be activated during your own Main Phase.
    They resolve immediately and are sent to the GY after resolution.

Hook used: on_spell_activate
    Called by game.py/_handle_activate when this card is played.

    context keys read:
        "active_player"   — "player" | "opponent"
        "player_field"    — live list[Card] passed directly from Main.py
        "opp_field"       — live list[Card] passed directly from Main.py
        "game_state"      — serialised state dict (used for phase + fallback
                            field checks when live lists are absent)
    context keys written:
        "send_to_gy"      — list[Card] to destroy this resolution
        "effect_message"  — human-readable result string for the game log

    Returns: None  (all output is via context mutation)

──────────────────────────────────────────────────────────────────────────────
Template for future Normal Spell effects
──────────────────────────────────────────────────────────────────────────────
1.  Copy this file, update CARD_ID / CARD_NAME / _REQUIRED_MONSTER.
2.  Call _require_phase(context, *_VALID_PHASES) at the top of your handler.
3.  Use _live_field(context, owner) to get the live Card list for a side.
4.  Write results into context["send_to_gy"] and context["effect_message"].
5.  register(CARD_ID, "on_spell_activate", _your_handler) at the bottom.

Phase strings used by Main.py  (defined in PHASES constant):
    "Draw", "Main", "Battle", "End"
    Note the spaces — "Main" not "Main1".
"""

from __future__ import annotations
from cardengine.effects import register, PhaseError, ActivationConditionError

print("[DMA module] dark_magic_attack.py was imported")

# ── Card identity ─────────────────────────────────────────────────────────────

CARD_ID   = "02314238"   # Canonical Konami passcode (8 digits, leading zero)
CARD_NAME = "Dark Magic Attack"

# ── Constants ─────────────────────────────────────────────────────────────────

_REQUIRED_MONSTER = "Dark Magician"

# Main.py phase strings — must match PHASES in Main.py.
# These must exactly match the strings in Main.py's PHASES list.
_VALID_PHASES = {"Main"}


# ── Phase guard (reusable by all spell/trap effects) ──────────────────────────
# PhaseError is imported from cardengine.effects so game.py can catch it
# without needing to reach into individual card modules.

def _require_phase(context: dict, *allowed: str) -> None:
    """
    Raises PhaseError if the current phase is not in *allowed*.
    Fails open (allows) when game_state is absent — safe for tests/sandbox.

    Usage:
        _require_phase(context, *_VALID_PHASES)
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


# ── Field resolution helpers (reusable by all spell/trap effects) ─────────────

def _card_name(card) -> str:
    """Card name — works for both live Card objects and serialised dicts."""
    if isinstance(card, dict):
        return card.get("name", "")
    return (getattr(card, "meta", {}) or {}).get("name", "")


def _card_type_str(card) -> str:
    """Card type string — works for both live Card objects and serialised dicts."""
    if isinstance(card, dict):
        return str(card.get("type", card.get("card_type", "")))
    meta = getattr(card, "meta", {}) or {}
    return str(meta.get("type", getattr(card, "card_type", "")))


def _live_field(context: dict, owner: str) -> list:
    """
    Returns the live list[Card] for *owner*'s monster field.

    Priority:
      1. context["player_field"] / context["opp_field"]  — live Card objects,
         passed directly from Main.py into the activate context.  Always
         prefer these; they are the actual objects apply_result will mutate.
      2. game_state["player"]["field"] / ["opponent"]["field"]  — serialised
         dicts from build_game_state.  Useful for read-only checks (name,
         type, mode) but NOT suitable for send_to_gy (dicts ≠ Card objects).
    """
    key = "player_field" if owner == "player" else "opp_field"
    if key in context:
        return context[key]

    # Fallback: serialised dicts (read-only)
    gs_key = "player" if owner == "player" else "opponent"
    return context.get("game_state", {}).get(gs_key, {}).get("field", [])


def _controls_monster(context: dict, owner: str, monster_name: str) -> bool:
    """
    Returns True if *owner* has a face-up monster matching *monster_name*.
    Checks the live field via _live_field so it works for both Card objects
    and serialised dicts.
    """
    for card in _live_field(context, owner):
        if _card_name(card) == monster_name:
            mode = (card.get("mode") if isinstance(card, dict)
                    else getattr(card, "mode", "ATK"))
            if mode != "SET":
                return True
    return False


def _get_opp_spells_traps(context: dict, opp: str) -> list:
    """
    Returns the opponent's live Spell/Trap Card objects from their field.

    Main.py has no separate spell/trap zone list — all field cards live in
    opp_field regardless of type.  We filter by card type here and return
    only actual Card objects (not dicts) so apply_result can GY them safely.
    """
    result = []
    for card in _live_field(context, opp):
        if isinstance(card, dict):
            # Serialised dict — can't safely GY it, skip
            continue
        t = _card_type_str(card)
        if "Spell" in t or "Trap" in t:
            result.append(card)
    return result


# ── Effect implementation ─────────────────────────────────────────────────────

def _on_spell_activate(card, context: dict) -> None:
    """
    on_spell_activate handler for Dark Magic Attack.

    Steps
    -----
    1. Phase guard — Main Phase only.
    2. Condition — controller must have "Dark Magician" face-up on field.
    3. Collect all live Spell/Trap Cards from the opponent's field.
    4. Write into context["send_to_gy"] for apply_result to process.
    5. Set context["effect_message"] for the game log.
    """
    active_player = context.get("active_player", "player")

    # ── 1. Phase guard ────────────────────────────────────────────────────
    _require_phase(context, *_VALID_PHASES)

    # ── 2. Activation condition ───────────────────────────────────────────
    if not _controls_monster(context, active_player, _REQUIRED_MONSTER):
        raise ActivationConditionError(
            f'You must control "{_REQUIRED_MONSTER}" to activate {CARD_NAME}.'
        )

    # ── 3. Collect opponent's Spell/Trap cards ────────────────────────────
    opp = "opponent" if active_player == "player" else "player"

    # ── DIAGNOSTIC (safe to leave in — prints once per activation) ────────
    # Writes to both stdout AND dma_debug.txt so the log survives even when
    # the game is launched by double-click (no visible terminal).
    def _dbg(msg):
        print(msg)
        try:
            with open("dma_debug.txt", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    _dbg("")
    _dbg("=" * 60)
    _dbg(f"[DMA debug] Activation fired.")
    _dbg(f"[DMA debug] active_player={active_player!r}, opp={opp!r}")
    _dbg(f"[DMA debug] context keys: {sorted(context.keys())}")

    # What's actually in player_field / opp_field as the effect sees it?
    pf = context.get("player_field")
    of = context.get("opp_field")
    _dbg(f"[DMA debug] context['player_field'] is {type(pf).__name__} with "
         f"{len(pf) if pf is not None else 'n/a'} items")
    _dbg(f"[DMA debug] context['opp_field']    is {type(of).__name__} with "
         f"{len(of) if of is not None else 'n/a'} items")

    live_opp = _live_field(context, opp)
    _dbg(f"[DMA debug] _live_field(opp) returned {len(live_opp)} cards")
    for i, c in enumerate(live_opp):
        ctype = _card_type_str(c)
        cname = _card_name(c)
        cmode = c.get("mode") if isinstance(c, dict) else getattr(c, "mode", "?")
        is_dict = isinstance(c, dict)
        has_meta = (not is_dict) and bool(getattr(c, "meta", None))
        _dbg(f"[DMA debug]   [{i}] name={cname!r} type={ctype!r} "
             f"mode={cmode!r} is_dict={is_dict} has_meta={has_meta}")

    opp_spells = _get_opp_spells_traps(context, opp)
    _dbg(f"[DMA debug] _get_opp_spells_traps returned {len(opp_spells)} cards")
    for c in opp_spells:
        _dbg(f"[DMA debug]   queued for GY: {_card_name(c)!r} "
             f"owner={getattr(c, 'owner', None)!r}")

    # ── 4. Queue for destruction ──────────────────────────────────────────
    existing = context.get("send_to_gy") or []
    context["send_to_gy"] = existing + opp_spells

    # Stamp owner so apply_result routes to the correct GY
    for c in opp_spells:
        if not getattr(c, "owner", None):
            c.owner = opp

    # ── 5. Effect message + announcement ─────────────────────────────────
    count = len(opp_spells)
    who   = "Player" if active_player == "player" else "Opponent"

    if count == 0:
        effect_msg = f"{CARD_NAME} resolved — opponent had no Spells or Traps to destroy."
        ann_body   = [
            f"{who} controls Dark Magician.",
            "Opponent had no Spells or Traps on the field.",
        ]
    else:
        destroyed_names = [_card_name(c) for c in opp_spells]
        effect_msg = (
            f"{CARD_NAME}: destroyed {count} opponent Spell/Trap card"
            f"{'s' if count != 1 else ''}."
        )
        ann_body = [
            f"{who} activates Dark Magic Attack!",
            f"Destroyed {count} opponent card{'s' if count != 1 else ''}:",
        ] + [f"  • {n}" for n in destroyed_names]

    context["effect_message"]      = effect_msg
    # These two keys are read by Main.py to trigger draw_announcement()
    context["announcement_title"]  = f"✦ {CARD_NAME} ✦"
    context["announcement_body"]   = ann_body
    context["announcement_kind"]   = "spell"


# ── Registration ──────────────────────────────────────────────────────────────
# Register under both 8-digit (canonical Konami) and 7-digit forms so the
# dispatcher matches whether metadata.json stores the id with or without the
# leading zero. effects.dispatch() does str(meta["id"]) for lookup, so an int
# stored as 2314238 normalises to "2314238", while a string "02314238" stays
# as "02314238" — different keys, same card.
register(CARD_ID,            "on_spell_activate", _on_spell_activate)
register(CARD_ID.lstrip("0"), "on_spell_activate", _on_spell_activate)