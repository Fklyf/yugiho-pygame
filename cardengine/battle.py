"""
cardengine/battle.py
--------------------
Generic battle resolution logic.

Handles ATK/DEF comparisons, damage calculation, and destruction outcomes.
Does NOT know about specific cards — all card-specific modifiers should be
applied to the card's effective_atk / effective_def before calling these.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.card import Card


# ---------------------------------------------------------------------------
# Battle result constants
# ---------------------------------------------------------------------------

RESULT_ATTACKER_WINS  = "attacker_wins"
RESULT_DEFENDER_WINS  = "defender_wins"
RESULT_BOTH_DESTROYED = "both_destroyed"
RESULT_NO_DAMAGE      = "no_damage"       # ATK vs DEF tie, or equal ATK


# ---------------------------------------------------------------------------
# Effective stat helpers
# ---------------------------------------------------------------------------

def get_effective_atk(card: "Card", game_state: dict = None) -> int:
    """
    Returns the card's ATK after all modifiers:
      • card.atk_modifier   — set directly on the card object (e.g. equip spells)
      • continuous_atk_mod  — registered effect hook (e.g. Dark Magician Girl GY boost)

    game_state is forwarded to continuous effect handlers so they can read
    graveyard / field state.  Pass it whenever you have it; omit for a quick
    base-stat lookup where continuous effects don't matter.
    """
    from cardengine import effects   # local import avoids circular dependency
    base       = (getattr(card, "meta", {}) or {}).get("atk") or 0
    attr_mod   = getattr(card, "atk_modifier", 0)
    effect_mod = effects.get_atk_modifier(card, game_state or {})
    return base + attr_mod + effect_mod


def get_effective_def(card: "Card", game_state: dict = None) -> int:
    """
    Returns the card's DEF after all modifiers.
    Mirrors get_effective_atk — see that docstring for details.
    """
    from cardengine import effects
    base       = (getattr(card, "meta", {}) or {}).get("def") or 0
    attr_mod   = getattr(card, "def_modifier", 0)
    effect_mod = effects.get_def_modifier(card, game_state or {})
    return base + attr_mod + effect_mod


# ---------------------------------------------------------------------------
# Core resolution
# ---------------------------------------------------------------------------

def resolve_attack(attacker: "Card", defender: "Card", game_state: dict) -> dict:
    """
    Resolves a single attack between attacker and defender.

    Returns a result dict:
        {
            "result":             RESULT_* constant,
            "attacker_destroyed": bool,
            "defender_destroyed": bool,
            "damage":             int,   # LP damage dealt to the defending player
            "damage_target":      "player" | "opponent" | None,
        }

    game_state must contain:
        "active_player": "player" | "opponent"
    """
    atk = get_effective_atk(attacker, game_state)

    # --- ATK vs ATK ---
    if defender.mode == "ATK":
        def_value = get_effective_atk(defender, game_state)
        if atk > def_value:
            damage = atk - def_value
            return _result(RESULT_ATTACKER_WINS,
                           attacker_destroyed=False,
                           defender_destroyed=True,
                           damage=damage,
                           damage_target=_defending_player(game_state))
        elif atk < def_value:
            damage = def_value - atk
            return _result(RESULT_DEFENDER_WINS,
                           attacker_destroyed=True,
                           defender_destroyed=False,
                           damage=damage,
                           damage_target=_attacking_player(game_state))
        else:
            return _result(RESULT_BOTH_DESTROYED,
                           attacker_destroyed=True,
                           defender_destroyed=True,
                           damage=0,
                           damage_target=None)

    # --- ATK vs DEF ---
    else:
        def_value = get_effective_def(defender, game_state)
        if atk > def_value:
            # Piercing damage only if attacker has the piercing flag
            piercing = getattr(attacker, "has_piercing", False)
            damage   = (atk - def_value) if piercing else 0
            return _result(RESULT_ATTACKER_WINS,
                           attacker_destroyed=False,
                           defender_destroyed=True,
                           damage=damage,
                           damage_target=_defending_player(game_state) if piercing else None)
        elif atk < def_value:
            return _result(RESULT_NO_DAMAGE,
                           attacker_destroyed=False,
                           defender_destroyed=False,
                           damage=0,
                           damage_target=None)
        else:
            return _result(RESULT_NO_DAMAGE,
                           attacker_destroyed=False,
                           defender_destroyed=False,
                           damage=0,
                           damage_target=None)


def resolve_direct_attack(attacker: "Card", game_state: dict) -> dict:
    """Direct attack when the defending player controls no monsters."""
    atk = get_effective_atk(attacker, game_state)
    return _result(RESULT_ATTACKER_WINS,
                   attacker_destroyed=False,
                   defender_destroyed=False,
                   damage=atk,
                   damage_target=_defending_player(game_state))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(result, *, attacker_destroyed, defender_destroyed, damage, damage_target) -> dict:
    return {
        "result":             result,
        "attacker_destroyed": attacker_destroyed,
        "defender_destroyed": defender_destroyed,
        "damage":             damage,
        "damage_target":      damage_target,
    }


def _defending_player(game_state: dict) -> str:
    return "opponent" if game_state.get("active_player") == "player" else "player"


def _attacking_player(game_state: dict) -> str:
    return game_state.get("active_player", "player")