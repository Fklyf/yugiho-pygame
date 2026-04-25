"""
attempt_tribute_summon — finalise a high-level monster summon after the
required tributes have been picked.

This is called by hand.resolve_hand_action and field.resolve_interaction
once tribute selection is complete (or by the drag-tribute fast-path in
game_loop, which preselects a single drop-target tribute).

The function:
  1. Pulls the summon card from hand and stamps owner.
  2. Stamps owner on the tributes so apply_result routes them to the right GY.
  3. Submits the "summon" action to cardengine.
  4. On success, locates a free monster zone for placement and refreshes
     the card's visuals.
  5. Resets the shared tribute selection state.
"""

from config import SCREEN_SIZE
from cardengine.game import submit_action, apply_result

from .. import tribute
from ..geometry import try_snap, reposition_field_card


def attempt_tribute_summon(
    summon_card, summon_owner,
    tributes,
    player_field, opp_field,
    player_hand,  opp_hand,
    gs, game_objects,
):
    my_hand  = player_hand  if summon_owner == "player" else opp_hand
    my_field = player_field if summon_owner == "player" else opp_field

    # Remove summon card from hand BEFORE submit_action.
    # apply_result also calls remove_card but if the hand has already
    # repositioned visually it can silently no-op, leaving the card in
    # both hand and field at the same time.
    my_hand.remove_card(summon_card)
    summon_card.in_hand     = False
    summon_card.is_dragging = False
    summon_card.angle       = 0
    summon_card.owner       = summon_owner

    # Stamp owner on tributes so apply_result routes them to the right GY.
    for t in tributes:
        t.owner = summon_owner

    # Rebuild gs so has_summoned_this_turn is current — the gs passed in
    # was snapshotted at the first tribute click and may be stale.
    fresh_gs = dict(gs)
    fresh_gs["has_summoned_this_turn"] = game_objects.get("has_summoned_this_turn", False)

    result = submit_action("summon", {
        "card":           summon_card,
        "owner":          summon_owner,
        "field_monsters": my_field,
        "tributes":       tributes,
        "game_state":     fresh_gs,
    })

    apply_result(result, game_objects)

    for msg in result.get("log", []):
        print(f"[Summon] {msg}")

    if not result.get("ok"):
        print(f"[Blocked] {result.get('error')}")
        # Summon failed — return card to hand; tributes stay on field
        summon_card.in_hand = True
        my_hand.add_card(summon_card)
    else:
        # Position the summoned card on screen — find the first free monster
        # zone for this owner so the card doesn't land between zones.
        zoom_level = game_objects.get("zoom_level", 1.0)
        cam_offset = game_objects.get("cam_offset", (0, 0))
        zones      = game_objects.get("zones", {})
        cam_x, cam_y = cam_offset
        cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2

        prefix = "P_M" if summon_owner == "player" else "O_M"
        placed = False
        for i in range(1, 6):
            zn = f"{prefix}{i}"
            if zn in zones and not any(
                    getattr(fc, "zone_name", None) == zn
                    for fc in my_field):
                z_rect = zones[zn]
                summon_card.world_x   = (z_rect.centerx - cx) / zoom_level - cam_x
                summon_card.world_y   = (z_rect.centery - cy) / zoom_level - cam_y
                summon_card.zone_name = zn
                placed = True
                break

        if not placed:
            # All zones occupied — fall back to a snapped position
            default_screen_x = SCREEN_SIZE[0] // 2
            default_screen_y = (cy + 120) if summon_owner == "player" else (cy - 120)
            try_snap(summon_card, (default_screen_x, default_screen_y),
                     zones, zoom_level, cam_offset, summon_owner)

        summon_card.update_visuals(zoom_level)
        reposition_field_card(summon_card, zoom_level, cam_offset)
        game_objects["has_summoned_this_turn"] = True

    tribute.reset()
