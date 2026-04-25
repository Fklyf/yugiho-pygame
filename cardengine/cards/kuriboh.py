"""
cardengine/cards/kuriboh.py
---------------------------
Effect implementation for Kuriboh (id: 40640057).

Effect (Quick Effect)
---------------------
    During damage calculation, if your opponent's monster attacks:
    You can discard this card from your hand — you take no battle damage
    from that battle.

Hook used
---------
    on_damage_calc

Context keys READ by this handler
----------------------------------
    activate_kuriboh  : bool  — set True by Main.py when player clicks ⚡
    hand              : list  — the player's current hand (Card objects)
    graveyard         : list  — the player's graveyard (Card objects)

Context keys WRITTEN by this handler
--------------------------------------
    damage            : int   — zeroed out when effect activates
    effect_message    : str   — human-readable log line

Quick-effect condition
----------------------
    Shown (⚡ button) when:
      • It is NOT the player's active turn  (active_player != "player")
      • The current step is "DamageCalc" or phase is "Battle"
      • The card is in the player's hand (guaranteed by get_quick_effects)

Integration in Main.py
-----------------------
When the player clicks the ⚡ button for Kuriboh:

    result = game.submit_action("quick_effect", {
        "card":             kuriboh_card,
        "hook":             "on_damage_calc",
        "activate_kuriboh": True,          # <-- tells this handler to fire
        "hand":             player_hand,
        "graveyard":        player_gy,
        "damage":           pending_damage,
        "damage_target":    "player",
        "game_state":       game_state,
    })
    apply_result(result)

    # After apply_result, read result["damage"] for the (zeroed) damage value
    # and result["effect_message"] for the log string.
"""

from cardengine.effects import register_quick_effect

KURIBOH_ID = "40640057"


# ---------------------------------------------------------------------------
# Condition — when to show the ⚡ button
# ---------------------------------------------------------------------------

def _condition(card, game_state: dict) -> bool:
    """
    Show the Kuriboh quick-effect button when:
      1. It is the opponent's turn (we are the non-active player).
      2. We are in the Battle Phase or specifically at Damage Calculation step.

    game_state keys checked:
        active_player : "player" | "opponent"
        phase         : str  (e.g. "Battle", "Main", "Draw" …)
        step          : str  (optional, e.g. "DamageCalc")
    """
    if game_state.get("active_player") == "player":
        return False   # it's our own turn — can't use as quick effect here

    phase = game_state.get("phase", "")
    step  = game_state.get("step", "")

    return phase == "Battle" or step == "DamageCalc"


# ---------------------------------------------------------------------------
# Handler — what happens when the effect resolves
# ---------------------------------------------------------------------------

def _on_damage_calc(card, context: dict) -> None:
    """
    Zero out battle damage when Kuriboh is discarded during damage calculation.

    The caller (Main.py click handler) is responsible for:
      1. Prompting the player (the ⚡ button IS the prompt).
      2. Setting context["activate_kuriboh"] = True before dispatching.

    This handler is a no-op unless that flag is set, so it is safe to
    dispatch on_damage_calc normally without accidentally triggering it.
    """
    if not context.get("activate_kuriboh"):
        return

    hand: list = context.get("hand", [])
    if card not in hand:
        return   # card isn't actually in hand — refuse silently

    # Discard
    hand.remove(card)
    graveyard: list = context.get("graveyard", [])
    graveyard.append(card)

    # Negate damage
    context["damage"] = 0
    context["effect_message"] = "Kuriboh discarded — battle damage reduced to 0!"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_quick_effect(
    card_id=KURIBOH_ID,
    hook="on_damage_calc",
    fn=_on_damage_calc,
    condition_fn=_condition,
    label="Kuriboh",
)