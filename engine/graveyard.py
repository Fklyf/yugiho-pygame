import pygame

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
            
            # Snap it perfectly to the GY zone's center
            top_card.rect.centerx = gy_rect.centerx
            top_card.rect.centery = gy_rect.centery
            
            top_card.draw(screen)