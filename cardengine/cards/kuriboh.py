"""
cardengine/cards/kuriboh.py
---------------------------
Effect implementation for Kuriboh (id: 40640057).

Effect:
    During damage calculation, if your opponent's monster attacks
    (Quick Effect): You can discard this card; you take no battle damage
    from that battle.

Hook used: on_damage_calc
    context keys read:
        "damage"        (int)   — damage about to be applied
        "damage_target" (str)   — "player" | "opponent"
        "hand"          (list)  — the defending player's hand
    context keys written:
        "damage"                — set to 0 if effect activates
        "effect_message"        — human-readable log string
"""

from cardengine.effects import register

KURIBOH_ID = "40640057"


def _on_damage_calc(card, context: dict):
    """
    Zero out battle damage when Kuriboh is discarded during damage calc.

    The caller is responsible for:
      1. Checking the player actually WANTS to activate (prompt logic lives
         outside the engine — this just applies the effect if flagged).
      2. Setting context["activate_kuriboh"] = True before dispatching.
    """
    if not context.get("activate_kuriboh"):
        return

    hand: list = context.get("hand", [])
    if card not in hand:
        return  # Card isn't actually in hand

    # Discard the card
    hand.remove(card)
    graveyard: list = context.get("graveyard", [])
    graveyard.append(card)

    # Negate the damage
    context["damage"] = 0
    context["effect_message"] = "Kuriboh discarded — battle damage reduced to 0!"


register(KURIBOH_ID, "on_damage_calc", _on_damage_calc)
