"""
ui/constants.py
---------------
Shared visual constants used across all ui submodules.

Kept in one place so tweaking a colour or size doesn't require hunting
through multiple files.
"""

from config import SCREEN_SIZE, SNAP_RADIUS   # noqa: re-exported so submodules only need one import

# ---------------------------------------------------------------------------
# Zone sets
# ---------------------------------------------------------------------------
PLAYER_ZONES   = ({f"P_M{i}"   for i in range(1, 6)} |
                  {f"P_S/T{i}" for i in range(1, 6)} |
                  {"P_Field"})
OPPONENT_ZONES = ({f"O_M{i}"   for i in range(1, 6)} |
                  {f"O_S/T{i}" for i in range(1, 6)} |
                  {"O_Field"})

# ---------------------------------------------------------------------------
# Field overlay colours
# ---------------------------------------------------------------------------
SNAP_FILL          = (220, 200,  80,  55)
SNAP_BORDER        = (220, 200,  80, 255)
DEF_BORDER         = ( 80, 160, 220, 255)
DEF_BORDER_WIDTH   = 2
HOVER_FILL         = (255, 255, 255,  25)
HOVER_BORDER       = (200, 200, 255, 200)
HOVER_BORDER_WIDTH = 2

# ---------------------------------------------------------------------------
# HUD colours
# ---------------------------------------------------------------------------
HUD_PLAYER_COL     = ( 80, 180,  80)
HUD_OPPONENT_COL   = (180,  80,  80)
HUD_DECK_COL       = (160, 160, 160)
HUD_HINT_COL       = ( 80,  80, 100)
HUD_EXPORT_COL     = (100, 220, 100)

# ---------------------------------------------------------------------------
# Selection / interaction colours
# ---------------------------------------------------------------------------
SEL_BORDER         = (255, 215,   0)   # gold — first selected card
SEL_BORDER_WIDTH   = 3
TARGET_BORDER      = (255,  80,  80)   # red — valid interaction target
TARGET_BORDER_W    = 2
INFO_BG            = ( 15,  15,  30, 210)
INFO_BORDER        = ( 80,  80, 120)

# ---------------------------------------------------------------------------
# LP widget colours
# ---------------------------------------------------------------------------
LP_BOX_PLAYER_IDLE   = ( 30,  55,  30)
LP_BOX_PLAYER_HOVER  = ( 45,  80,  45)
LP_BOX_OPP_IDLE      = ( 55,  30,  30)
LP_BOX_OPP_HOVER     = ( 80,  45,  45)
LP_BOX_ACTIVE_FILL   = ( 20,  20,  50)
LP_BOX_BORDER_IDLE   = (100, 100, 100)
LP_BOX_BORDER_ACTIVE = (200, 200,  80)
LP_TEXT_NORMAL       = (220, 220, 220)
LP_TEXT_LOW          = (220,  80,  80)
LP_LABEL_COL         = (140, 140, 140)
LP_CURSOR_COL        = (220, 220,  80)

_LP_BOX_W  = 200
_LP_BOX_H  = 60
_LP_MARGIN = 14
_LP_PAD    = 10

# ---------------------------------------------------------------------------
# Phase button colours
# ---------------------------------------------------------------------------
PHASE_BTN_BG_IDLE         = ( 40,  70, 120)
PHASE_BTN_BG_HOVER        = ( 70, 110, 170)
PHASE_BTN_BG_DISABLED     = ( 60,  60,  60)
PHASE_BTN_FG_IDLE         = (220, 230, 245)
PHASE_BTN_FG_HOVER        = (255, 255, 255)
PHASE_BTN_FG_DISABLED     = (140, 140, 140)
PHASE_BTN_BORDER_IDLE     = ( 90, 130, 180)
PHASE_BTN_BORDER_HOVER    = (140, 180, 230)
PHASE_BTN_BORDER_DISABLED = ( 90,  90,  90)

_PHASE_BTN_W   = 150
_PHASE_BTN_H   = 36
_PHASE_BTN_GAP = 12

# ---------------------------------------------------------------------------
# Announcement colours
# ---------------------------------------------------------------------------
_ANN_SPELL_BG      = (10,  10,  40, 200)
_ANN_SPELL_TITLE   = (180, 140, 255)
_ANN_SPELL_BODY    = (210, 210, 255)
_ANN_DAMAGE_BG     = (40,  10,  10, 200)
_ANN_DAMAGE_TITLE  = (255, 120,  80)
_ANN_DAMAGE_BODY   = (255, 200, 180)
_ANN_BORDER_SPELL  = (120,  80, 220)
_ANN_BORDER_DAMAGE = (200,  60,  40)

# ---------------------------------------------------------------------------
# Quick-effect button colours
# ---------------------------------------------------------------------------
QE_BTN_W        = 72
QE_BTN_H        = 22
QE_BTN_GAP_Y    = 4
QE_STACK_STEP   = 26

QE_BG_IDLE      = ( 30,  60,  20, 210)
QE_BG_HOVER     = ( 60, 130,  40, 230)
QE_BORDER_IDLE  = ( 80, 180,  60, 255)
QE_BORDER_HOVER = (140, 230,  90, 255)
QE_TEXT_COL     = (220, 255, 180)
QE_ICON         = "⚡"
