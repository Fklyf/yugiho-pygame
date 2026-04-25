"""
cardengine/game_helpers.py
--------------------------
Shared utility functions used by game_handlers.py and game_apply.py.

Nothing here imports from other game_* modules — this sits at the bottom
of the dependency chain so everyone can import from it safely.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Result constructors
# ---------------------------------------------------------------------------

def _ok(*, log=None, send_to_gy=None, lp_damage=None,
        effect_message=None, summoned_card=None) -> dict:
    return {
        "ok":             True,
        "error":          None,
        "log":            log or [],
        "send_to_gy":     send_to_gy or [],
        "lp_damage":      lp_damage or {"player": 0, "opponent": 0},
        "effect_message": effect_message,
        "summoned_card":  summoned_card,
    }


def _err(reason: str) -> dict:
    return {
        "ok":             False,
        "error":          reason,
        "log":            [f"Illegal action: {reason}"],
        "send_to_gy":     [],
        "lp_damage":      {"player": 0, "opponent": 0},
        "effect_message": None,
        "summoned_card":  None,
    }


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------

def _name(card) -> str:
    return (getattr(card, "meta", {}) or {}).get("name", "Unknown")


def _safe_remove(lst: list, item) -> None:
    try:
        lst.remove(item)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Battle helpers
# ---------------------------------------------------------------------------

def _lp_from_result(res: dict) -> dict:
    target = res.get("damage_target")
    damage = res.get("damage", 0)
    return {
        "player":   damage if target == "player"   else 0,
        "opponent": damage if target == "opponent" else 0,
    }
