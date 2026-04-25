"""
ui/hud.py
---------
HUD rendering: turn info, deck counts, hint bar, Next-Phase button,
LP boxes, and their hit-tests.

Public API
----------
draw_hud(screen, font, small_font, active_player, turn_number,
         player_deck, opp_deck, player_lp, opp_lp,
         export_flash, hints, lp_edit_target, lp_input_buffer,
         mouse_pos, game_phase)
    → returns (lp_edit_target, lp_input_buffer)

lp_hit_test(mouse_pos, player_lp, opp_lp)
    → "player" | "opponent" | None

phase_btn_hit_test(mouse_pos, game_phase)
    → True | False
"""

import pygame
from ui.constants import (
    SCREEN_SIZE,
    HUD_PLAYER_COL, HUD_OPPONENT_COL, HUD_DECK_COL, HUD_HINT_COL, HUD_EXPORT_COL,
    QE_ICON,
    LP_BOX_PLAYER_IDLE, LP_BOX_PLAYER_HOVER,
    LP_BOX_OPP_IDLE, LP_BOX_OPP_HOVER,
    LP_BOX_ACTIVE_FILL, LP_BOX_BORDER_IDLE, LP_BOX_BORDER_ACTIVE,
    LP_TEXT_NORMAL, LP_TEXT_LOW, LP_LABEL_COL, LP_CURSOR_COL,
    _LP_BOX_W, _LP_BOX_H, _LP_MARGIN, _LP_PAD,
    PHASE_BTN_BG_IDLE, PHASE_BTN_BG_HOVER, PHASE_BTN_BG_DISABLED,
    PHASE_BTN_FG_IDLE, PHASE_BTN_FG_HOVER, PHASE_BTN_FG_DISABLED,
    PHASE_BTN_BORDER_IDLE, PHASE_BTN_BORDER_HOVER, PHASE_BTN_BORDER_DISABLED,
    _PHASE_BTN_W, _PHASE_BTN_H, _PHASE_BTN_GAP,
)


# ---------------------------------------------------------------------------
# Rect helpers
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
    opp = _opp_lp_rect()
    x   = opp.left - _PHASE_BTN_GAP - _PHASE_BTN_W
    y   = opp.centery - _PHASE_BTN_H // 2
    return pygame.Rect(x, y, _PHASE_BTN_W, _PHASE_BTN_H)


# QE panel button colours (self-contained here)
_QE_BTN_W             = 160
_QE_BTN_H             = 36
_QE_BTN_BG_ACTIVE     = ( 50,  20, 110)
_QE_BTN_BG_HOVER      = ( 80,  40, 170)
_QE_BTN_BG_DISABLED   = ( 50,  50,  50)
_QE_BTN_FG_ACTIVE     = (200, 160, 255)
_QE_BTN_FG_DISABLED   = (110, 110, 110)
_QE_BTN_BORDER_ACTIVE = (130,  80, 230)
_QE_BTN_BORDER_HOVER  = (180, 120, 255)
_QE_BTN_BORDER_DIS    = ( 80,  80,  80)


def _qe_panel_btn_rect():
    """Sits to the left of the Next-Phase button."""
    phase = _phase_btn_rect()
    x = phase.left - _QE_BTN_W - _PHASE_BTN_GAP
    y = phase.centery - _QE_BTN_H // 2
    return pygame.Rect(x, y, _QE_BTN_W, _QE_BTN_H)


def draw_qe_panel_button(screen, font, mouse_pos,
                          has_quick_effects: bool,
                          panel_open: bool = False) -> None:
    """
    Renders the ⚡ Quick Effects HUD button.

    Parameters
    ----------
    has_quick_effects : True when the player has at least one activatable effect
    panel_open        : True when the panel is already open (highlights the button)
    """
    rect    = _qe_panel_btn_rect()
    enabled = has_quick_effects
    hovered = rect.collidepoint(mouse_pos) and enabled

    if not enabled:
        bg, fg, border = (_QE_BTN_BG_DISABLED,
                          _QE_BTN_FG_DISABLED,
                          _QE_BTN_BORDER_DIS)
    elif panel_open or hovered:
        bg, fg, border = (_QE_BTN_BG_HOVER,
                          _QE_BTN_FG_ACTIVE,
                          _QE_BTN_BORDER_HOVER)
    else:
        bg, fg, border = (_QE_BTN_BG_ACTIVE,
                          _QE_BTN_FG_ACTIVE,
                          _QE_BTN_BORDER_ACTIVE)

    pygame.draw.rect(screen, bg,     rect, border_radius=6)
    pygame.draw.rect(screen, border, rect, width=2, border_radius=6)

    label = f"{QE_ICON} Quick Effects"
    text  = font.render(label, True, fg)
    screen.blit(text, text.get_rect(center=rect.center))


def qe_panel_btn_hit_test(mouse_pos, has_quick_effects: bool) -> bool:
    """Returns True if the QE button was clicked and is currently enabled."""
    if not has_quick_effects:
        return False
    return _qe_panel_btn_rect().collidepoint(mouse_pos)


# ---------------------------------------------------------------------------
# Public hit-tests
# ---------------------------------------------------------------------------

def lp_hit_test(mouse_pos, player_lp, opp_lp):
    """Returns 'player', 'opponent', or None based on which LP box was clicked."""
    if _player_lp_rect().collidepoint(mouse_pos):
        return "player"
    if _opp_lp_rect().collidepoint(mouse_pos):
        return "opponent"
    return None


def phase_btn_hit_test(mouse_pos, game_phase):
    """
    Returns True if the Next-Phase button was clicked AND it's enabled.
    Disabled at End Phase — the player must press Tab to end the turn.
    """
    if game_phase == "End":
        return False
    return _phase_btn_rect().collidepoint(mouse_pos)


# ---------------------------------------------------------------------------
# Internal renderers
# ---------------------------------------------------------------------------

def _draw_lp_box(screen, rect, label, lp_value,
                 is_active, is_hovered, lp_input_buffer,
                 idle_fill, hover_fill):
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

    label_surf = label_font.render(label, True, LP_LABEL_COL)
    screen.blit(label_surf, (rect.x + _LP_PAD, rect.y + 5))

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

    if is_hovered and not is_active:
        hint = hint_font.render("click to edit  •  Enter to confirm", True, (120, 120, 120))
        screen.blit(hint, (rect.x + _LP_PAD, vy + 2))


def _draw_phase_button(screen, font, rect, game_phase, mouse_pos):
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
# Public draw call
# ---------------------------------------------------------------------------

def draw_hud(screen, font, small_font,
             active_player, turn_number,
             player_deck, opp_deck,
             player_lp, opp_lp,
             export_flash, hints,
             lp_edit_target, lp_input_buffer,
             mouse_pos=(0, 0),
             game_phase="Main"):
    """
    Draws the full HUD.
    Returns (lp_edit_target, lp_input_buffer) unchanged.
    """
    col = HUD_PLAYER_COL if active_player == "player" else HUD_OPPONENT_COL
    screen.blit(font.render(
        f"Turn {turn_number}  │  Active: {active_player.upper()}"
        f"  │  Phase: {game_phase}"
        f"  │  [Tab = end turn, Space = next phase]",
        True, col), (10, 10))

    screen.blit(small_font.render(
        f"Player deck: {len(player_deck)}    Opponent deck: {len(opp_deck)}",
        True, HUD_DECK_COL), (10, 34))

    for i, h in enumerate(hints):
        screen.blit(small_font.render(h, True, HUD_HINT_COL),
                    (10, SCREEN_SIZE[1] - 18 * (len(hints) - i)))

    if export_flash > 0:
        fs = small_font.render("✓  game_state.json saved", True, HUD_EXPORT_COL)
        fs.set_alpha(min(255, export_flash * 4))
        screen.blit(fs, (10, 56))

    _draw_phase_button(screen, font, _phase_btn_rect(), game_phase, mouse_pos)

    p_rect    = _player_lp_rect()
    o_rect    = _opp_lp_rect()
    p_hovered = p_rect.collidepoint(mouse_pos)
    o_hovered = o_rect.collidepoint(mouse_pos)

    _draw_lp_box(screen, p_rect, "YOUR LIFE POINTS",     player_lp,
                 is_active=(lp_edit_target == "player"),
                 is_hovered=p_hovered,
                 lp_input_buffer=lp_input_buffer,
                 idle_fill=LP_BOX_PLAYER_IDLE, hover_fill=LP_BOX_PLAYER_HOVER)

    _draw_lp_box(screen, o_rect, "OPPONENT LIFE POINTS", opp_lp,
                 is_active=(lp_edit_target == "opponent"),
                 is_hovered=o_hovered,
                 lp_input_buffer=lp_input_buffer,
                 idle_fill=LP_BOX_OPP_IDLE, hover_fill=LP_BOX_OPP_HOVER)

    return lp_edit_target, lp_input_buffer
