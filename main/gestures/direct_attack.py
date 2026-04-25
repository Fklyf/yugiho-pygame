"""
attempt_direct_attack — friendly monster attacks the opposing player's LP
directly when the opponent's monster zone is empty.

Only legal in Battle Phase.  Marks ``attacker.attack_used = True`` on success.
Honors the Kuriboh-style "battle_damage_negation_pending" flag in game_objects
when the attacker is the opponent.
"""

from cardengine import battle

from ..announcements import arm_announcement
from ..state import card_to_state


def attempt_direct_attack(
    attacker, attacker_owner,
    player_field, opp_field,
    player_gy, opp_gy,
    player_lp, opp_lp,
    game_objects,
    turn_number, active_player, game_phase,
):
    """
    NOTE: ATK is read via battle.get_effective_atk so continuous modifiers
    apply (e.g. Dark Magician Girl's +300 per Dark Magician / Magician of
    Black Chaos in either GY). For that, we build a minimal game_state
    containing both graveyards — the only fields DMG's handler reads.
    """
    if game_phase != "Battle":
        print("[Direct Attack] Can only attack during Battle Phase.")
        return False

    if attacker_owner != active_player:
        print("[Direct Attack] It is not your turn.")
        return False

    defender_field = opp_field if attacker_owner == "player" else player_field
    face_up_monsters = [
        c for c in defender_field
        if "Monster" in getattr(c, "card_type", "")
        and getattr(c, "mode", "ATK") != "SET"
    ]
    if face_up_monsters:
        print("[Direct Attack] Opponent has monsters — cannot attack directly.")
        return False

    if getattr(attacker, "summoning_sickness", False):
        print("[Direct Attack] This monster has summoning sickness.")
        return False
    if getattr(attacker, "attack_used", False):
        print("[Direct Attack] This monster already attacked this turn.")
        return False

    meta_a = getattr(attacker, "meta", {}) or {}
    # Build a minimal game_state — DMG's continuous_atk_mod only reads
    # game_state[side]["graveyard"], so we only need the graveyards here.
    # If other future continuous effects need more state (field, LP, phase),
    # extend this dict or switch to the full build_game_state(...) helper.
    mini_state = {
        "active_player": active_player,
        "player":   {"graveyard": [card_to_state(c) for c in player_gy.cards]},
        "opponent": {"graveyard": [card_to_state(c) for c in opp_gy.cards]},
    }
    atk    = battle.get_effective_atk(attacker, mini_state)
    name_a = meta_a.get("name", "?")

    # Store ATK so the ⚡ Kuriboh button knows how much damage is incoming.
    # Main loop reads this back from game_objects each frame.
    game_objects["pending_battle_damage"] = atk

    # Honor Kuriboh-style negation flag (set when the player activates a
    # quick effect that negates the next battle damage event).  Direct
    # attacks always damage the player when the opponent is attacking, and
    # never damage the player when the player is attacking — so we only
    # consume the flag in the "opponent attacks player directly" branch.
    negation_active = (
        attacker_owner != "player"
        and game_objects.get("battle_damage_negation_pending", False)
    )
    if negation_active:
        atk = 0
        game_objects["battle_damage_negation_pending"] = False
        print("[Direct Attack] Battle damage to player negated by quick effect.")

    if attacker_owner == "player":
        opp_lp[0]  = max(0, opp_lp[0] - atk)
        target_str = "Opponent"
        remaining  = opp_lp[0]
    else:
        player_lp[0] = max(0, player_lp[0] - atk)
        target_str   = "Player"
        remaining    = player_lp[0]

    attacker.attack_used = True

    print(f"[Direct Attack] {name_a} attacks directly for {atk}! "
          f"{target_str} LP: {remaining:,}")

    ann = game_objects.get("ann_state", [None, 0])
    arm_announcement({
        "announcement_title": f"⚔ {atk} Direct Attack!",
        "announcement_body": [
            f"{name_a} attacks {target_str} directly!",
            f"{target_str} LP: {remaining:,}",
        ],
        "announcement_kind": "damage",
    }, ann)
    game_objects["ann_state"] = ann
    return True
