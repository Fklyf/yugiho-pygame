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

Quick Effects
-------------
Cards that can be activated from hand during the opponent's turn (or at
specific steps outside the owner's Main Phase) register via:

    register_quick_effect(card_id, hook, fn, condition_fn)

The condition_fn(card, game_state) -> bool is evaluated each frame to decide
whether the ⚡ button should appear on that card in the hand zone.

To query which hand cards currently have activatable quick effects, call:

    get_quick_effects(hand, game_state) -> list[QuickEffectEntry]

Each entry is a namedtuple: (card, hook, label).

Integration in Main.py
-----------------------
Draw loop (every frame, during opponent's turn / relevant steps):
    quick_effs = effects.get_quick_effects(player_hand, game_state)
    ui.draw_quick_effect_buttons(screen, font, quick_effs, mouse_pos)

Mouse-click handler:
    hit = ui.quick_effect_btn_hit_test(mouse_pos, quick_effs)
    if hit:
        result = game.submit_action("quick_effect", {
            "card":        hit.card,
            "hook":        hit.hook,
            "game_state":  game_state,
            "hand":        player_hand,
            "graveyard":   player_gy,
            # ...any other context the specific effect needs
        })
        apply_result(result)
"""

from __future__ import annotations
from typing import Callable, Any, NamedTuple


# ---------------------------------------------------------------------------
# Shared exceptions (raised by card effect handlers, caught by game.py)
# ---------------------------------------------------------------------------

class PhaseError(Exception):
    """Raised when a card is activated in the wrong phase."""


class ActivationConditionError(Exception):
    """Raised when a card's activation condition isn't met
    (e.g. required monster not on field)."""


class SetTimingError(Exception):
    """Raised when a Trap or Quick-Play Spell is activated the same turn
    it was Set. Vanilla YGO timing rule."""


# ---------------------------------------------------------------------------
# Registry structures
# ---------------------------------------------------------------------------

# Main hook registry: { card_id: { hook_name: handler_fn } }
_registry: dict[str, dict[str, Callable]] = {}

# Quick effect registry entry
class _QuickEffectEntry(NamedTuple):
    hook:         str
    fn:           Callable
    condition_fn: Callable   # (card, game_state) -> bool
    label:        str        # Display label for the ⚡ button, e.g. "Kuriboh"


# Quick effect registry: { card_id: [_QuickEffectEntry, ...] }
_quick_registry: dict[str, list[_QuickEffectEntry]] = {}


# ---------------------------------------------------------------------------
# Public namedtuple returned by get_quick_effects
# ---------------------------------------------------------------------------

class QuickEffectEntry(NamedTuple):
    """Returned by get_quick_effects. One entry per activatable hand card."""
    card:  Any    # The Card object in hand
    hook:  str    # Hook to dispatch when activated
    label: str    # Human-readable name for the button (card name or custom)


# ---------------------------------------------------------------------------
# Registration API
# ---------------------------------------------------------------------------

def register(card_id: str, hook: str, fn: Callable) -> None:
    """Register a handler for a specific card id + hook combination."""
    _registry.setdefault(str(card_id), {})[hook] = fn


def register_quick_effect(
    card_id: str,
    hook: str,
    fn: Callable,
    condition_fn: Callable,
    label: str = "",
) -> None:
    """
    Register a quick effect that can be activated outside the owner's turn.

    Parameters
    ----------
    card_id      : str       — card id string (matches metadata id field)
    hook         : str       — hook name to dispatch (e.g. "on_damage_calc")
    fn           : Callable  — handler fn(card, context) -> None
    condition_fn : Callable  — fn(card, game_state) -> bool
                               Return True when the button should be shown.
                               Keep this cheap — it's called every frame.
    label        : str       — button label. Defaults to card_id if blank.

    The handler is also added to the normal _registry under the same hook so
    dispatch() works unchanged when the effect is triggered.

    Example (in a card module)
    --------------------------
        def _condition(card, gs):
            # Only during opponent's attack step
            return (gs.get("active_player") != "player"
                    and gs.get("phase") == "Battle")

        def _handler(card, ctx):
            ...

        register_quick_effect("40640057", "on_damage_calc",
                               _handler, _condition, label="Kuriboh")
    """
    cid = str(card_id)
    register(cid, hook, fn)   # also accessible via normal dispatch()
    entry = _QuickEffectEntry(
        hook=hook,
        fn=fn,
        condition_fn=condition_fn,
        label=label or cid,
    )
    _quick_registry.setdefault(cid, []).append(entry)


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
# Quick effect query
# ---------------------------------------------------------------------------

def get_quick_effects(hand: list, game_state: dict) -> list[QuickEffectEntry]:
    """
    Returns a list of QuickEffectEntry for every hand card that currently
    has at least one activatable quick effect.

    Called every frame during the draw loop — condition_fn must be cheap.

    Parameters
    ----------
    hand       : list of Card objects currently in the player's hand
    game_state : the current game_state dict (forwarded to condition_fn)

    Returns
    -------
    List of QuickEffectEntry namedtuples — one per (card, hook) pair whose
    condition_fn returns True.  A card with two activatable quick effects
    would produce two entries (rare but supported).
    """
    results: list[QuickEffectEntry] = []
    for card in hand:
        card_id = str((getattr(card, "meta", {}) or {}).get("id", ""))
        if not card_id:
            continue
        for entry in _quick_registry.get(card_id, []):
            try:
                if entry.condition_fn(card, game_state):
                    results.append(QuickEffectEntry(
                        card=card,
                        hook=entry.hook,
                        label=entry.label,
                    ))
            except Exception:
                pass   # never crash the draw loop on a bad condition_fn
    return results


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


def has_quick_effect(card) -> bool:
    """Returns True if this card has any registered quick effects."""
    card_id = str((getattr(card, "meta", {}) or {}).get("id", ""))
    return bool(_quick_registry.get(card_id))


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
