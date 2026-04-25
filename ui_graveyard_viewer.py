"""
ui_graveyard_viewer.py
----------------------
Full-screen dim overlay that shows both players' graveyards side-by-side.

Usage (in Main.py)
------------------
    import ui_graveyard_viewer as gy_viewer

    # In the main loop, whenever the viewer is open:
    if gy_viewer.is_open():
        gy_viewer.draw(screen, font, small_font, player_gy, opp_gy)
        # Let the viewer handle its own events and swallow them so the
        # underlying game doesn't also react:
        #   for event in pygame.event.get():
        #       if gy_viewer.handle_event(event):
        #           continue
        #       ... normal game event handling ...

    # Open it when RMB hits either GY zone:
    if rmb_on_gy_zone:
        gy_viewer.open()

Design
------
- Read-only. Hover a thumbnail → full card detail appears in a side column.
- Both GYs shown; "Your GY" on the left, "Opponent's GY" on the right.
- Cards rendered in a responsive grid (wraps to new rows when overflowing).
- Most recently added card is highlighted with a subtle border.
- Click outside the grid, press Escape, or RMB anywhere closes the viewer.

Dependencies
------------
- pygame (already in use)
- config.SCREEN_SIZE for sizing
- Card objects with .front_img attribute (standard)
"""

from __future__ import annotations
import pygame
from config import SCREEN_SIZE


# ── Module-level state ──────────────────────────────────────────────────────
# The viewer is a singleton; there's only one GY overlay open at a time.
_open             = False
_hovered_card     = None      # Card currently under mouse, for detail pane
_scroll_player    = 0         # pixels scrolled down in player column
_scroll_opponent  = 0         # pixels scrolled down in opponent column

# Layout constants. Tuned to look clean at 1920×1080; scale from SCREEN_SIZE.
_MARGIN           = 40
_CARD_W           = 90
_CARD_H           = 130
_CARD_GAP         = 10
_HEADER_H         = 60
_DETAIL_W         = 320      # width of the detail pane on the right

# Colour palette
_BG_DIM_ALPHA     = 200       # 0–255, how dark the background dim is
_PANEL_BG         = (24, 28, 36)
_PANEL_BORDER     = (120, 140, 180)
_TITLE_COLOR      = (230, 235, 245)
_COUNT_COLOR      = (180, 190, 210)
_CARD_HIGHLIGHT   = (255, 210, 90)
_DETAIL_BG        = (32, 38, 50)
_DETAIL_TEXT      = (220, 225, 235)


# ── Public API ──────────────────────────────────────────────────────────────

def is_open() -> bool:
    return _open


def open() -> None:
    global _open, _hovered_card, _scroll_player, _scroll_opponent
    _open = True
    _hovered_card = None
    _scroll_player = 0
    _scroll_opponent = 0


def close() -> None:
    global _open, _hovered_card
    _open = False
    _hovered_card = None


def toggle() -> None:
    if _open:
        close()
    else:
        open()


def handle_event(event) -> bool:
    """
    Consume an event if the viewer is open. Returns True if the event was
    handled (caller should skip its own handling of this event).
    """
    global _hovered_card, _scroll_player, _scroll_opponent

    if not _open:
        return False

    if event.type == pygame.KEYDOWN:
        if event.key in (pygame.K_ESCAPE, pygame.K_BACKQUOTE, pygame.K_q):
            close()
        return True

    if event.type == pygame.MOUSEBUTTONDOWN:
        # RMB anywhere closes the viewer; LMB clicks outside the panel close.
        if event.button == 3:
            close()
            return True
        if event.button == 1:
            panel_rect = _panel_rect()
            if not panel_rect.collidepoint(event.pos):
                close()
            return True
        # Scroll wheel
        if event.button == 4:   # wheel up
            _apply_scroll(event.pos, -40)
            return True
        if event.button == 5:   # wheel down
            _apply_scroll(event.pos, 40)
            return True

    if event.type == pygame.MOUSEMOTION:
        # Hover detection — updated in draw(), but also invalidate here so
        # rapid motion doesn't show stale hover after scroll.
        _hovered_card = None
        return True

    # Absorb all other events while the viewer is open so the game doesn't
    # react to them.
    return True


def draw(screen, font, small_font, player_gy, opp_gy) -> None:
    """Render the overlay. Call every frame while is_open()."""
    if not _open:
        return

    # ── Dim background ────────────────────────────────────────────────────
    dim = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    dim.fill((0, 0, 0, _BG_DIM_ALPHA))
    screen.blit(dim, (0, 0))

    # ── Panel frame ───────────────────────────────────────────────────────
    panel = _panel_rect()
    pygame.draw.rect(screen, _PANEL_BG, panel, border_radius=8)
    pygame.draw.rect(screen, _PANEL_BORDER, panel, width=2, border_radius=8)

    # ── Title bar ─────────────────────────────────────────────────────────
    title = font.render("Graveyards", True, _TITLE_COLOR)
    screen.blit(title, (panel.x + 20, panel.y + 18))
    hint = small_font.render("Hover for details — Esc or RMB to close",
                             True, _COUNT_COLOR)
    screen.blit(hint, (panel.right - hint.get_width() - 20, panel.y + 22))

    # Separator under title
    pygame.draw.line(screen, _PANEL_BORDER,
                     (panel.x + 10, panel.y + _HEADER_H),
                     (panel.right - 10, panel.y + _HEADER_H), 1)

    # ── Column layout ────────────────────────────────────────────────────
    mouse_pos = pygame.mouse.get_pos()

    detail_x = panel.right - _DETAIL_W - 10
    col_w = (detail_x - panel.x - 30) // 2
    col_y = panel.y + _HEADER_H + 20
    col_h = panel.bottom - col_y - 20

    player_col = pygame.Rect(panel.x + 20,            col_y, col_w, col_h)
    opp_col    = pygame.Rect(player_col.right + 10,   col_y, col_w, col_h)

    # Remember positions for scroll routing
    _panel_rect.player_col = player_col   # attach as attribute for handle_event
    _panel_rect.opp_col    = opp_col

    _draw_column(screen, font, small_font, player_col,
                 "Your Graveyard", player_gy.cards, _scroll_player, mouse_pos)
    _draw_column(screen, font, small_font, opp_col,
                 "Opponent's Graveyard", opp_gy.cards, _scroll_opponent, mouse_pos)

    # ── Detail pane ──────────────────────────────────────────────────────
    detail = pygame.Rect(detail_x, col_y, _DETAIL_W, col_h)
    pygame.draw.rect(screen, _DETAIL_BG, detail, border_radius=4)
    pygame.draw.rect(screen, _PANEL_BORDER, detail, width=1, border_radius=4)
    _draw_detail_pane(screen, font, small_font, detail, _hovered_card)


# ── Internals ───────────────────────────────────────────────────────────────

def _panel_rect() -> pygame.Rect:
    return pygame.Rect(
        _MARGIN, _MARGIN,
        SCREEN_SIZE[0] - 2 * _MARGIN,
        SCREEN_SIZE[1] - 2 * _MARGIN,
    )


def _apply_scroll(pos, delta) -> None:
    """Route wheel scroll to whichever column the cursor is over."""
    global _scroll_player, _scroll_opponent
    player_col = getattr(_panel_rect, "player_col", None)
    opp_col    = getattr(_panel_rect, "opp_col",    None)
    if player_col and player_col.collidepoint(pos):
        _scroll_player = max(0, _scroll_player + delta)
    elif opp_col and opp_col.collidepoint(pos):
        _scroll_opponent = max(0, _scroll_opponent + delta)


def _draw_column(screen, font, small_font, col_rect, title, cards, scroll, mouse_pos) -> None:
    """Render one graveyard column and update _hovered_card as a side effect."""
    global _hovered_card

    # Column header
    header = font.render(f"{title}  ({len(cards)})", True, _TITLE_COLOR)
    screen.blit(header, (col_rect.x + 4, col_rect.y - 28))

    # Clip drawing to the column so scrolled-out cards don't bleed over
    old_clip = screen.get_clip()
    screen.set_clip(col_rect)

    # Grid: how many columns fit?
    per_row = max(1, (col_rect.width + _CARD_GAP) // (_CARD_W + _CARD_GAP))

    # Draw cards — newest first so the latest addition is most visible.
    # (Reverse the list; cards.append(c) is the insertion order.)
    ordered = list(reversed(cards))

    for i, card in enumerate(ordered):
        row, col = divmod(i, per_row)
        cx = col_rect.x + col * (_CARD_W + _CARD_GAP) + 4
        cy = col_rect.y + row * (_CARD_H + _CARD_GAP) + 4 - scroll

        # Cull rows completely above/below the visible window
        if cy + _CARD_H < col_rect.y or cy > col_rect.bottom:
            continue

        thumb_rect = pygame.Rect(cx, cy, _CARD_W, _CARD_H)

        # Render card image (front_img, scaled)
        try:
            src = card.front_img
            scaled = pygame.transform.smoothscale(src, (_CARD_W, _CARD_H))
            screen.blit(scaled, thumb_rect.topleft)
        except Exception:
            pygame.draw.rect(screen, (80, 40, 40), thumb_rect)
            name = (getattr(card, "meta", {}) or {}).get("name", "?")
            label = small_font.render(name[:10], True, (240, 240, 240))
            screen.blit(label, (thumb_rect.x + 4, thumb_rect.y + 4))

        # Highlight on hover
        if thumb_rect.collidepoint(mouse_pos):
            pygame.draw.rect(screen, _CARD_HIGHLIGHT, thumb_rect, width=3,
                             border_radius=3)
            _hovered_card = card
        # Highlight the most recent addition (index 0 after reversing)
        elif i == 0:
            pygame.draw.rect(screen, (140, 170, 220), thumb_rect, width=2,
                             border_radius=3)

    screen.set_clip(old_clip)

    if not cards:
        empty = small_font.render("(empty)", True, _COUNT_COLOR)
        screen.blit(empty, (col_rect.x + 10, col_rect.y + 20))


def _draw_detail_pane(screen, font, small_font, rect, card) -> None:
    if card is None:
        msg = small_font.render("Hover a card to see details",
                                True, _COUNT_COLOR)
        screen.blit(msg, (rect.x + 12, rect.y + 12))
        return

    meta = getattr(card, "meta", {}) or {}
    name = meta.get("name", "Unknown")
    ctype = meta.get("type", getattr(card, "card_type", ""))
    atk   = meta.get("atk")
    df    = meta.get("def")
    level = meta.get("level")
    attr  = meta.get("attribute")
    race  = meta.get("race")
    desc  = meta.get("desc", "")

    y = rect.y + 12
    # Name
    name_surf = font.render(name, True, _DETAIL_TEXT)
    screen.blit(name_surf, (rect.x + 12, y))
    y += name_surf.get_height() + 4

    # Type line
    type_surf = small_font.render(str(ctype), True, _COUNT_COLOR)
    screen.blit(type_surf, (rect.x + 12, y))
    y += type_surf.get_height() + 6

    # Card image (larger than thumbnail)
    img_w = rect.width - 24
    img_h = int(img_w * 1.45)
    if y + img_h < rect.bottom - 120:
        try:
            scaled = pygame.transform.smoothscale(card.front_img, (img_w, img_h))
            screen.blit(scaled, (rect.x + 12, y))
            y += img_h + 8
        except Exception:
            pass

    # Stats block (monsters only)
    if atk is not None or df is not None or level is not None:
        stat_line = []
        if level is not None:
            stat_line.append(f"Lv {level}")
        if attr:
            stat_line.append(str(attr))
        if race:
            stat_line.append(str(race))
        if stat_line:
            sl = small_font.render(" · ".join(stat_line), True, _COUNT_COLOR)
            screen.blit(sl, (rect.x + 12, y))
            y += sl.get_height() + 2
        if atk is not None or df is not None:
            atk_line = f"ATK {atk if atk is not None else '?'}  /  DEF {df if df is not None else '?'}"
            surf = font.render(atk_line, True, _DETAIL_TEXT)
            screen.blit(surf, (rect.x + 12, y))
            y += surf.get_height() + 6

    # Description (wrapped)
    if desc:
        y = _blit_wrapped(screen, small_font, desc, rect.x + 12, y,
                          rect.width - 24, _DETAIL_TEXT, rect.bottom - 12)


def _blit_wrapped(screen, font, text, x, y, max_width, color, y_limit) -> int:
    """Render *text* wrapped to max_width, starting at (x, y). Returns new y."""
    import textwrap
    # Rough char estimate: pygame font has no measure-width-per-char API that's
    # cheap, so we approximate by trying character lengths.
    words = text.split()
    line = ""
    lines = []
    for w in words:
        candidate = (line + " " + w).strip()
        if font.size(candidate)[0] <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)

    for ln in lines:
        if y + font.get_height() > y_limit:
            break
        surf = font.render(ln, True, color)
        screen.blit(surf, (x, y))
        y += font.get_height() + 1
    return y
