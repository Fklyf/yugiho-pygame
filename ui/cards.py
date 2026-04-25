"""
ui/cards.py
-----------
Card info panel rendered in the bottom-left corner.

Public API
----------
draw_card_info_panel(screen, card, font, small_font, game_state=None)
"""

import pygame
from ui.constants import SCREEN_SIZE, SEL_BORDER, INFO_BG, INFO_BORDER


def draw_card_info_panel(screen, card, font, small_font, game_state=None):
    """
    Draws a compact info panel in the bottom-left corner showing the
    selected card's name, type, ATK/DEF (with continuous-effect boost
    segments when game_state is supplied), and a description snippet.
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

    atk_boost = 0
    def_boost = 0
    if game_state is not None and (atk is not None or def_ is not None):
        from cardengine import battle
        if atk is not None:
            atk_boost = battle.get_effective_atk(card, game_state) - atk
        if def_ is not None:
            def_boost = battle.get_effective_def(card, game_state) - def_

    PAD = 10
    W   = 320
    H   = 130
    x   = PAD
    y   = SCREEN_SIZE[1] - H - PAD - 54

    bg = pygame.Surface((W, H), pygame.SRCALPHA)
    bg.fill(INFO_BG)
    screen.blit(bg, (x, y))
    pygame.draw.rect(screen, INFO_BORDER, (x, y, W, H), 1, border_radius=5)

    name_font = pygame.font.SysFont("Arial", 15, bold=True)
    name_surf = name_font.render(name, True, SEL_BORDER)
    screen.blit(name_surf, (x + PAD, y + PAD))

    type_font = pygame.font.SysFont("Arial", 12)
    type_surf = type_font.render(f"{card_type}  [{mode}]", True, (160, 160, 200))
    screen.blit(type_surf, (x + PAD, y + PAD + name_surf.get_height() + 2))

    if atk is not None or def_ is not None:
        BASE_COL  = (220, 200, 100)
        BOOST_POS = ( 80, 220, 100)
        BOOST_NEG = (220,  90,  90)
        SEP_COL   = (160, 160, 160)

        segments = []
        if atk is not None:
            segments.append((f"ATK {atk}", BASE_COL))
            if atk_boost > 0:
                segments.append((f" +{atk_boost}", BOOST_POS))
            elif atk_boost < 0:
                segments.append((f" {atk_boost}", BOOST_NEG))

        if atk is not None and def_ is not None:
            segments.append(("  /  ", SEP_COL))

        if def_ is not None:
            segments.append((f"DEF {def_}", BASE_COL))
            if def_boost > 0:
                segments.append((f" +{def_boost}", BOOST_POS))
            elif def_boost < 0:
                segments.append((f" {def_boost}", BOOST_NEG))

        sx = x + PAD
        sy = y + PAD + name_surf.get_height() + 18
        for text, colour in segments:
            surf = type_font.render(text, True, colour)
            screen.blit(surf, (sx, sy))
            sx += surf.get_width()

    desc_y    = y + PAD + name_surf.get_height() + 36
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
