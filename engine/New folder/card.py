import pygame

class Card:
    def __init__(self, image, card_back_image, card_type):
        self.original_image = image
        self.original_back_image = card_back_image
        self.image = image
        self.card_back_image = card_back_image
        
        self.card_type = card_type 
        self.base_width, self.base_height = self.original_image.get_size()
        self.rect = self.image.get_rect()
        
        # World coordinates for field placement
        self.world_x, self.world_y = 0, 0
        
        # Default states
        self.mode = "ATK" if "Monster" in self.card_type else "FACE_UP"
        self.in_hand = True
        self.is_dragging = False
        self.angle = 0
        self.current_scale = 1.0

    def update_visuals(self, scale, offset=(0, 0)):
        """Handles scaling and accepts the 'offset' sent by the Hand class."""
        if self.current_scale != scale:
            self.current_scale = scale
            new_w = int(self.base_width * scale)
            new_h = int(base_h := self.base_height * scale)
            self.image = pygame.transform.smoothscale(self.original_image, (new_w, int(new_h)))
            
            if self.original_back_image:
                self.card_back_image = pygame.transform.smoothscale(self.original_back_image, (new_w, int(new_h)))
            else:
                self.card_back_image = pygame.Surface((new_w, int(new_h)))
                self.card_back_image.fill((50, 50, 50))

            self.rect = self.image.get_rect(center=self.rect.center)

    def update_screen_position(self, zoom_level, camera, pivot=(0, 0)):
        """
        Translates world coordinates to the screen using a pivot point.
        Formula: Screen = (World + Camera - Pivot) * Zoom + Pivot
        """
        cx, cy = pivot
        cam_x, cam_y = camera
        
        # Calculate position relative to the screen center (pivot)
        screen_x = (self.world_x + cam_x - cx) * zoom_level + cx
        screen_y = (self.world_y + cam_y - cy) * zoom_level + cy
        
        self.rect.center = (int(screen_x), int(screen_y))

    def toggle_position(self):
        """Cycles through ATK/DEF/SET for Monsters and FACE_UP/SET for Spells."""
        if "Monster" in self.card_type:
            modes = ["ATK", "DEF", "SET"]
            self.mode = modes[(modes.index(self.mode) + 1) % 3]
        else:
            self.mode = "SET" if self.mode == "FACE_UP" else "FACE_UP"

    def draw(self, surface):
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