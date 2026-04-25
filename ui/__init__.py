"""
ui/__init__.py
--------------
Re-exports the full public API so that Main.py's existing import:

    from ui import draw_snap_highlight, draw_field_overlays, draw_hud,
                   lp_hit_test, draw_selection_highlight, draw_card_info_panel,
                   draw_announcement, phase_btn_hit_test

continues to work without any changes.

New additions (quick effects) are also exported here, so Main.py can add:

    from ui import draw_quick_effect_buttons, quick_effect_btn_hit_test
"""

from ui.field         import (draw_snap_highlight,
                               draw_field_overlays,
                               draw_selection_highlight)
from ui.hud           import (draw_hud,
                               lp_hit_test,
                               phase_btn_hit_test)
from ui.cards         import draw_card_info_panel
from ui.announcements import draw_announcement
from ui.quick_effects import (draw_quick_effect_buttons,
                               quick_effect_btn_hit_test)

__all__ = [
    # field
    "draw_snap_highlight",
    "draw_field_overlays",
    "draw_selection_highlight",
    # hud
    "draw_hud",
    "lp_hit_test",
    "phase_btn_hit_test",
    # cards
    "draw_card_info_panel",
    # announcements
    "draw_announcement",
    # quick effects
    "draw_quick_effect_buttons",
    "quick_effect_btn_hit_test",
]
