"""
ui.py — All visual overlay rendering for the YGO field tracker.

Public API
----------
draw_snap_highlight(screen, zones, drag_pos, owner)
draw_field_overlays(screen, zones, player_field, opp_field, mouse_pos)
draw_hud(screen, font, small_font, active_player, turn_number,
         player_deck, opp_deck, player_lp, opp_lp,
         export_flash, hints, lp_edit_target, lp_input_buffer, mouse_pos,
         game_phase)
    → returns (lp_edit_target, lp_input_buffer)

lp_hit_test(mouse_pos, player_lp, opp_lp)
    → "player" | "opponent" | None

phase_btn_hit_test(mouse_pos, game_phase)
    → True | False  (False at End Phase, even if mouse is over the button)
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

# Selection / interaction colours
SEL_BORDER         = (255, 215,   0)   # gold — first selected card
SEL_BORDER_WIDTH   = 3
TARGET_BORDER      = (255,  80,  80)   # red — valid interaction target
TARGET_BORDER_W    = 2
INFO_BG            = ( 15,  15,  30, 210)
INFO_BORDER        = ( 80,  80, 120)

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

# Phase button — sits to the LEFT of the opponent LP box (top-right area),
# vertically aligned with the LP box's top edge so the HUD reads as one row.
PHASE_BTN_BG_IDLE     = ( 40,  70, 120)
PHASE_BTN_BG_HOVER    = ( 70, 110, 170)
PHASE_BTN_BG_DISABLED = ( 60,  60,  60)
PHASE_BTN_FG_IDLE     = (220, 230, 245)
PHASE_BTN_FG_HOVER    = (255, 255, 255)
PHASE_BTN_FG_DISABLED = (140, 140, 140)
PHASE_BTN_BORDER_IDLE     = ( 90, 130, 180)
PHASE_BTN_BORDER_HOVER    = (140, 180, 230)
PHASE_BTN_BORDER_DISABLED = ( 90,  90,  90)

_PHASE_BTN_W   = 150
_PHASE_BTN_H   = 36
_PHASE_BTN_GAP = 12   # horizontal gap between the button and the opp LP box


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


def _phase_btn_rect():
    """
    Top-right strip, immediately left of the opponent LP box.
    Vertically centred against the LP box so the row reads cleanly.
    """
    opp = _opp_lp_rect()
    x = opp.left - _PHASE_BTN_GAP - _PHASE_BTN_W
    y = opp.centery - _PHASE_BTN_H // 2
    return pygame.Rect(x, y, _PHASE_BTN_W, _PHASE_BTN_H)


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
# Public: phase_btn_hit_test
# ---------------------------------------------------------------------------

def phase_btn_hit_test(mouse_pos, game_phase):
    """
    Returns True if the Next-Phase button was clicked AND it's enabled.
    Disabled at End Phase since there's nowhere further to advance —
    the player must press Tab to actually end the turn.
    """
    if game_phase == "End":
        return False
    return _phase_btn_rect().collidepoint(mouse_pos)


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


def _draw_phase_button(screen, font, rect, game_phase, mouse_pos):
    """
    Renders the Next-Phase button at *rect*.

    States:
      • End Phase   → disabled appearance, label flips to "End Phase ▸",
                      no hover effect (see phase_btn_hit_test which also
                      ignores clicks at End so the visual matches behaviour).
      • Hovered     → brighter background and border for affordance.
      • Idle        → muted blue background.
    """
    at_end  = (game_phase == "End")
    hovered = rect.collidepoint(mouse_pos) and not at_end

    if at_end:
        bg, fg, border = (PHASE_BTN_BG_DISABLED,
                          PHASE_BTN_FG_DISABLED,
                          PHASE_BTN_BORDER_DISABLED)
    elif hovered:
        bg, fg, border = (PHASE_BTN_BG_HOVER,
                          PHASE_BTN_FG_HOVER,
                          PHASE_BTN_BORDER_HOVER)
    else:
        bg, fg, border = (PHASE_BTN_BG_IDLE,
                          PHASE_BTN_FG_IDLE,
                          PHASE_BTN_BORDER_IDLE)

    pygame.draw.rect(screen, bg,     rect, border_radius=6)
    pygame.draw.rect(screen, border, rect, width=2, border_radius=6)

    label = "End Phase ▸" if at_end else "Next Phase ▸"
    text  = font.render(label, True, fg)
    screen.blit(text, text.get_rect(center=rect.center))


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
             mouse_pos=(0, 0),
             game_phase="Main 1"):
    """
    Draws the full HUD including turn info, deck counts, hints, export flash,
    the Next-Phase button, and the two LP boxes.

    Returns (lp_edit_target, lp_input_buffer) — unchanged, so Main.py can
    keep mutating them via KEYDOWN events without round-trip confusion.

    game_phase is used by the Next-Phase button for its label/disabled state.
    Defaults to "Main 1" so older callers that don't pass it still render a
    sensible button (just won't reflect actual phase) — update call sites to
    pass the real phase.
    """
    # Turn / active player
    col = HUD_PLAYER_COL if active_player == "player" else HUD_OPPONENT_COL
    screen.blit(font.render(
        f"Turn {turn_number}  │  Active: {active_player.upper()}"
        f"  │  Phase: {game_phase}"
        f"  │  [Tab = end turn, Space = next phase]",
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

    # Next-Phase button (top-right strip, immediately left of opp LP box)
    _draw_phase_button(screen, font, _phase_btn_rect(), game_phase, mouse_pos)

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


# ---------------------------------------------------------------------------
# Public: selection highlight
# ---------------------------------------------------------------------------

def draw_selection_highlight(screen, selected_card, target_card=None,
                              field_cards=None):
    """
    Draws a gold border around the selected card and a red border around
    any valid interaction target (hovered field card when one is selected).

    Call after draw_field_overlays so the highlight sits on top.
    """
    if selected_card and getattr(selected_card, "rect", None):
        pygame.draw.rect(screen, SEL_BORDER, selected_card.rect,
                         SEL_BORDER_WIDTH, border_radius=3)

    if target_card and target_card is not selected_card:
        pygame.draw.rect(screen, TARGET_BORDER, target_card.rect,
                         TARGET_BORDER_W, border_radius=3)


# ---------------------------------------------------------------------------
# Public: card info panel
# ---------------------------------------------------------------------------

def draw_card_info_panel(screen, card, font, small_font):
    """
    Draws a compact info panel in the bottom-left corner showing the
    selected card's name, type, ATK/DEF, and description snippet.
    """
    if card is None:
        return

    meta = getattr(card, "meta", {}) or {}
    name      = meta.get("name", "Unknown")
    card_type = meta.get("type", card.card_type)
    atk       = meta.get("atk")
    def_      = meta.get("def")
    desc      = meta.get("desc", "")
    mode      = getattr(card, "mode", "")

    PAD   = 10
    W     = 320
    H     = 130
    x     = PAD
    y     = SCREEN_SIZE[1] - H - PAD - 54   # sit above the hint bar

    # Background
    bg = pygame.Surface((W, H), pygame.SRCALPHA)
    bg.fill(INFO_BG)
    screen.blit(bg, (x, y))
    pygame.draw.rect(screen, INFO_BORDER, (x, y, W, H), 1, border_radius=5)

    # Name
    name_font = pygame.font.SysFont("Arial", 15, bold=True)
    name_surf = name_font.render(name, True, SEL_BORDER)
    screen.blit(name_surf, (x + PAD, y + PAD))

    # Type + mode
    type_font = pygame.font.SysFont("Arial", 12)
    type_surf = type_font.render(f"{card_type}  [{mode}]", True, (160, 160, 200))
    screen.blit(type_surf, (x + PAD, y + PAD + name_surf.get_height() + 2))

    # ATK / DEF line
    if atk is not None or def_ is not None:
        stat_str  = ""
        if atk is not None: stat_str += f"ATK {atk}"
        if atk is not None and def_ is not None: stat_str += "  /  "
        if def_ is not None: stat_str += f"DEF {def_}"
        stat_surf = type_font.render(stat_str, True, (220, 200, 100))
        screen.blit(stat_surf, (x + PAD, y + PAD + name_surf.get_height() + 18))

    # Description (truncated to fit)
    desc_y   = y + PAD + name_surf.get_height() + 36
    desc_font = pygame.font.SysFont("Arial", 11)
    max_chars = 58
    lines     = []
    words     = desc.split()
    line      = ""
    for word in words:
        test = f"{line} {word}".strip()
        if len(test) <= max_chars:
            line = test
        else:
            lines.append(line)
            line = word
        if len(lines) == 2:
            break
    if line and len(lines) < 2:
        lines.append(line)
    if len(lines) == 2 and len(desc.split()) > len(" ".join(lines).split()):
        lines[-1] = lines[-1][:max_chars - 3] + "..."

    for i, ln in enumerate(lines):
        screen.blit(desc_font.render(ln, True, (170, 170, 170)),
                    (x + PAD, desc_y + i * 14))

# ---------------------------------------------------------------------------
# Public: centre-screen announcements
# ---------------------------------------------------------------------------

# Announcement colour palette
_ANN_SPELL_BG      = (10,  10,  40, 200)   # dark blue — spell/trap
_ANN_SPELL_TITLE   = (180, 140, 255)        # purple-white
_ANN_SPELL_BODY    = (210, 210, 255)
_ANN_DAMAGE_BG     = (40,  10,  10, 200)   # dark red — damage
_ANN_DAMAGE_TITLE  = (255, 120,  80)        # orange-red
_ANN_DAMAGE_BODY   = (255, 200, 180)
_ANN_BORDER_SPELL  = (120,  80, 220)
_ANN_BORDER_DAMAGE = (200,  60,  40)


def draw_announcement(screen, title: str, body_lines: list[str],
                       alpha: int, kind: str = "spell") -> None:
    """
    Renders a centred announcement banner that fades out over time.

    Parameters
    ----------
    screen      : pygame.Surface
    title       : bold headline (e.g. "Dark Magic Attack!")
    body_lines  : list of detail strings shown below the title
    alpha       : 0–255 opacity — pass a value that decrements each frame
    kind        : "spell" (purple) | "damage" (red)

    Usage in Main.py
    ----------------
    # In your game-state locals, keep two values:
    #   announcement        = None | {"title": str, "body": list[str], "kind": str}
    #   announcement_timer  = 0        (frames remaining, e.g. 180 = 3 s at 60 fps)
    #
    # When a spell resolves or damage is dealt:
    #   announcement       = {"title": "Dark Magic Attack!", "body": [...], "kind": "spell"}
    #   announcement_timer = 180
    #
    # Each frame, inside the draw loop:
    #   if announcement_timer > 0:
    #       alpha = min(255, announcement_timer * 4)   # fade out in last ~64 frames
    #       draw_announcement(screen,
    #                         announcement["title"],
    #                         announcement["body"],
    #                         alpha,
    #                         announcement["kind"])
    #       announcement_timer -= 1
    """
    if alpha <= 0:
        return

    if kind == "damage":
        bg_col     = _ANN_DAMAGE_BG
        title_col  = _ANN_DAMAGE_TITLE
        body_col   = _ANN_DAMAGE_BODY
        border_col = _ANN_BORDER_DAMAGE
    else:
        bg_col     = _ANN_SPELL_BG
        title_col  = _ANN_SPELL_TITLE
        body_col   = _ANN_SPELL_BODY
        border_col = _ANN_BORDER_SPELL

    title_font = pygame.font.SysFont("Arial", 32, bold=True)
    body_font  = pygame.font.SysFont("Arial", 18)

    title_surf = title_font.render(title, True, title_col)
    body_surfs = [body_font.render(ln, True, body_col) for ln in body_lines]

    PAD    = 24
    W      = max(title_surf.get_width(), *(s.get_width() for s in body_surfs),
                 300) + PAD * 2
    H      = (PAD
              + title_surf.get_height() + 8
              + sum(s.get_height() + 4 for s in body_surfs)
              + PAD)

    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    x      = cx - W // 2
    y      = cy - H // 2

    bg = pygame.Surface((W, H), pygame.SRCALPHA)
    bg.fill((*bg_col[:3], min(alpha, bg_col[3])))
    screen.blit(bg, (x, y))

    border_surf = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.rect(border_surf, (*border_col, alpha), (0, 0, W, H), 2, border_radius=8)
    screen.blit(border_surf, (x, y))

    # Title
    title_surf.set_alpha(alpha)
    screen.blit(title_surf, (cx - title_surf.get_width() // 2, y + PAD))

    # Body lines
    ty = y + PAD + title_surf.get_height() + 8
    for surf in body_surfs:
        surf.set_alpha(alpha)
        screen.blit(surf, (cx - surf.get_width() // 2, ty))
        ty += surf.get_height() + 4