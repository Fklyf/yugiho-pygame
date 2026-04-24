"""
cardengine/__init__.py
----------------------
Card logic engine for YGO Field Tracker.

Structure
---------
cardengine/
    battle.py       — Generic ATK/DEF resolution and damage calculation
    effects.py      — Effect hook registry and dispatcher
    rules.py        — Summon legality, attack legality, targeting rules
    cards/          — One file per card with custom effect logic
        __init__.py     (auto-imports all card modules)
        kuriboh.py
        dark_magician_girl.py
        buster_blader.py
        ...

Quick-start
-----------
Import the engine once at game startup to register all card effects:

    import cardengine          # triggers cardengine/cards auto-import

Then in your game loop:

    from cardengine.battle  import resolve_attack
    from cardengine.effects import dispatch, get_atk_modifier
    from cardengine.rules   import can_attack, can_normal_summon

Adding a new card
-----------------
1.  Create cardengine/cards/<card_name>.py
2.  Import `register` from cardengine.effects
3.  Call register(card_id, hook_name, handler_fn)
4.  Done — the auto-importer picks it up.

Adding a metadata flag
----------------------
In metadata.json add an "effects" list to the card:

    "effects": ["on_discard", "continuous_atk_mod"]

This is informational only (the engine uses id-based registration), but it
lets you query which hooks a card participates in without importing all modules.
"""

# Auto-register all card-specific effect modules
import importlib as _importlib
_importlib.import_module("cardengine.cards")