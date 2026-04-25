import pygame
import ctypes

# Fix for high-DPI displays
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# ── Display ────────────────────────────────────────────────────────────────
SCREEN_SIZE  = (1600, 900)
FPS          = 60

# ── Colors ─────────────────────────────────────────────────────────────────
BG_COLOR     = (10,  10,  15)
ZONE_COLOR   = (40,  40,  60)
LABEL_COLOR  = (120, 120, 180)

# ── Card sizing ────────────────────────────────────────────────────────────
BASE_CARD_SIZE      = (1100, 1600)   # source resolution cards are normalised to
CARD_HAND_SIZE_RATIO = 0.13          # hand card size as a fraction of BASE_CARD_SIZE

# ── Hand layout ────────────────────────────────────────────────────────────
# Anchor: where the centre of the hand fan sits on screen
HAND_ANCHOR_X_OFFSET = 0            # pixels left/right from horizontal centre
HAND_ANCHOR_Y_OFFSET = -90          # pixels up from the bottom edge

# Fan geometry
HAND_SPACING         = 72           # pixels between card centres at rest
HAND_CURVE_DIP       = 6            # Y-dip (pixels) per unit of offset² — controls arc depth
HAND_ANGLE_SPREAD    = 4            # degrees of tilt per unit of offset from centre

# Hover behaviour
HAND_HOVER_SCALE_MULT  = 1.8        # hovered card is this multiple of CARD_HAND_SIZE_RATIO
HAND_HOVER_LIFT        = 160        # pixels the hovered card rises above its rest position
HAND_HOVER_SHIFT       = 36         # pixels neighbours are pushed aside on hover
HAND_HOVER_DIST_X      = 60         # X-proximity threshold to trigger hover (pixels)
HAND_HOVER_DIST_Y      = 130        # Y-proximity threshold to trigger hover (pixels)

# Smooth lerp speed (0.0 = frozen, 1.0 = instant snap)
HAND_LERP_SPEED        = 0.18

# ── Snap-to-zone ───────────────────────────────────────────────────────────
SNAP_RADIUS            = 100         # pixels — how close the card centre must be to a zone centre

DECKS = {
    "Yugi": "assets/Deck_Yugi",
    "Kaiba": "assets/Deck_Kaiba",
    "Test1": "assets/Deck_Card_Test1",
}

# Then set which ones are in use
PLAYER_DECK_PATH = DECKS["Test1"]
OPPONENT_DECK_PATH = DECKS["Test1"]

# ── Rules mode ─────────────────────────────────────────────────────────────
# "sandbox" — no restrictions, cards can do anything at any time
# "loose"   — rules are tracked and warned about, but never hard-blocked
# "strict"  — full YGO rules enforced, illegal actions are rejected
RULES_MODE = "sandbox"
STARTING_HAND_SIZE = 5
INSTANT_HAND       = True
# Cards dropped below PLAYER_HAND_Y go back into the player's hand
# Cards dropped above OPPONENT_HAND_Y go back into the opponent's hand
PLAYER_HAND_Y_THRESHOLD   = SCREEN_SIZE[1] - 140
OPPONENT_HAND_Y_THRESHOLD = 140