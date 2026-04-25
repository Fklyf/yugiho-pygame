"""
main.gestures — per-gesture resolver functions.

Each module here translates one kind of player gesture (LMB drag-drop,
RMB select-then-target, double-click, etc.) into one or more calls to
the card engine (cardengine.game.submit_action / apply_result).

NOTE on naming: the card engine speaks in terms of "actions" (summon,
attack, activate, draw, set, flip_activate, quick_effect — see
cardengine.game.submit_action).  The functions here are NOT those —
they're the upstream layer that decides which engine action a click
or drag means.  Calling this subpackage `actions` would clash with the
engine's vocabulary, so it's `gestures`.

Public entry points:

    tribute_summon.attempt_tribute_summon
    hand.resolve_hand_action            — selected hand card → target click
    field.resolve_interaction           — selected field card → field card
    direct_attack.attempt_direct_attack — friendly monster vs empty field
    set_card.attempt_set_card           — Set a card face-down
    flip_activate.attempt_flip_activate — flip a Set Spell/Trap face-up

The game loop in main/game_loop.py is the only caller — it dispatches
to whichever resolver matches the current gesture.
"""
