import pygame
from config import (
    SCREEN_SIZE,
    CARD_HAND_SIZE_RATIO,
    HAND_ANCHOR_X_OFFSET,
    HAND_ANCHOR_Y_OFFSET,
    HAND_SPACING,
    HAND_CURVE_DIP,
    HAND_ANGLE_SPREAD,
    HAND_HOVER_SCALE_MULT,
    HAND_HOVER_LIFT,
    HAND_HOVER_SHIFT,
    HAND_HOVER_DIST_X,
    HAND_HOVER_DIST_Y,
    HAND_LERP_SPEED,
)


class Hand:
    """
    Displays a hand of cards as a centred arc fan at the bottom of the screen.

    Cards smoothly lerp toward their target positions each frame so adding /
    removing / hovering cards all feel fluid.  All magic numbers are pulled
    from config.py so the feel can be tuned without touching this file.
    """

    def __init__(self, anchor_y_override=None, visible=True):
        """
        anchor_y_override lets the opponent hand pass in a flipped Y anchor
        so both hands share the same class without any mirror logic here.
        visible=False hides the hand entirely (used for the opponent).
        """
        self.cards = []
        self.hovered_card = None
        self.visible = visible

        # Screen-centre anchor keeps the fan centred regardless of window size
        self.anchor_x = SCREEN_SIZE[0] // 2 + HAND_ANCHOR_X_OFFSET
        if anchor_y_override is not None:
            self.anchor_y = anchor_y_override
        else:
            self.anchor_y = SCREEN_SIZE[1] + HAND_ANCHOR_Y_OFFSET

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_card(self, card_obj, drop_x=None):
        card_obj.in_hand      = True
        card_obj.mode         = "ATK" if "Monster" in card_obj.card_type else "FACE_UP"
        card_obj.is_dragging  = False

        if drop_x is None or not self.cards:
            self.cards.append(card_obj)
        else:
            insert_index = len(self.cards)
            for i, card in enumerate(self.cards):
                if drop_x < getattr(card, 'target_x', 0):
                    insert_index = i
                    break
            self.cards.insert(insert_index, card_obj)

        self._reposition()

    def remove_card(self, card_obj):
        if card_obj in self.cards:
            self.cards.remove(card_obj)
        self._reposition()

    def update(self, mouse_pos):
        """Call once per frame before draw(). No-ops if not visible."""
        if not self.visible:
            return
        self._detect_hover(mouse_pos)
        self._apply_targets()
        self._lerp_positions()

    def draw(self, surface):
        """No-ops if not visible."""
        if not self.visible:
            return
        # Non-hovered, non-dragging cards first (back-to-front by index)
        for card in self.cards:
            if card is not self.hovered_card and not getattr(card, 'is_dragging', False):
                card.draw(surface)

        # Hovered card floats above the rest
        if self.hovered_card and not getattr(self.hovered_card, 'is_dragging', False):
            self.hovered_card.draw(surface)

        # Dragging card is always on top
        for card in self.cards:
            if getattr(card, 'is_dragging', False):
                card.draw(surface)

    def check_click(self, pos):
        """Returns the card under the cursor, preferring the hovered card."""
        if self.hovered_card and self.hovered_card.rect.collidepoint(pos):
            return self.hovered_card
        for card in reversed(self.cards):
            if card.rect.collidepoint(pos):
                return card
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reposition(self):
        """Recalculates target_x / target_y / target_angle for every card."""
        if not self.cards:
            return

        num_cards    = len(self.cards)
        center_index = (num_cards - 1) / 2.0
        total_width  = (num_cards - 1) * HAND_SPACING
        start_x      = self.anchor_x - total_width / 2.0   # centred fan

        for i, card in enumerate(self.cards):
            if getattr(card, 'is_dragging', False):
                continue

            offset = i - center_index                       # signed distance from centre

            card.target_x     = start_x + i * HAND_SPACING
            card.target_y     = self.anchor_y + (offset ** 2) * HAND_CURVE_DIP
            card.target_angle = -offset * HAND_ANGLE_SPREAD

    def _detect_hover(self, mouse_pos):
        """Picks which card (if any) the mouse is near."""
        self.hovered_card = None
        mx, my = mouse_pos

        for card in reversed(self.cards):
            if getattr(card, 'is_dragging', False):
                continue
            dx = abs(mx - getattr(card, 'target_x', mx))
            dy = abs(my - getattr(card, 'target_y', my))
            if dx < HAND_HOVER_DIST_X and dy < HAND_HOVER_DIST_Y:
                self.hovered_card = card
                break

    def _apply_targets(self):
        """
        Sets the *desired* rect centre and scale for each card this frame.
        Actual position smoothing happens in _lerp_positions().
        """
        hover_idx = (self.cards.index(self.hovered_card)
                     if self.hovered_card else None)

        for i, card in enumerate(self.cards):
            if getattr(card, 'is_dragging', False):
                continue

            if card is self.hovered_card:
                scale = CARD_HAND_SIZE_RATIO * HAND_HOVER_SCALE_MULT
                card.update_visuals(scale)
                card.target_draw_x = card.target_x
                card.target_draw_y = card.target_y - HAND_HOVER_LIFT
                card.angle         = 0
            else:
                card.update_visuals(CARD_HAND_SIZE_RATIO)
                card.angle = getattr(card, 'target_angle', 0)

                # Nudge neighbours away from the hovered card
                shift_x = 0
                if hover_idx is not None:
                    shift_x = -HAND_HOVER_SHIFT if i < hover_idx else HAND_HOVER_SHIFT

                card.target_draw_x = card.target_x + shift_x
                card.target_draw_y = card.target_y

    def _lerp_positions(self):
        """Smoothly moves each card's rect.center toward its target_draw position."""
        t = HAND_LERP_SPEED
        for card in self.cards:
            if getattr(card, 'is_dragging', False):
                continue

            tx = getattr(card, 'target_draw_x', card.target_x)
            ty = getattr(card, 'target_draw_y', card.target_y)

            # Initialise lerp position on first use
            if not hasattr(card, 'lerp_x'):
                card.lerp_x = float(tx)
                card.lerp_y = float(ty)

            card.lerp_x += (tx - card.lerp_x) * t
            card.lerp_y += (ty - card.lerp_y) * t

            card.rect.centerx = int(card.lerp_x)
            card.rect.centery = int(card.lerp_y)