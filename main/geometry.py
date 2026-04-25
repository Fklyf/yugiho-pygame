"""
Coordinate helpers — translate between world coords, screen coords, and zones.

Functions
─────────
  try_snap                If a drop position is close enough to a legal zone
                          centre, snap the card into it.
  reposition_field_card   Recompute a single field card's screen rect from
                          its world coords + camera/zoom.
  reposition_all_field_cards
                          Same, for a whole list (used after pan/zoom).
  is_own_side_click       True if a screen position is on the active
                          player's half of the field.
"""

from config import SCREEN_SIZE, SNAP_RADIUS

from .constants import PLAYER_ZONES, OPPONENT_ZONES


def try_snap(card, drop_screen_pos, zones, zoom_level, cam_offset, owner):
    """
    If the drop position is within SNAP_RADIUS of an eligible zone centre,
    snaps the card to that zone and returns (True, snapped_rect).
    Returns (False, None) otherwise.
    """
    cx, cy  = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    legal   = PLAYER_ZONES if owner == "player" else OPPONENT_ZONES
    dx, dy  = drop_screen_pos

    best_dist = float("inf")
    best_zone = None
    best_rect = None

    for name, z_rect in zones.items():
        if name not in legal:
            continue
        dist = ((dx - z_rect.centerx) ** 2 + (dy - z_rect.centery) ** 2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_zone = name
            best_rect = z_rect

    if best_zone is None or best_dist > SNAP_RADIUS:
        return False, None

    card.world_x   = (best_rect.centerx - cx) / zoom_level - cam_offset[0]
    card.world_y   = (best_rect.centery - cy) / zoom_level - cam_offset[1]
    card.zone_name = best_zone
    return True, best_rect


def reposition_field_card(card, zoom_level, cam_offset):
    """Recompute *card*'s screen rect from its world coords + camera/zoom."""
    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    cam_x, cam_y = cam_offset
    card.rect.centerx = int(cx + (card.world_x + cam_x) * zoom_level)
    card.rect.centery = int(cy + (card.world_y + cam_y) * zoom_level)


def reposition_all_field_cards(field_cards, zoom_level, cam_offset):
    """Reposition every card in *field_cards* — used after pan/zoom."""
    for c in field_cards:
        reposition_field_card(c, zoom_level, cam_offset)


def is_own_side_click(pos, active_player, zones) -> bool:
    """
    True if *pos* (screen coords) is on the active player's half of the field.

    Accepts either:
      • A click inside a named zone belonging to the active player
        (P_M*, P_S/T*, P_Field for player; O_* for opponent), or
      • A click on the lower half of the screen for the player, upper half
        for the opponent. Opponent is always drawn on top.
    """
    clicked_zone_name = next(
        (n for n, r in zones.items() if r.collidepoint(pos)), None)
    if clicked_zone_name is not None:
        prefix = "P_" if active_player == "player" else "O_"
        return clicked_zone_name.startswith(prefix)

    click_y = pos[1]
    screen_mid = SCREEN_SIZE[1] // 2
    if active_player == "player":
        return click_y >= screen_mid
    return click_y < screen_mid
