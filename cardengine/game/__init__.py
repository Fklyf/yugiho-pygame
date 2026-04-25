"""
cardengine/game/__init__.py
---------------------------
Makes `game` a package and re-exports the public API so Main.py needs
no changes — it still does:

    from cardengine.game import submit_action, apply_result
"""

from .core import submit_action, apply_result  # noqa: F401
