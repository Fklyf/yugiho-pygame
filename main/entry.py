"""
main() — top-level entry point.

Wraps run_game() in a try/except so any unhandled exception is written to
crash_log.txt with a timestamp before the window closes.  This is the same
behaviour the original Main.py had — it just lives in its own file now.
"""

import datetime
import traceback

import pygame

from .game_loop import run_game


def main():
    try:
        run_game()
    except Exception:
        msg = traceback.format_exc()
        print(msg)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open("crash_log.txt", "a") as f:
                f.write(f"--- {ts} ---\n{msg}\n")
        except Exception:
            pass
        input("Press Enter to exit...")
    finally:
        pygame.quit()
