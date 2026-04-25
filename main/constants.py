"""
Shared constants for the entry-point package.

These were scattered at the top of the old Main.py.  They're collected here
so submodules can import what they need without dragging in the whole event
loop.
"""

# Pixels the mouse must move while holding LMB on a hand card before the card
# is lifted into a drag.  Below this threshold, releasing the button registers
# as a plain "select" click.
DRAG_THRESHOLD = 6

# Turn phases in order.  We cycle through them with Tab (end-turn advances
# automatically to Draw Phase for the new active player).
PHASES = ["Draw", "Main", "Battle", "End"]

# Zone-name sets used by snap-to-zone logic in geometry.try_snap().
PLAYER_ZONES = (
    {f"P_M{i}"   for i in range(1, 6)} |
    {f"P_S/T{i}" for i in range(1, 6)} |
    {"P_Field"}
)
OPPONENT_ZONES = (
    {f"O_M{i}"   for i in range(1, 6)} |
    {f"O_S/T{i}" for i in range(1, 6)} |
    {"O_Field"}
)
