"""
ui/quick_effects.py
-------------------
Two things live here:

1. Per-card ⚡ button rendering / hit-test (original, used by __init__.py)
   draw_quick_effect_buttons(screen, font, quick_effects, mouse_pos, hand_rects)
   quick_effect_btn_hit_test(mouse_pos, quick_effects, hand_rects) → QuickEffectEntry | None

2. Quick-effect panel overlay (new)
   open_panel(quick_effects)
   close_panel()
   is_open() → bool
   draw_panel(screen, font, small_font)
   panel_hit_test(mouse_pos) → QuickEffectEntry | None
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import pygame
from ui.constants import (
    QE_BTN_W, QE_BTN_H, QE_BTN_GAP_Y, QE_STACK_STEP,
    QE_BG_IDLE, QE_BG_HOVER,
    QE_BORDER_IDLE, QE_BORDER_HOVER,
    QE_TEXT_COL, QE_ICON,
    SCREEN_SIZE,
)

if TYPE_CHECKING:
    from cardengine.effects import QuickEffectEntry


# ===========================================================================
# Part 1 — Per-card ⚡ buttons (original)
# ===========================================================================

def _btn_rect(card_rect: pygame.Rect, stack_index: int = 0) -> pygame.Rect:
    cx = card_rect.centerx
    y  = card_rect.top - QE_BTN_GAP_Y - QE_BTN_H - stack_index * QE_STACK_STEP
    return pygame.Rect(cx - QE_BTN_W // 2, y, QE_BTN_W, QE_BTN_H)


def _get_card_rect(card, hand_rects) -> pygame.Rect | None:
    if hand_rects and card in hand_rects:
        return hand_rects[card]
    return getattr(card, "rect", None)


def draw_quick_effect_buttons(
    screen,
    font,
    quick_effects: list,
    mouse_pos: tuple,
    hand_rects: dict = None,
) -> None:
    """
    Renders a ⚡ button above each hand card that has an activatable
    quick effect.  Call after all card sprites and field overlays.
    """
    if not quick_effects:
        return

    btn_font = pygame.font.SysFont("Arial", 12, bold=True)
    seen: dict = {}

    for entry in quick_effects:
        card      = entry.card
        card_rect = _get_card_rect(card, hand_rects)
        if card_rect is None:
            continue

        stack_idx      = seen.get(id(card), 0)
        seen[id(card)] = stack_idx + 1

        btn     = _btn_rect(card_rect, stack_idx)
        hovered = btn.collidepoint(mouse_pos)

        bg_col     = QE_BG_HOVER     if hovered else QE_BG_IDLE
        border_col = QE_BORDER_HOVER if hovered else QE_BORDER_IDLE

        bg_surf = pygame.Surface((btn.width, btn.height), pygame.SRCALPHA)
        bg_surf.fill(bg_col)
        screen.blit(bg_surf, btn.topleft)

        border_surf = pygame.Surface((btn.width, btn.height), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, border_col,
                         (0, 0, btn.width, btn.height), 1, border_radius=4)
        screen.blit(border_surf, btn.topleft)

        label      = f"{QE_ICON} {entry.label}"
        label_surf = btn_font.render(label, True, QE_TEXT_COL)
        lx = btn.x + max(2, (btn.width - label_surf.get_width()) // 2)
        ly = btn.y + (btn.height - label_surf.get_height()) // 2
        screen.blit(label_surf, (lx, ly))


def quick_effect_btn_hit_test(
    mouse_pos: tuple,
    quick_effects: list,
    hand_rects: dict = None,
) -> "QuickEffectEntry | None":
    """
    Returns the QuickEffectEntry whose ⚡ button was clicked, or None.
    Call on MOUSEBUTTONDOWN before all other click handlers.
    """
    seen: dict = {}
    for entry in quick_effects:
        card      = entry.card
        card_rect = _get_card_rect(card, hand_rects)
        if card_rect is None:
            continue

        stack_idx      = seen.get(id(card), 0)
        seen[id(card)] = stack_idx + 1

        if _btn_rect(card_rect, stack_idx).collidepoint(mouse_pos):
            return entry

    return None


# ===========================================================================
# Part 2 — Panel overlay (new)
# ===========================================================================

_PANEL_BG         = ( 10,  10,  35, 220)
_PANEL_BORDER     = ( 90,  60, 180, 255)
_PANEL_TITLE_COL  = (180, 140, 255)
_ROW_IDLE         = ( 25,  25,  60, 200)
_ROW_HOVER        = ( 55,  40, 130, 230)
_ROW_BORDER       = ( 70,  50, 160, 200)
_NAME_COL         = (220, 200, 255)
_HOOK_COL         = (150, 130, 210)

_PAD              = 14
_ROW_H            = 46
_ROW_GAP          = 6
_PANEL_W          = 340

_panel_open: bool       = False
_panel_entries: list    = []
_panel_row_rects: list  = []


def open_panel(quick_effects: list) -> None:
    global _panel_open, _panel_entries, _panel_row_rects
    _panel_open      = True
    _panel_entries   = list(quick_effects)
    _panel_row_rects = []


def close_panel() -> None:
    global _panel_open, _panel_entries, _panel_row_rects
    _panel_open      = False
    _panel_entries   = []
    _panel_row_rects = []


def is_open() -> bool:
    return _panel_open


def draw_panel(screen: pygame.Surface, font, small_font) -> None:
    """Render the panel centred on screen. Rebuilds row rects each frame."""
    global _panel_row_rects

    if not _panel_open:
        return

    title_font = pygame.font.SysFont("Arial", 16, bold=True)
    name_font  = pygame.font.SysFont("Arial", 14, bold=True)
    hook_font  = pygame.font.SysFont("Arial", 12)
    dim_font   = pygame.font.SysFont("Arial", 11)

    n_rows  = max(len(_panel_entries), 1)
    title_h = 28
    panel_h = (_PAD + title_h + _PAD // 2
               + n_rows * (_ROW_H + _ROW_GAP) - _ROW_GAP
               + _PAD)

    cx = SCREEN_SIZE[0] // 2
    cy = SCREEN_SIZE[1] // 2
    px = cx - _PANEL_W // 2
    py = cy - panel_h // 2

    bg = pygame.Surface((_PANEL_W, panel_h), pygame.SRCALPHA)
    bg.fill(_PANEL_BG)
    screen.blit(bg, (px, py))
    pygame.draw.rect(screen, _PANEL_BORDER, (px, py, _PANEL_W, panel_h), 2, border_radius=8)

    title_surf = title_font.render(f"{QE_ICON}  Quick Effects", True, _PANEL_TITLE_COL)
    screen.blit(title_surf, (px + _PAD, py + _PAD))

    mx, my = pygame.mouse.get_pos()
    _panel_row_rects = []
    row_y = py + _PAD + title_h + _PAD // 2

    if not _panel_entries:
        no_surf = hook_font.render("No quick effects available right now.", True, _HOOK_COL)
        screen.blit(no_surf, (px + _PAD, row_y + (_ROW_H - no_surf.get_height()) // 2))
        _panel_row_rects.append(None)
        return

    for entry in _panel_entries:
        row_rect = pygame.Rect(px + _PAD // 2, row_y, _PANEL_W - _PAD, _ROW_H)
        _panel_row_rects.append(row_rect)

        hovered  = row_rect.collidepoint(mx, my)
        row_bg   = pygame.Surface((row_rect.width, row_rect.height), pygame.SRCALPHA)
        row_bg.fill(_ROW_HOVER if hovered else _ROW_IDLE)
        screen.blit(row_bg, row_rect.topleft)
        pygame.draw.rect(screen, _ROW_BORDER, row_rect, 1, border_radius=5)

        meta      = getattr(entry.card, "meta", {}) or {}
        card_name = meta.get("name", "Unknown")
        label     = getattr(entry, "label", "Activate")

        name_surf = name_font.render(f"{QE_ICON} {card_name}", True, _NAME_COL)
        hook_surf = hook_font.render(label, True, _HOOK_COL)
        tx = row_rect.x + 8
        screen.blit(name_surf, (tx, row_rect.y + 5))
        screen.blit(hook_surf, (tx + 2, row_rect.y + 5 + name_surf.get_height() + 2))

        row_y += _ROW_H + _ROW_GAP

    dim_surf = dim_font.render("Esc / right-click to dismiss", True, (90, 90, 120))
    screen.blit(dim_surf,
                (px + _PANEL_W - dim_surf.get_width() - _PAD,
                 py + panel_h - dim_surf.get_height() - 4))


def panel_hit_test(mouse_pos: tuple) -> "QuickEffectEntry | None":
    """Returns the entry whose row was clicked, or None."""
    if not _panel_open or not _panel_entries:
        return None
    for rect, entry in zip(_panel_row_rects, _panel_entries):
        if rect and rect.collidepoint(mouse_pos):
            return entry
    return None
