"""
attempt_flip_activate — flip a face-down Set Spell/Trap face-up and resolve
its effect.

Monsters are NOT flipped here — toggle_position handles ATK/DEF/SET cycling
for monsters elsewhere (it lives on the Card class).

Returns True if the gesture was consumed (success OR rule-block with a
printed reason), False if the gesture wasn't applicable (caller should
fall through).
"""

from cardengine.game import submit_action, apply_result

from ..announcements import arm_announcement
from ..helpers import safe_remove
from ..state import build_game_state


def attempt_flip_activate(
    card, owner, active_player,
    player_field, opp_field,
    player_hand,  opp_hand,
    player_lp,    opp_lp,
    player_gy,    opp_gy,
    game_objects,
    player_deck,  opp_deck,
    turn_number,
    game_phase,
    has_drawn_this_turn,
    has_summoned_this_turn,
) -> bool:
    if owner != active_player:
        print("[Blocked] You can only activate your own cards on your turn.")
        return True

    meta = getattr(card, "meta", {}) or {}
    card_type = str(meta.get("type", card.card_type))
    if "Monster" in card_type:
        return False   # Not our job — let position toggle handle it

    card.owner = owner
    gs = build_game_state(
        player_hand, player_field, player_gy,
        opp_hand,    opp_field,    opp_gy,
        len(player_deck), len(opp_deck),
        player_lp[0], opp_lp[0],
        turn_number, active_player,
        game_phase, has_drawn_this_turn,
        has_summoned_this_turn,
    )
    gs["turn"] = turn_number

    result = submit_action("flip_activate", {
        "card":          card,
        "owner":         owner,
        "active_player": active_player,
        "targets":       [],
        "game_state":    gs,
        "player_field":  player_field,
        "opp_field":     opp_field,
    })
    apply_result(result, game_objects)
    for msg in result.get("log", []):
        print(f"[Flip] {msg}")

    if not result.get("ok"):
        print(f"[Blocked] {result.get('error')}")
        return True

    # Announcement
    ann_state = game_objects.get("ann_state", [None, 0])
    arm_announcement(result, ann_state)
    game_objects["ann_state"] = ann_state

    # Normal Spells and Traps go to GY after resolving. Continuous/Equip/Field
    # Spells stay on the field face-up.
    is_persistent = any(kw in card_type for kw in
                        ("Continuous", "Equip", "Field"))
    is_trap_card  = "Trap" in card_type
    is_normal_spell = ("Spell" in card_type) and not is_persistent
    if is_normal_spell or is_trap_card:
        # Pull off field list and drop in GY
        safe_remove(player_field, card)
        safe_remove(opp_field,    card)
        gy = player_gy if owner == "player" else opp_gy
        gy.add_card(card)

    return True
