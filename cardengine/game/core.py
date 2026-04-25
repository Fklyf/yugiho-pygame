"""
cardengine/game/core.py
------------------
Coordinator between Main.py's event loop and the cardengine subsystems.

Main.py calls exactly two things — nothing else changes:
    action_result = game.submit_action(action, context)
    game.apply_result(action_result, game_objects)

Action types
------------
    "attack"        — one monster attacks another (or direct)
    "summon"        — a card is played from hand / Extra Deck to field
    "activate"      — a spell/trap is activated from hand
    "flip_activate" — a face-down Set spell/trap is flipped and resolved
    "set"           — a card is placed face-down
    "send_to_gy"    — card is destroyed / discarded outside of battle
    "draw"          — active player draws (Draw Phase only, once per turn)

Result dict (always returned by submit_action)
----------------------------------------------
    {
        "ok":               bool,
        "error":            str | None,
        "log":              list[str],
        "send_to_gy":       list[Card],
        "lp_damage": {
            "player":       int,
            "opponent":     int,
        },
        "effect_message":   str | None,
        "summoned_card":    Card | None,
        "draw_count":       int | None,   # spell-effect draws (e.g. Pot of Greed)
    }

Where the logic lives
---------------------
    game_handlers.py  — one _handle_* function per action type
    game_apply.py     — apply_result (LP, GY, field, draws)
    game_helpers.py   — _ok, _err, _name, _safe_remove, _lp_from_result
"""

from __future__ import annotations

from .game_helpers import _err
from .game_handlers import (
    _handle_attack,
    _handle_quick_effect,
    _handle_summon,
    _handle_activate,
    _handle_set,
    _handle_flip_activate,
    _handle_send_to_gy,
    _handle_draw,
)
from .game_apply import apply_result  # re-exported for Main.py


# ---------------------------------------------------------------------------
# Public API — called from Main.py
# ---------------------------------------------------------------------------

_HANDLERS = {
    "attack":        _handle_attack,
    "quick_effect":  _handle_quick_effect,
    "summon":        _handle_summon,
    "activate":      _handle_activate,
    "set":           _handle_set,
    "flip_activate": _handle_flip_activate,
    "send_to_gy":    _handle_send_to_gy,
    "draw":          _handle_draw,
}


def submit_action(action: str, context: dict) -> dict:
    handler = _HANDLERS.get(action)
    if handler is None:
        return _err(f"Unknown action: '{action}'")
    return handler(context)


# ---------------------------------------------------------------------------
# Card effect modules — auto-discovered
# ---------------------------------------------------------------------------
# Every .py file in cardengine/cards/ is imported automatically so its
# register() calls run before submit_action is reachable.
# To add a new card: just drop the file in cards/ — no changes needed here.

import importlib, pkgutil
import cardengine.cards as _cards_pkg

_card_modules = []
for _mod_info in pkgutil.iter_modules(_cards_pkg.__path__):
    importlib.import_module(f"cardengine.cards.{_mod_info.name}")
    _card_modules.append(_mod_info.name)

print(f"[cardengine] Loaded {len(_card_modules)} card module(s): {', '.join(_card_modules)}")
