"""
Mutable state for an in-progress tribute summon.

In the original Main.py these were three module-level globals:

    pending_summon_card  = None
    pending_summon_owner = None
    selected_tributes    = []

…with `global` declarations sprinkled across every helper that touched
them.  After the split, `global` no longer crosses module boundaries, so
we promote them to attributes on this module.  Any importer can now do:

    from main import tribute

    if tribute.pending_card is not None:        # read
        ...
    tribute.pending_card  = some_card           # write
    tribute.pending_owner = "player"
    tribute.selected      = [target_card]
    tribute.reset()                             # clear all three

Reads/writes go through the module object, so every importer sees the
same values — same semantics as the old globals.
"""

# Currently pending tribute summon — the high-level monster being summoned.
pending_card  = None

# Owner of the pending summon ("player" or "opponent").
pending_owner = None

# Cards already chosen as tributes.  Replaced (not mutated) by callers,
# but kept as a list for ergonomic iteration.
selected: list = []


def reset() -> None:
    """Clear all three selection fields back to empty/None."""
    global pending_card, pending_owner, selected
    pending_card  = None
    pending_owner = None
    selected      = []


def cancel(hand_obj) -> None:
    """
    Cancel the pending summon.  Returns the summoning card to *hand_obj*
    if it was actually pulled off the hand earlier; if it was only
    RMB-selected (still in hand) we skip the add to avoid duplicating it.
    """
    global pending_card
    if pending_card is not None:
        name = (getattr(pending_card, "meta", {}) or {}).get("name", "?")
        already_in_hand = (pending_card in getattr(hand_obj, "cards", [])
                           or pending_card.in_hand)
        if not already_in_hand:
            pending_card.in_hand = True
            hand_obj.add_card(pending_card)
        print(f"[Tribute] Summon cancelled — {name} returned to hand.")
    reset()
