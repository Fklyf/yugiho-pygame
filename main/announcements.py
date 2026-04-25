"""
Centre-screen announcement banner helper.

Used by every action helper that fires a card effect — they call
arm_announcement(result, ann_state) so the draw loop can render the
banner on the next frame.
"""


def arm_announcement(result: dict, announcement_state: list) -> None:
    """
    Reads announcement keys written by effect handlers into a result dict
    and stores them in announcement_state so the draw loop can display them.

    announcement_state is a 2-element list [announcement, timer] so it can
    be mutated from inside nested functions without nonlocal declarations:

        announcement_state = [None, 0]
        arm_announcement(result, announcement_state)
        announcement, timer = announcement_state

    Keys read from result (all optional):
        "announcement_title"  str
        "announcement_body"   list[str]
        "announcement_kind"   "spell" | "damage"

    Falls back to effect_message as a single body line if title is absent.
    """
    title = result.get("announcement_title")
    body  = result.get("announcement_body", [])
    kind  = result.get("announcement_kind", "spell")

    if not title:
        msg = result.get("effect_message")
        if msg:
            title = "Card Effect"
            body  = [msg]

    if title:
        announcement_state[0] = {"title": title, "body": body, "kind": kind}
        announcement_state[1] = 180   # 3 seconds at 60 fps
