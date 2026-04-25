"""
attempt_set_card — Set a hand card face-down on the active player's field.

Returns True if the gesture was consumed (success OR rule-block with a
clear printed reason), False if the gesture wasn't applicable (e.g. wrong
player clicked, so the caller should fall through to other handlers).

High-level monsters cannot be Set directly through this flow — the user
must Normal Summon them first and cycle to SET position via RMB.
"""

from config import SCREEN_SIZE
from cardengine import rules
from cardengine.game import submit_action, apply_result

from ..geometry import reposition_field_card
from ..state import build_game_state


def attempt_set_card(
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
    zones=None,
    zoom_level=1.0,
    cam_offset=(0, 0),
) -> bool:
    if owner != active_player:
        print("[Blocked] You can only Set your own cards on your turn.")
        return True  # "handled" — don't fall through

    my_field = player_field if owner == "player" else opp_field

    gs = build_game_state(
        player_hand, player_field, player_gy,
        opp_hand,    opp_field,    opp_gy,
        len(player_deck), len(opp_deck),
        player_lp[0], opp_lp[0],
        turn_number, active_player,
        game_phase, has_drawn_this_turn,
        has_summoned_this_turn,
    )
    # Surface turn number at top level for can_flip_activate
    gs["turn"] = turn_number

    meta = getattr(card, "meta", {}) or {}
    card_type = str(meta.get("type", card.card_type))
    needs_tributes = ("Monster" in card_type) and rules.tributes_required(card) > 0

    if needs_tributes:
        # We route high-level Set through the normal-summon + toggle_position
        # flow instead of forking tributes.
        print(f"[Set] High-level monsters can't be Set directly in this flow. "
              f"Summon first, then cycle to SET position via RMB.")
        return True

    # ── Find a free zone on owner's side BEFORE the engine places the card.
    # Mirrors what attempt_tribute_summon does so apply_result's reposition
    # step has sensible world_x / world_y values to work with.
    if zones is not None:
        is_spell_or_trap = ("Spell" in card_type or "Trap" in card_type)
        zone_prefix = ("P_S/T" if is_spell_or_trap else "P_M") \
                      if owner == "player" \
                      else ("O_S/T" if is_spell_or_trap else "O_M")
        cx, cy   = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
        cam_x, cam_y = cam_offset
        placed = False
        for i in range(1, 6):
            zn = f"{zone_prefix}{i}"
            if zn in zones and not any(
                    getattr(fc, "zone_name", None) == zn for fc in my_field):
                z_rect = zones[zn]
                card.world_x   = (z_rect.centerx - cx) / zoom_level - cam_x
                card.world_y   = (z_rect.centery - cy) / zoom_level - cam_y
                card.zone_name = zn
                placed = True
                break
        if not placed:
            print(f"[Blocked] No free {'Spell/Trap' if is_spell_or_trap else 'Monster'} zone.")
            return True

    # Detach card from hand BEFORE submit_action — same pattern as
    # attempt_tribute_summon. Without these resets, the Hand layout pass
    # next frame still treats the card as a hand card (in_hand=True) and
    # repositions its rect to wherever the hand layout puts it, which looks
    # like the Set card "snapping to a random spot" on the field.
    my_hand = player_hand if owner == "player" else opp_hand
    my_hand.remove_card(card)
    card.in_hand     = False
    card.is_dragging = False
    card.angle       = 0
    card.owner       = owner

    result = submit_action("set", {
        "card":           card,
        "owner":          owner,
        "field_monsters": my_field,    # full field list — game.py splits by type
        "tributes":       [],
        "game_state":     gs,
    })
    apply_result(result, game_objects)
    for msg in result.get("log", []):
        print(f"[Set] {msg}")
    if not result.get("ok"):
        print(f"[Blocked] {result.get('error')}")
        # Undo zone placement so the rejected card doesn't keep stale coords,
        # and return the card to the hand it came from.
        card.zone_name = None
        card.in_hand   = True
        my_hand.add_card(card)
        return True

    # Refresh visuals for the newly placed face-down card
    if hasattr(card, "update_visuals"):
        card.update_visuals(zoom_level)
    reposition_field_card(card, zoom_level, cam_offset)

    # Mirror Normal Summon's once-per-turn budget for Set monsters.
    if "Monster" in card_type:
        game_objects["has_summoned_this_turn"] = True

    return True
