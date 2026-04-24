"""
cardengine/cards/buster_blader.py
----------------------------------
Effect implementation for Buster Blader (id: 78193831).

Effect:
    Gains 500 ATK for each Dragon monster your opponent controls or is
    in their GY.

Hook used: continuous_atk_mod
"""

from cardengine.effects import register

BB_ID    = "78193831"
_BOOST   = 500


def _continuous_atk_mod(card, context: dict) -> int:
    game_state  = context.get("game_state", {})
    opp         = game_state.get("opponent", {})

    count = 0

    # Opponent's field
    for c in opp.get("field", []):
        card_type = (c.get("type", "") if isinstance(c, dict)
                     else (getattr(c, "meta", {}) or {}).get("type", ""))
        if "Dragon" in card_type:
            count += 1

    # Opponent's graveyard
    for c in opp.get("graveyard", []):
        card_type = (c.get("type", "") if isinstance(c, dict)
                     else (getattr(c, "meta", {}) or {}).get("type", ""))
        if "Dragon" in card_type:
            count += 1

    return count * _BOOST


register(BB_ID, "continuous_atk_mod", _continuous_atk_mod)
