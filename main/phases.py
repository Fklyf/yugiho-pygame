"""
Phase advancement — shared by Space key and the Next Phase button.

Auto-advance Draw → Main happens elsewhere (right after a successful draw)
— this helper handles the manual Main → Battle → End walk.

Going past End is intentionally a no-op; ending the turn is Tab's job, so
the player explicitly chooses between "next phase" and "end turn".
"""

from .constants import PHASES


def advance_phase(current_phase, active_player):
    """Return the new phase, or *current_phase* unchanged if no advance is legal."""
    try:
        idx = PHASES.index(current_phase)
    except ValueError:
        return current_phase
    if idx < 0 or idx >= len(PHASES) - 1:
        if current_phase == "End":
            print("[Phase] Already at End Phase. Press Tab to end turn.")
        return current_phase
    new_phase = PHASES[idx + 1]
    print(f"[Phase] {active_player.upper()} — {new_phase} Phase")
    return new_phase
