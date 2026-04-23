"""
ui.py — All visual overlay rendering for the YGO field tracker.

Public API
----------
draw_snap_highlight(screen, zones, drag_pos, owner)
draw_field_overlays(screen, zones, player_field, opp_field, mouse_pos)
draw_hud(screen, font, small_font, active_player, turn_number,
         player_deck, opp_deck, player_lp, opp_lp,
         export_flash, hints, lp_edit_target, lp_input_buffer, mouse_pos)
    → returns (lp_edit_target, lp_input_buffer)

lp_hit_test(mouse_pos, player_lp, opp_lp)
    → "player" | "opponent" | None
"""

import math
import pygame
from config import SCREEN_SIZE, SNAP_RADIUS

# ---------------------------------------------------------------------------
# Zone sets
# ---------------------------------------------------------------------------
PLAYER_ZONES   = ({f"P_M{i}"   for i in range(1, 6)} |
                  {f"P_S/T{i}" for i in range(1, 6)} |
                  {"P_Field"})
OPPONENT_ZONES = ({f"O_M{i}"   for i in range(1, 6)} |
                  {f"O_S/T{i}" for i in range(1, 6)} |
                  {"O_Field"})

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
SNAP_FILL          = (220, 200,  80,  55)
SNAP_BORDER        = (220, 200,  80, 255)
DEF_BORDER         = ( 80, 160, 220, 255)
DEF_BORDER_WIDTH   = 2
HOVER_FILL         = (255, 255, 255,  25)
HOVER_BORDER       = (200, 200, 255, 200)
HOVER_BORDER_WIDTH = 2
HUD_PLAYER_COL     = ( 80, 180,  80)
HUD_OPPONENT_COL   = (180,  80,  80)
HUD_DECK_COL       = (160, 160, 160)
HUD_HINT_COL       = ( 80,  80, 100)
HUD_EXPORT_COL     = (100, 220, 100)

# LP widget colours
LP_BOX_PLAYER_IDLE   = ( 30,  55,  30)
LP_BOX_PLAYER_HOVER  = ( 45,  80,  45)
LP_BOX_OPP_IDLE      = ( 55,  30,  30)
LP_BOX_OPP_HOVER     = ( 80,  45,  45)
LP_BOX_ACTIVE_FILL   = ( 20,  20,  50)
LP_BOX_BORDER_IDLE   = (100, 100, 100)
LP_BOX_BORDER_ACTIVE = (200, 200,  80)
LP_TEXT_NORMAL       = (220, 220, 220)
LP_TEXT_LOW          = (220,  80,  80)
LP_LABEL_COL         = (140, 140, 140)
LP_CURSOR_COL        = (220, 220,  80)

_LP_BOX_W  = 200
_LP_BOX_H  = 60
_LP_MARGIN = 14
_LP_PAD    = 10


# ---------------------------------------------------------------------------
# LP box rects
# ---------------------------------------------------------------------------

def _player_lp_rect():
    x = SCREEN_SIZE[0] - _LP_BOX_W - _LP_MARGIN
    y = SCREEN_SIZE[1] - _LP_BOX_H - _LP_MARGIN
    return pygame.Rect(x, y, _LP_BOX_W, _LP_BOX_H)


def _opp_lp_rect():
    x = SCREEN_SIZE[0] - _LP_BOX_W - _LP_MARGIN
    y = _LP_MARGIN
    return pygame.Rect(x, y, _LP_BOX_W, _LP_BOX_H)


# ---------------------------------------------------------------------------
# Public: lp_hit_test
# ---------------------------------------------------------------------------

def lp_hit_test(mouse_pos, player_lp, opp_lp):
    """Returns 'player', 'opponent', or None based on which LP box was clicked."""
    if _player_lp_rect().collidepoint(mouse_pos):
        return "player"
    if _opp_lp_rect().collidepoint(mouse_pos):
        return "opponent"
    return None


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


def _draw_lp_box(screen, rect, label, lp_value,
                 is_active, is_hovered, lp_input_buffer,
                 idle_fill, hover_fill):
    """Renders one LP box — idle, hovered, or actively being edited."""
    if is_active:
        fill   = LP_BOX_ACTIVE_FILL
        border = LP_BOX_BORDER_ACTIVE
    elif is_hovered:
        fill   = hover_fill
        border = LP_BOX_BORDER_ACTIVE
    else:
        fill   = idle_fill
        border = LP_BOX_BORDER_IDLE

    bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    bg.fill((*fill, 210))
    screen.blit(bg, rect.topleft)
    pygame.draw.rect(screen, border, rect, 2, border_radius=6)

    lp_font    = pygame.font.SysFont("Arial", 22, bold=True)
    label_font = pygame.font.SysFont("Arial", 11)
    hint_font  = pygame.font.SysFont("Arial", 11)

    # Label row
    label_surf = label_font.render(label, True, LP_LABEL_COL)
    screen.blit(label_surf, (rect.x + _LP_PAD, rect.y + 5))

    # Value / input row
    if is_active:
        display = lp_input_buffer + "|"
        col     = LP_CURSOR_COL
    else:
        display = f"{lp_value:,}"
        col     = LP_TEXT_LOW if lp_value <= 1000 else LP_TEXT_NORMAL

    val_surf = lp_font.render(display, True, col)
    vx = rect.right - _LP_PAD - val_surf.get_width()
    vy = rect.bottom - _LP_PAD - val_surf.get_height()
    screen.blit(val_surf, (vx, vy))

    # "click to edit" hint on hover (not while editing)
    if is_hovered and not is_active:
        hint = hint_font.render("click to edit  •  Enter to confirm", True, (120, 120, 120))
        screen.blit(hint, (rect.x + _LP_PAD, vy + 2))


# ---------------------------------------------------------------------------
# Public draw calls
# ---------------------------------------------------------------------------

def draw_snap_highlight(screen, zones, drag_pos, owner):
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

    # Hover highlight
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


def draw_hud(screen, font, small_font,
             active_player, turn_number,
             player_deck, opp_deck,
             player_lp, opp_lp,
             export_flash, hints,
             lp_edit_target, lp_input_buffer,
             mouse_pos=(0, 0)):
    """
    Draws the full HUD including turn info, deck counts, hints, export flash,
    and the two LP boxes.

    Returns (lp_edit_target, lp_input_buffer) — unchanged, so Main.py can
    keep mutating them via KEYDOWN events without round-trip confusion.
    """
    # Turn / active player
    col = HUD_PLAYER_COL if active_player == "player" else HUD_OPPONENT_COL
    screen.blit(font.render(
        f"Turn {turn_number}  │  Active: {active_player.upper()}"
        f"  │  [Tab = end turn]",
        True, col), (10, 10))

    # Deck counts
    screen.blit(small_font.render(
        f"Player deck: {len(player_deck)}    Opponent deck: {len(opp_deck)}",
        True, HUD_DECK_COL), (10, 34))

    # Hint bar
    for i, h in enumerate(hints):
        screen.blit(small_font.render(h, True, HUD_HINT_COL),
                    (10, SCREEN_SIZE[1] - 18 * (len(hints) - i)))

    # Export flash
    if export_flash > 0:
        fs = small_font.render("✓  game_state.json saved", True, HUD_EXPORT_COL)
        fs.set_alpha(min(255, export_flash * 4))
        screen.blit(fs, (10, 56))

    # LP boxes
    p_rect    = _player_lp_rect()
    o_rect    = _opp_lp_rect()
    p_hovered = p_rect.collidepoint(mouse_pos)
    o_hovered = o_rect.collidepoint(mouse_pos)

    _draw_lp_box(
        screen, p_rect,
        label="YOUR LIFE POINTS",
        lp_value=player_lp,
        is_active=(lp_edit_target == "player"),
        is_hovered=p_hovered,
        lp_input_buffer=lp_input_buffer,
        idle_fill=LP_BOX_PLAYER_IDLE,
        hover_fill=LP_BOX_PLAYER_HOVER,
    )
    _draw_lp_box(
        screen, o_rect,
        label="OPPONENT LIFE POINTS",
        lp_value=opp_lp,
        is_active=(lp_edit_target == "opponent"),
        is_hovered=o_hovered,
        lp_input_buffer=lp_input_buffer,
        idle_fill=LP_BOX_OPP_IDLE,
        hover_fill=LP_BOX_OPP_HOVER,
    )

    return lp_edit_target, lp_input_buffer