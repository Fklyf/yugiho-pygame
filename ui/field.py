"""
ui/field.py
-----------
Field-level rendering: snap highlight, card overlays, selection borders.

Public API
----------
draw_snap_highlight(screen, zones, drag_pos, owner)
draw_field_overlays(screen, zones, player_field, opp_field, mouse_pos)
draw_selection_highlight(screen, selected_card, target_card=None,
                         field_cards=None)
"""

import math
import pygame
from ui.constants import (
    SCREEN_SIZE, SNAP_RADIUS,
    PLAYER_ZONES, OPPONENT_ZONES,
    SNAP_FILL, SNAP_BORDER,
    DEF_BORDER, DEF_BORDER_WIDTH,
    HOVER_FILL, HOVER_BORDER, HOVER_BORDER_WIDTH,
    SEL_BORDER, SEL_BORDER_WIDTH,
    TARGET_BORDER, TARGET_BORDER_W,
)

# SNAP_RADIUS lives in config but is re-exported via constants — if your
# constants.py doesn't import it, import directly:
try:
    from ui.constants import SNAP_RADIUS  # noqa
except ImportError:
    from config import SNAP_RADIUS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rotated_rect_points(rect, angle_deg):
    cx, cy = rect.centerx, rect.centery
    hw, hh = rect.width / 2, rect.height / 2
    rad    = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [(cx + lx*cos_a - ly*sin_a, cy + lx*sin_a + ly*cos_a)
            for lx, ly in corners]


def _card_is_sideways(card):
    return (not card.in_hand
            and "Monster" in card.card_type
            and card.mode in ("DEF", "SET"))


# ---------------------------------------------------------------------------
# Public draw calls
# ---------------------------------------------------------------------------

def draw_snap_highlight(screen, zones, drag_pos, owner):
    """Highlights the nearest snap zone while a card is being dragged."""
    legal  = PLAYER_ZONES if owner == "player" else OPPONENT_ZONES
    dx, dy = drag_pos
    for name, z_rect in zones.items():
        if name not in legal:
            continue
        if math.hypot(dx - z_rect.centerx, dy - z_rect.centery) < SNAP_RADIUS:
            hl = pygame.Surface((z_rect.width, z_rect.height), pygame.SRCALPHA)
            hl.fill(SNAP_FILL)
            screen.blit(hl, z_rect.topleft)
            pygame.draw.rect(screen, SNAP_BORDER, z_rect, 2)


def draw_field_overlays(screen, zones, player_field, opp_field, mouse_pos):
    """
    Draws DEF/SET rotation outlines and hover highlight+tooltip for field cards.
    """
    mx, my = mouse_pos

    zoned = {}
    for c in player_field + opp_field:
        zn = getattr(c, "zone_name", None)
        if zn:
            zoned[zn] = c

    # Rotated outlines for DEF/SET monsters
    for zone_name, card in zoned.items():
        if not _card_is_sideways(card):
            continue
        z_rect = zones.get(zone_name)
        if z_rect:
            pygame.draw.polygon(screen, DEF_BORDER,
                                _rotated_rect_points(z_rect, 90),
                                DEF_BORDER_WIDTH)

    # Hover highlight + tooltip
    hovered = None
    for c in reversed(player_field + opp_field):
        if c.rect.collidepoint(mx, my):
            hovered = c
            break

    if hovered:
        hl = pygame.Surface((hovered.rect.width, hovered.rect.height), pygame.SRCALPHA)
        hl.fill(HOVER_FILL)
        screen.blit(hl, hovered.rect.topleft)
        pygame.draw.rect(screen, HOVER_BORDER, hovered.rect, HOVER_BORDER_WIDTH)

        name     = (getattr(hovered, "meta", {}) or {}).get("name", "Unknown")
        tip_font = pygame.font.SysFont("Arial", 14)
        tip_text = tip_font.render(f"{name}  [{hovered.mode}]", True, (220, 220, 255))
        tx = max(0, min(hovered.rect.centerx - tip_text.get_width() // 2,
                        SCREEN_SIZE[0] - tip_text.get_width()))
        ty = max(0, hovered.rect.top - tip_text.get_height() - 4)
        screen.blit(tip_text, (tx, ty))


def draw_selection_highlight(screen, selected_card, target_card=None,
                              field_cards=None):
    """
    Gold border around the selected card; red border around the hover target.
    Call after draw_field_overlays so the highlight sits on top.
    """
    if selected_card and getattr(selected_card, "rect", None):
        pygame.draw.rect(screen, SEL_BORDER, selected_card.rect,
                         SEL_BORDER_WIDTH, border_radius=3)

    if target_card and target_card is not selected_card:
        pygame.draw.rect(screen, TARGET_BORDER, target_card.rect,
                         TARGET_BORDER_W, border_radius=3)
