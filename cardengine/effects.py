"""
cardengine/effects.py
---------------------
Card effect registry and hook dispatcher.

How it works
------------
1.  Each card in metadata.json can carry an "effects" list of hook names:

        "effects": ["on_discard", "on_damage_calc"]

2.  When a game event fires, call:

        dispatch(hook_name, card, context)

    The registry looks up the card's id, finds any handler registered for
    that (card_id, hook), and calls it.

3.  Card-specific modules (e.g. cardengine/cards/kuriboh.py) register their
    handlers at import time using @register or register().

Supported hooks (add more as needed)
-------------------------------------
    on_discard          — card is discarded from hand
    on_draw             — card is drawn
    on_summon           — card is successfully summoned
    on_destroy          — card is sent to GY from field
    on_damage_calc      — during damage calculation (before damage is applied)
    on_spell_activate   — when a spell targets this card
    on_end_phase        — end of the turn this card is on the field
    on_equip            — when this card is equipped to a monster
    continuous_atk_mod  — returns an ATK modifier int (called every frame)
    continuous_def_mod  — returns a DEF modifier int (called every frame)
"""

from __future__ import annotations
from typing import Callable, Any

# Registry: { card_id: { hook_name: handler_fn } }
_registry: dict[str, dict[str, Callable]] = {}


# ---------------------------------------------------------------------------
# Registration API
# ---------------------------------------------------------------------------

def register(card_id: str, hook: str, fn: Callable) -> None:
    """Register a handler for a specific card id + hook combination."""
    _registry.setdefault(str(card_id), {})[hook] = fn


def register_card(card_id: str) -> Callable:
    """
    Class/module decorator. The decorated object must expose methods named
    after hooks (e.g. def on_discard(card, context): ...).

    Usage:
        @register_card("40640057")   # Kuriboh
        class KuribohEffects:
            def on_discard(card, context): ...
    """
    def decorator(cls):
        for hook in dir(cls):
            if hook.startswith("_"):
                continue
            fn = getattr(cls, hook)
            if callable(fn):
                register(card_id, hook, fn)
        return cls
    return decorator


# ---------------------------------------------------------------------------
# Dispatch API
# ---------------------------------------------------------------------------

def dispatch(hook: str, card, context: dict) -> Any:
    """
    Fire a hook for the given card.

    Returns the handler's return value, or None if no handler is registered.
    context is a mutable dict that handlers can read from / write to.
    """
    card_id = str((getattr(card, "meta", {}) or {}).get("id", ""))
    if not card_id:
        return None

    handlers = _registry.get(card_id, {})
    fn = handlers.get(hook)
    if fn is None:
        return None

    return fn(card, context)


def has_effect(card, hook: str) -> bool:
    """Quick check — does this card have a handler for this hook?"""
    card_id = str((getattr(card, "meta", {}) or {}).get("id", ""))
    return hook in _registry.get(card_id, {})


# ---------------------------------------------------------------------------
# Continuous modifier helpers (called each frame / on stat lookup)
# ---------------------------------------------------------------------------

def get_atk_modifier(card, game_state: dict) -> int:
    """
    Returns the total ATK modifier from all continuous effects on this card.
    The handler should return an int (positive or negative).
    """
    result = dispatch("continuous_atk_mod", card, {"game_state": game_state})
    return result if isinstance(result, int) else 0


def get_def_modifier(card, game_state: dict) -> int:
    result = dispatch("continuous_def_mod", card, {"game_state": game_state})
    return result if isinstance(result, int) else 0
