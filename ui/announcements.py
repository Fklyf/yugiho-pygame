"""
ui/announcements.py
-------------------
Centre-screen announcement banner (spell activation, damage, etc.).

Public API
----------
draw_announcement(screen, title, body_lines, alpha, kind="spell")
"""

import pygame
from ui.constants import (
    SCREEN_SIZE,
    _ANN_SPELL_BG, _ANN_SPELL_TITLE, _ANN_SPELL_BODY,
    _ANN_DAMAGE_BG, _ANN_DAMAGE_TITLE, _ANN_DAMAGE_BODY,
    _ANN_BORDER_SPELL, _ANN_BORDER_DAMAGE,
)


def draw_announcement(screen, title: str, body_lines: list,
                       alpha: int, kind: str = "spell") -> None:
    """
    Renders a centred announcement banner that fades out over time.

    Parameters
    ----------
    screen     : pygame.Surface
    title      : bold headline
    body_lines : list of detail strings shown below the title
    alpha      : 0–255 opacity — pass a value that decrements each frame
    kind       : "spell" (purple) | "damage" (red)

    Usage in Main.py
    ----------------
    if announcement_timer > 0:
        alpha = min(255, announcement_timer * 4)
        draw_announcement(screen,
                          announcement["title"],
                          announcement["body"],
                          alpha,
                          announcement["kind"])
        announcement_timer -= 1
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

    PAD = 24
    W   = max(title_surf.get_width(),
              *(s.get_width() for s in body_surfs),
              300) + PAD * 2
    H   = (PAD
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

    title_surf.set_alpha(alpha)
    screen.blit(title_surf, (cx - title_surf.get_width() // 2, y + PAD))

    ty = y + PAD + title_surf.get_height() + 8
    for surf in body_surfs:
        surf.set_alpha(alpha)
        screen.blit(surf, (cx - surf.get_width() // 2, ty))
        ty += surf.get_height() + 4
