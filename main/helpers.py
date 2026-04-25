"""Tiny generic helpers shared across the package."""


def safe_remove(lst, item):
    """Remove *item* from *lst* if present.  Silently no-op otherwise."""
    try:
        lst.remove(item)
    except ValueError:
        pass
