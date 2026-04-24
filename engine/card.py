import pygame
from config import BASE_CARD_SIZE

class Card:
    def __init__(self, image, card_back_image, card_type):
        # Scale the original images to the BASE_CARD_SIZE immediately
        self.original_image = pygame.transform.smoothscale(image, BASE_CARD_SIZE)
        self.original_back_image = pygame.transform.smoothscale(card_back_image, BASE_CARD_SIZE)
        self.owner = None

        self.image = self.original_image
        self.card_back_image = self.original_back_image
        
        self.card_type = card_type 
        # Use the standard size as the base for all future scaling
        self.base_width, self.base_height = BASE_CARD_SIZE 
        self.rect = self.image.get_rect()
        
        self.world_x, self.world_y = 0, 0
        self.mode = "ATK" if "Monster" in self.card_type else "FACE_UP"
        self.in_hand = True
        self.is_dragging = False
        self.angle = 0
        self.current_scale = 1.0

    def update_visuals(self, scale, offset=(0, 0)):
        """Handles scaling and accepts the 'offset' sent by the Hand class."""
        # Always update scale if it changes to maintain quality
        if self.current_scale != scale:
            self.current_scale = scale
            new_w = int(self.base_width * scale)
            new_h = int(self.base_height * scale)
            self.image = pygame.transform.smoothscale(self.original_image, (new_w, new_h))
            self.card_back_image = pygame.transform.smoothscale(self.original_back_image, (new_w, new_h))
            self.rect = self.image.get_rect(center=self.rect.center)

    def update_screen_position(self, zoom_level, camera_pos, pivot=(0, 0)):
        """
        Translates world coordinates to the screen based on camera panning
        and a pivot point (for centered zooming).
        """
        cam_x, cam_y = camera_pos
        pivot_x, pivot_y = pivot
        
        # Option 2 Fix: Apply the pivot transformation logic
        self.rect.centerx = int((self.world_x + cam_x - pivot_x) * zoom_level + pivot_x)
        self.rect.centery = int((self.world_y + cam_y - pivot_y) * zoom_level + pivot_y)

    def toggle_position(self):
        """Cycles through ATK/DEF/SET for Monsters and FACE_UP/SET for Spells."""
        if "Monster" in self.card_type:
            modes = ["ATK", "DEF", "SET"]
            self.mode = modes[(modes.index(self.mode) + 1) % 3]
        else:
            self.mode = "SET" if self.mode == "FACE_UP" else "FACE_UP"

    def draw(self, surface):
        # Choose front or back based on mode
        img = self.card_back_image if self.mode == "SET" else self.image
        rot_angle = self.angle
        
        # Rotate 90 degrees if in Defense or Set mode on the field
        if not self.in_hand and "Monster" in self.card_type and self.mode in ["DEF", "SET"]:
            rot_angle += 90

        if rot_angle != 0:
            rotated = pygame.transform.rotate(img, rot_angle)
            surface.blit(rotated, rotated.get_rect(center=self.rect.center).topleft)
        else:
            surface.blit(img, self.rect.topleft)