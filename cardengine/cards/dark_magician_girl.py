"""
cardengine/cards/dark_magician_girl.py
--------------------------------------
Effect implementation for Dark Magician Girl (id: 38033121).

Effect:
    Gains 300 ATK for every "Dark Magician" or "Magician of Black Chaos"
    in either GY.

Hook used: continuous_atk_mod
    context keys read:
        "game_state"  — full game state dict (player/opponent graveyards)
    Returns:
        int — ATK bonus to add on top of base 2000
"""

from cardengine.effects import register

DMG_ID = "38033121"

_BOOST_NAMES = {"Dark Magician", "Magician of Black Chaos"}
_BOOST_PER   = 300


def _continuous_atk_mod(card, context: dict) -> int:
    game_state = context.get("game_state", {})

    count = 0
    for side in ("player", "opponent"):
        gy_cards = game_state.get(side, {}).get("graveyard", [])
        for c in gy_cards:
            name = (c.get("name") if isinstance(c, dict)
                    else (getattr(c, "meta", {}) or {}).get("name", ""))
            if name in _BOOST_NAMES:
                count += 1

    return count * _BOOST_PER


register(DMG_ID, "continuous_atk_mod", _continuous_atk_mod)
