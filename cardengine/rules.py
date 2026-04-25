"""
cardengine/rules.py
-------------------
Generic game-rule validation.

Checks legality of actions (summons, attacks, targeting) without knowing
about specific card effects.  Card-specific overrides live in the effects
registry (effects.py).

Behaviour is controlled by RULES_MODE in config.py:
    "sandbox" — all checks pass, nothing is ever blocked
    "loose"   — checks run and log warnings, but never hard-block
    "strict"  — checks run and hard-block illegal actions

NOTE: Normal-summon and fusion-summon checks ALWAYS hard-block regardless of
RULES_MODE.  RULES_MODE only softens combat / targeting checks.
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING

try:
    from config import RULES_MODE
except ImportError:
    RULES_MODE = "loose"   # safe default if config isn't available

if TYPE_CHECKING:
    from engine.card import Card


def _check(ok: bool, reason: str) -> tuple[bool, str]:
    """
    Applies RULES_MODE to a rule check result.
      sandbox → always (True, "")
      loose   → always (True, reason)  — caller can log the warning
      strict  → returns (ok, reason) unchanged
    """
    if RULES_MODE == "sandbox":
        return True, ""
    if RULES_MODE == "loose":
        return True, reason if not ok else ""
    # strict
    return ok, reason


# ---------------------------------------------------------------------------
# Card-type helpers
# ---------------------------------------------------------------------------

def is_monster(card: "Card") -> bool:
    return "Monster" in getattr(card, "card_type", "")

def is_spell(card: "Card") -> bool:
    return "Spell" in getattr(card, "card_type", "")

def is_trap(card: "Card") -> bool:
    return "Trap" in getattr(card, "card_type", "")

def is_fusion(card: "Card") -> bool:
    """True for any Fusion Monster (Extra Deck card, cannot be Normal Summoned)."""
    meta = getattr(card, "meta", {}) or {}
    card_type = meta.get("type", getattr(card, "card_type", ""))
    return "Fusion" in str(card_type)

def is_extra_deck_monster(card: "Card") -> bool:
    """
    True for any monster that lives in the Extra Deck and cannot be Normal Summoned.
    Covers Fusion, Synchro, XYZ, Link.
    """
    meta = getattr(card, "meta", {}) or {}
    card_type = str(meta.get("type", getattr(card, "card_type", "")))
    return any(t in card_type for t in ("Fusion", "Synchro", "Xyz", "Link"))


# ---------------------------------------------------------------------------
# Fusion material parsing
# ---------------------------------------------------------------------------

def fusion_materials(card: "Card") -> list[str]:
    """
    Parses the card's desc field for material names listed in the standard
    Fusion Monster format:

        "Blue-Eyes White Dragon" + "Blue-Eyes White Dragon" + ...

    Returns a list of material name strings (with duplicates preserved).
    Returns an empty list if none are found or desc is missing.
    """
    meta = getattr(card, "meta", {}) or {}
    desc = meta.get("desc", "") or ""
    # Extract all quoted names at the start of the description.
    # Stop at the first sentence that doesn't look like a material list.
    # Standard format: "Name A" + "Name B" + ...
    materials = re.findall(r'"([^"]+)"', desc.split("\n")[0])
    return materials


def can_fusion_summon(card: "Card", field_monsters: list) -> tuple[bool, str]:
    """
    Checks whether a Fusion Monster can be Fusion Summoned onto the field.

    Rules enforced:
      • The card must actually be a Fusion Monster.
      • Each required material must be present on the owner's field by name.
        Duplicates in the material list require duplicates on the field.
      • There must be a free zone after materials are removed (net monsters).

    Returns (ok, reason).  This check always hard-blocks — it is not subject
    to RULES_MODE loosening because placing an illegal Fusion card on the field
    would corrupt the game state.
    """
    if not is_fusion(card):
        return False, "Not a Fusion Monster."

    materials = fusion_materials(card)
    if not materials:
        # No parseable materials — block to be safe, log a clear reason.
        return False, "Could not parse Fusion materials from card description."

    # Build a mutable list of field monster names to tick off one by one
    field_names = [
        (getattr(m, "meta", {}) or {}).get("name", "")
        for m in field_monsters
    ]

    missing = []
    remaining_field = list(field_names)
    for material in materials:
        if material in remaining_field:
            remaining_field.remove(material)
        else:
            missing.append(material)

    if missing:
        return False, (
            f"Missing Fusion material(s) on field: "
            + ", ".join(f'"{m}"' for m in missing)
        )

    # After consuming materials, check that a zone will be free
    net_monsters = len(field_monsters) - len(materials)
    if net_monsters >= 5:
        return False, "No free monster zone after Fusion Summon."

    return True, None


# ---------------------------------------------------------------------------
# Tribute requirements
# ---------------------------------------------------------------------------

TRIBUTE_LEVELS = {
    range(1, 5):  0,   # Level 1–4:  no tribute
    range(5, 7):  1,   # Level 5–6:  1 tribute
    range(7, 13): 2,   # Level 7+:   2 tributes
}


def tributes_required(card: "Card") -> int:
    """
    Returns how many tributes are needed to Normal Summon this card.
    Extra Deck monsters (Fusion, Synchro, etc.) always return 0 because
    they are never Normal Summoned.
    """
    if is_extra_deck_monster(card):
        return 0
    level = (getattr(card, "meta", {}) or {}).get("level") or 0
    for level_range, count in TRIBUTE_LEVELS.items():
        if level in level_range:
            return count
    return 0

def can_draw(game_state: dict) -> tuple[bool, str]:
    """
    Returns (ok, reason).

    Opening-hand deal
    -----------------
    The first player receives their starting hand during setup (outside the
    normal Draw Phase), so their very first turn begins at Standby / Main —
    they do NOT draw at the start of turn 1.

    The second player DOES draw at the start of their first turn (turn 2
    overall), giving them one extra card to compensate for going second.
    This is handled by the flag ``second_player_first_turn`` in game_state.

    Flags expected in game_state
    ----------------------------
    phase                   : str   — current phase name (default "Main")
    has_drawn_this_turn     : bool  — True once the normal draw has been taken
    second_player_first_turn: bool  — True only on the very first turn of the
                                      second player; allows a draw outside the
                                      Draw Phase (or a second draw if already
                                      in Draw Phase) up to the hand limit set
                                      by the first player
    draws_remaining         : int   — how many draws are still allowed this
                                      phase/turn (used for second-player
                                      opening draw; normal turns this is 1)
    """
    phase = game_state.get("phase", "Main")

    # Second player's first turn: they are entitled to draw up to their
    # starting hand limit regardless of phase, as long as draws remain.
    if game_state.get("second_player_first_turn", False):
        remaining = game_state.get("draws_remaining", 1)
        if remaining <= 0:
            return False, "You have already drawn your opening hand."
        return True, ""

    # Normal turns: must be in Draw Phase and must not have drawn yet.
    if phase != "Draw":
        return False, f"You can only draw during the Draw Phase (current phase: {phase})."

    if game_state.get("has_drawn_this_turn", False):
        return False, "You have already drawn a card this turn."

    return True, ""

def can_normal_summon(card: "Card", field_monsters: list, tributes: list = None, game_state: dict = None) -> tuple[bool, str]:
    """
    Returns (ok, reason).  Always hard-blocks illegal summons regardless of
    RULES_MODE — placing a card on the field illegally corrupts game state.
    """
    tributes   = tributes   or []
    game_state = game_state or {}

    # Phase restriction: Normal Summons are only legal in Main Phase 1 or 2.
    # We check this before other rules so the user gets the most relevant
    # error first (no point telling them they're missing tributes if they
    # can't summon in this phase anyway). Same hard-block policy as the rest
    # of can_normal_summon — placing a card on the field outside Main Phase
    # would corrupt turn structure.
    phase = game_state.get("phase", "")
    if phase and phase not in ("Main 1", "Main 2"):
        return False, (
            f"Monsters can only be Normal Summoned during Main Phase 1 or 2 "
            f"(current phase: {phase})."
        )

    # Only one Normal/Tribute Summon per turn.
    if game_state.get("has_summoned_this_turn", False):
        return False, "You can only Normal Summon once per turn."

    # Extra Deck monsters cannot be Normal Summoned at all.
    if is_extra_deck_monster(card):
        card_type = (getattr(card, "meta", {}) or {}).get("type", "Extra Deck monster")
        return False, f"{card_type} cannot be Normal Summoned."

    level = (getattr(card, "meta", {}) or {}).get("level") or \
            getattr(card, "level", 1)

    # --- Level 1-4: No tribute ---
    if level <= 4:
        if len(tributes) > 0:
            return False, "Level 4 or lower monsters cannot be Tribute Summoned."

    # --- Level 5-6: exactly 1 tribute ---
    elif 5 <= level <= 6:
        if len(tributes) < 1:
            return False, f"Level {level} monster requires 1 Tribute."
        if len(tributes) > 1:
            return False, "Too many Tributes for a Level 5-6 monster."

    # --- Level 7+: exactly 2 tributes ---
    elif level >= 7:
        if len(tributes) < 2:
            return False, f"Level {level} monster requires 2 Tributes."
        if len(tributes) > 2:
            return False, "Too many Tributes for a Level 7+ monster."

    # Field space check (tributes free up slots)
    if (len(field_monsters) - len(tributes)) >= 5:
        return False, "Monster zones are full."

    return True, None


# ---------------------------------------------------------------------------
# Attack legality
# ---------------------------------------------------------------------------

def can_attack(attacker: "Card", game_state: dict) -> tuple[bool, str]:
    """
    Returns (ok, reason).
    Checks basic rules only — continuous effects that prevent attack
    (e.g. Swords of Revealing Light) should be checked via effects.py.
    """
    if attacker.mode != "ATK":
        return _check(False, "Monster must be in ATK position to attack.")

    if getattr(attacker, "summoning_sickness", False):
        return _check(False, "Monster cannot attack the turn it was summoned.")

    if getattr(attacker, "attack_used", False):
        return _check(False, "Monster has already attacked this turn.")

    return True, ""


def can_be_attacked(defender: "Card") -> tuple[bool, str]:
    """
    Returns (ok, reason).
    A face-down SET monster CAN be attacked (flip effect resolves separately).
    """
    if getattr(defender, "cannot_be_attacked", False):
        return _check(False, "This monster cannot be attacked.")
    return True, ""


# ---------------------------------------------------------------------------
# Targeting legality
# ---------------------------------------------------------------------------

def can_be_targeted(target: "Card", effect_type: str = "spell") -> tuple[bool, str]:
    """
    Returns (ok, reason).
    effect_type: "spell" | "trap" | "monster"
    """
    if getattr(target, "untargetable", False):
        return _check(False, "This card cannot be targeted.")
    if target.mode == "SET" and effect_type in ("spell", "trap"):
        return _check(False, "Face-down monsters cannot be targeted by Spell/Trap effects.")
    return True, ""


# ---------------------------------------------------------------------------
# Zone helpers
# ---------------------------------------------------------------------------

MAX_MONSTER_ZONES    = 5
MAX_SPELL_TRAP_ZONES = 5


def has_open_monster_zone(field_monsters: list) -> bool:
    return len(field_monsters) < MAX_MONSTER_ZONES


def has_open_spell_trap_zone(field_spells: list) -> bool:
    return len(field_spells) < MAX_SPELL_TRAP_ZONES


# ---------------------------------------------------------------------------
# Set / Flip-activate legality
# ---------------------------------------------------------------------------

def can_set_spell_trap(card: "Card", field_cards: list, game_state: dict = None) -> tuple[bool, str]:
    """
    Returns (ok, reason) for setting a Spell/Trap face-down.
    - Must be a Spell or Trap.
    - Must have a free Spell/Trap zone. Here ``field_cards`` is the owner's
      full field list (monsters + spells/traps, as Main.py has no separate
      spell/trap zone list). We count non-monster cards as occupying S/T zones.
    """
    if is_monster(card):
        return False, "Monsters cannot be Set to a Spell/Trap zone."
    if not (is_spell(card) or is_trap(card)):
        return False, "Only Spells or Traps can be Set to a Spell/Trap zone."
    st_count = sum(1 for c in field_cards if not is_monster(c))
    if st_count >= MAX_SPELL_TRAP_ZONES:
        return False, "Spell/Trap zones are full."
    return True, ""


def can_set_monster(card: "Card", field_monsters: list, tributes: list = None, game_state: dict = None) -> tuple[bool, str]:
    """
    Returns (ok, reason) for Setting a monster face-down in DEF.
    Piggybacks the Normal Summon rules — Sets and Normal Summons share the
    'once per turn' budget and the same tribute costs.
    """
    return can_normal_summon(card, field_monsters, tributes or [], game_state or {})


def can_flip_activate(card: "Card", game_state: dict = None) -> tuple[bool, str]:
    """
    Returns (ok, reason) for flipping a face-down Spell/Trap face-up to
    activate it.

    Rules enforced (always hard-block — these are timing-critical):
      • Traps and Quick-Play Spells cannot be activated the turn they were Set.
        We check ``card.turn_set`` against ``game_state["turn"]``.
      • Normal Spells, Continuous Spells, Equip Spells, Field Spells have no
        same-turn restriction.
    """
    game_state = game_state or {}
    current_turn = game_state.get("turn") or game_state.get("meta", {}).get("turn")
    turn_set     = getattr(card, "turn_set", None)

    meta       = getattr(card, "meta", {}) or {}
    card_type  = str(meta.get("type", getattr(card, "card_type", "")))
    is_trap_c       = "Trap" in card_type
    is_quickplay_c  = "Quick-Play" in card_type

    if (is_trap_c or is_quickplay_c) and turn_set is not None and turn_set == current_turn:
        label = "Trap" if is_trap_c else "Quick-Play Spell"
        return False, f"{label} cannot be activated the turn it was Set."

    return True, ""