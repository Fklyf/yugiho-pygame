"""
main — YGO Field Tracker entry point package.

Split from the original monolithic Main.py for maintainability. See the
module-level docstrings inside each submodule for what lives where.

Quick map
─────────
  constants      DRAG_THRESHOLD, PHASES, zone-name sets
  geometry       Coordinate conversion + snap-to-zone
  phases         advance_phase()
  state          Game-state serialisation + card loading
  tribute        Pending tribute-summon selection state (shared)
  announcements  Centre-screen banner helper
  helpers        safe_remove()
  gestures/      Per-gesture resolvers (summon/set/flip/attack/etc.)
                 — named to avoid collision with cardengine "actions"
  game_loop      The main pygame event loop (run_game)
  entry          main() — crash-log wrapper around run_game()
"""

from .entry import main

__all__ = ["main"]
