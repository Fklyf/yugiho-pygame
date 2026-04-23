import pygame
from config import SCREEN_SIZE, BASE_CARD_SIZE, ZONE_COLOR, LABEL_COLOR

# Colors to distinguish the two sides
PLAYER_ZONE_COLOR = (40, 40, 60)    # Blueish — player's side
OPPONENT_ZONE_COLOR = (60, 40, 40)  # Reddish — opponent's side


def _build_zone_list(spacing_x, spacing_y, side_sign):
    """
    Build the list of (name, (world_x, world_y)) for one side of the field.
    side_sign = +1 → player (bottom half), -1 → opponent (top half).
    The two rows for each side:
        inner row  (closer to centre-line) = Monster zones
        outer row  (further from centre)   = Spell/Trap zones
    """
    inner_y = side_sign * spacing_y / 2    # Monster row
    outer_y = side_sign * spacing_y * 1.5  # Spell/Trap row

    side_offset = spacing_x * 3

    prefix = "P" if side_sign == 1 else "O"  # Player vs Opponent prefix

    zones = [
        (f'{prefix}_Deck',  (side_offset,  outer_y)),
        (f'{prefix}_GY',    (side_offset,  inner_y)),
        (f'{prefix}_Extra', (-side_offset, outer_y)),
        (f'{prefix}_Field', (-side_offset, inner_y)),
    ]

    start_x = -2 * spacing_x
    for i in range(5):
        x = start_x + i * spacing_x
        zones.append((f'{prefix}_M{i+1}',   (x, inner_y)))
        zones.append((f'{prefix}_S/T{i+1}', (x, outer_y)))

    return zones


def draw_field_zones(screen, zoom_level, cam_offset, font):
    """
    Draws both the player (bottom) and opponent (top) field zones.
    Returns a dict of interactive zone rects keyed by logical name.
    """
    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2

    card_w, card_h = BASE_CARD_SIZE
    spacing_x = card_w + 20
    spacing_y = card_h + 26

    player_zones   = _build_zone_list(spacing_x, spacing_y, +1)
    opponent_zones = _build_zone_list(spacing_x, spacing_y, -1)

    interactive_zones = {}

    for zone_list, color in ((player_zones, PLAYER_ZONE_COLOR),
                              (opponent_zones, OPPONENT_ZONE_COLOR)):
        for name, pos in zone_list:
            w = int(card_w * zoom_level)
            h = int(card_h * zoom_level)

            sx = int(cx + (pos[0] + cam_offset[0]) * zoom_level - w / 2)
            sy = int(cy + (pos[1] + cam_offset[1]) * zoom_level - h / 2)

            z_rect = pygame.Rect(sx, sy, w, h)
            pygame.draw.rect(screen, color, z_rect, 2)

            # Short label (strip the P_/O_ prefix for display)
            label = name.split("_", 1)[1]
            text_surface = font.render(label, True, LABEL_COLOR)
            screen.blit(text_surface, (sx + 5, sy + 5))

            # Store every zone rect for hit-testing and GY/Deck access
            interactive_zones[name] = z_rect

    # Draw the centre dividing line
    line_y = int(cy + cam_offset[1] * zoom_level)
    pygame.draw.line(screen, (80, 80, 80),
                     (0, line_y), (SCREEN_SIZE[0], line_y), 1)

    return interactive_zones