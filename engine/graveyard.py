import pygame
from config import SCREEN_SIZE

class Graveyard:
    def __init__(self):
        self.cards = []

    def add_card(self, card_obj):
        """Sends a card to the graveyard."""
        card_obj.in_hand = False
        card_obj.is_dragging = False
        card_obj.mode = "ATK" # Reset to face-up vertical
        self.cards.append(card_obj)

    def draw_top_card(self, screen, gy_rect):
        """Draws only the top card of the GY inside the GY zone."""
        if self.cards and gy_rect:
            top_card = self.cards[-1]

            # Resize card surface to exactly fit the zone rect so it snaps
            # perfectly regardless of zoom / camera offset.
            zone_w = gy_rect.width
            zone_h = gy_rect.height

            # Update the card's world position to match the zone centre so
            # reposition_field_card stays consistent if the card is inspected.
            cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
            top_card.rect.width  = zone_w
            top_card.rect.height = zone_h
            top_card.rect.centerx = gy_rect.centerx
            top_card.rect.centery = gy_rect.centery

            # Scale the front/back surface to fit the zone tightly
            try:
                face_up = top_card.mode != "SET"
                src = top_card.front_img if face_up else top_card.back_img
                scaled = pygame.transform.smoothscale(src, (zone_w, zone_h))
                screen.blit(scaled, gy_rect.topleft)
            except Exception:
                # Fallback: let the card draw itself at the snapped position
                top_card.draw(screen)