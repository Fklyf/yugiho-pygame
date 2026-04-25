import pygame

class Graveyard:
    def __init__(self):
        self.cards = []
        self._cached_surf = None
        self._last_size = (0, 0)

    def add_card(self, card_obj):
        card_obj.in_hand = False
        card_obj.is_dragging = False
        card_obj.mode = "ATK"
        self.cards.append(card_obj)
        # Clear cache so the new top card gets rendered
        self._cached_surf = None 

    def draw_top_card(self, screen, gy_rect):
        if not self.cards or not gy_rect:
            return

        top_card = self.cards[-1]
        w, h = int(gy_rect.width), int(gy_rect.height)

        if w <= 5 or h <= 5:
            return

        # Only rescale if the size changed (zooming) or we don't have a cache
        if (w, h) != self._last_size or self._cached_surf is None:
            try:
                # Use the front image (assuming your Card uses .image or .front_img)
                src = getattr(top_card, 'front_img', getattr(top_card, 'image', None))
                
                if src:
                    # smoothscale is better for downscaling, 
                    # but if it's still blurry, try pygame.transform.resizing.scale
                    self._cached_surf = pygame.transform.smoothscale(src, (w, h))
                    self._last_size = (w, h)
            except Exception as e:
                print(f"Scale Error: {e}")
                return

        # Blit the crisp cached version
        if self._cached_surf:
            screen.blit(self._cached_surf, gy_rect.topleft)
            
            # Keep the rect updated for clicking
            top_card.rect.topleft = gy_rect.topleft
            top_card.rect.size = (w, h)