"""
resolve_interaction — dispatcher for "selected field card → other field card" gestures.

Decision tree
─────────────
  Case 1: Pending tribute summon continuation (clicking own monsters as tributes).
  Case 2: Monster vs opponent monster → attack, with a damage preview armed
           for any quick-effect (Kuriboh-style) battle-damage negation buttons.
  Case 3: Spell / Trap activated targeting a card.
  Case 4: Same-owner monster → own field monster
            4a. Fusion Summon (uses on-field monsters as materials)
            4b. Normal/Tribute Summon (rare via field route, but supported)
"""

from cardengine import rules, battle
from cardengine.game import submit_action, apply_result

from .. import tribute
from ..announcements import arm_announcement
from ..state import build_game_state, card_to_state
from .tribute_summon import attempt_tribute_summon


def resolve_interaction(
    card_a, owner_a,
    card_b, owner_b,
    active_player,
    player_field, opp_field,
    player_hand,  opp_hand,
    player_lp,    opp_lp,
    player_gy,    opp_gy,
    game_objects,
    player_deck,  opp_deck,
    turn_number,
    game_phase="Main",
    has_drawn_this_turn=False,
    has_summoned_this_turn=False,
):
    """Decides what cardengine action to fire when field card_a is used on card_b."""
    meta_a = getattr(card_a, "meta", {}) or {}
    meta_b = getattr(card_b, "meta", {}) or {}

    type_a = meta_a.get("type", card_a.card_type)
    type_b = meta_b.get("type", card_b.card_type)

    name_a = meta_a.get("name", "?")
    name_b = meta_b.get("name", "?")

    my_field = player_field if owner_a == "player" else opp_field

    gs = build_game_state(
        player_hand, player_field, player_gy,
        opp_hand, opp_field, opp_gy,
        len(player_deck), len(opp_deck),
        player_lp[0], opp_lp[0],
        turn_number, active_player,
        game_phase, has_drawn_this_turn,
        has_summoned_this_turn,
    )

    # ── Case 1: Continuation of a pending tribute summon ──────────────────
    if (tribute.pending_card is not None
            and card_a is tribute.pending_card
            and owner_a == tribute.pending_owner
            and owner_b == owner_a
            and "Monster" in str(type_b)
            and (card_b in player_field or card_b in opp_field)):

        if card_b not in tribute.selected:
            tribute.selected.append(card_b)
            level  = (getattr(tribute.pending_card, "meta", {}) or {}).get("level", 0)
            needed = rules.tributes_required(tribute.pending_card)
            have   = len(tribute.selected)
            print(f"[Tribute] Selected {name_b} as tribute "
                  f"({have}/{needed} for Lv{level} {name_a}).")
        else:
            print(f"[Tribute] {name_b} is already selected as a tribute.")
            return

        needed = rules.tributes_required(tribute.pending_card)
        if len(tribute.selected) >= needed:
            attempt_tribute_summon(
                tribute.pending_card, tribute.pending_owner,
                list(tribute.selected),
                player_field, opp_field,
                player_hand, opp_hand,
                gs, game_objects,
            )
        return

    # ── Case 2: Monster attacks opponent's monster ─────────────────────────
    if ("Monster" in type_a and "Monster" in type_b and owner_a != owner_b):
        card_a.owner = owner_a
        card_b.owner = owner_b

        # Build a minimal game_state for stat calc (continuous effects need GYs).
        mini_gs = {
            "active_player": owner_a,
            "player":   {"graveyard": [card_to_state(c) for c in player_gy.cards]},
            "opponent": {"graveyard": [card_to_state(c) for c in opp_gy.cards]},
        }

        # Pre-resolve the battle to know what damage the player WOULD take, so
        # the ⚡ Kuriboh button knows how much to offer to negate.  This is
        # purely a lookahead — we resolve again after apply_result for the
        # canonical numbers.
        preview = battle.resolve_attack(card_a, card_b, mini_gs)
        prev_dmg    = preview.get("damage", 0)
        prev_target = preview.get("damage_target")
        # pending_battle_damage represents damage incoming to the *player*
        # (the user) — only set it when the user is the one taking the hit.
        game_objects["pending_battle_damage"] = (
            prev_dmg if prev_target == "player" else 0
        )

        result = submit_action("attack", {
            "attacker":      card_a,
            "defender":      card_b,
            "active_player": owner_a,
            "game_state":    gs,
        })
        apply_result(result, game_objects)
        for msg in result["log"]:
            print(f"[Battle] {msg}")

        if not result["ok"]:
            print(f"[Blocked] {result['error']}")
            game_objects["pending_battle_damage"] = 0
            return

        # ----- Apply battle damage to LP -----
        # cardengine.game.apply_result currently doesn't mutate LP for
        # monster-vs-monster combat, so we apply it here using the same
        # pattern as attempt_direct_attack (mutate player_lp[0] / opp_lp[0]).
        #
        # Honor Kuriboh / similar quick effects: if the player armed a
        # battle-damage-negation effect at any point before this attack
        # resolved, zero out damage to the player and consume the flag.
        # This decouples Kuriboh from `pending_battle_damage`, which is set
        # AFTER the player has already clicked the ⚡ button — using the
        # flag means click-timing no longer matters.
        # Damage to the opponent is unaffected (Kuriboh only protects the user).
        br = battle.resolve_attack(card_a, card_b, mini_gs)
        dmg        = br.get("damage", 0)
        dmg_target = br.get("damage_target")

        if (dmg_target == "player"
                and game_objects.get("battle_damage_negation_pending", False)):
            print(f"[Battle] Battle damage to player negated by quick effect.")
            dmg = 0
            game_objects["battle_damage_negation_pending"] = False

        if dmg > 0 and dmg_target in ("player", "opponent"):
            if dmg_target == "player":
                player_lp[0] = max(0, player_lp[0] - dmg)
                remaining    = player_lp[0]
                target_str   = "Player"
            else:
                opp_lp[0]    = max(0, opp_lp[0] - dmg)
                remaining    = opp_lp[0]
                target_str   = "Opponent"

            attacker_name = (getattr(card_a, "meta", {}) or {}).get("name", "?")
            print(f"[Battle] {attacker_name} deals {dmg} damage to "
                  f"{target_str}. {target_str} LP: {remaining:,}")

            ann = game_objects.get("ann_state", [None, 0])
            arm_announcement({
                "announcement_title": f"⚔ {dmg} Battle Damage!",
                "announcement_body":  [
                    f"{attacker_name} deals {dmg} damage to {target_str}.",
                    f"{target_str} LP: {remaining:,}",
                ],
                "announcement_kind":  "damage",
            }, ann)
            game_objects["ann_state"] = ann

        # Reset pending damage now that attack is fully resolved
        game_objects["pending_battle_damage"] = 0
        return

    # ── Case 3: Spell/Trap activated targeting a card ─────────────────────
    if "Spell" in type_a or "Trap" in type_a:
        if owner_a != active_player:
            print("[Blocked] Can't activate opponent's card.")
            return
        card_a.owner = owner_a
        card_b.owner = owner_b
        result = submit_action("activate", {
            "card":          card_a,
            "owner":         owner_a,
            "active_player": active_player,
            "targets":       [card_b],
            "game_state":    gs,
            "player_field":  player_field,
            "opp_field":     opp_field,
        })
        apply_result(result, game_objects)
        for msg in result["log"]:
            print(f"[Activate] {msg}")
        if not result["ok"]:
            print(f"[Blocked] {result['error']}")
        else:
            ann = game_objects.get("ann_state", [None, 0])
            arm_announcement(result, ann)
            game_objects["ann_state"] = ann
        return

    # ── Case 4: Same-owner monster → own field monster ────────────────────
    if owner_a == owner_b:
        is_b_on_field = card_b in player_field or card_b in opp_field
        type_str = str(type_a)

        if "Monster" in type_str and is_b_on_field:

            # 4a: Fusion Summon
            if rules.is_fusion(card_a):
                result = submit_action("summon", {
                    "card":           card_a,
                    "owner":          owner_a,
                    "field_monsters": my_field,
                    "game_state":     gs,
                })
                apply_result(result, game_objects)
                for msg in result.get("log", []):
                    print(f"[Fusion] {msg}")
                if not result.get("ok"):
                    print(f"[Blocked] {result.get('error')}")
                    # Field card — not in hand, no add_card needed
                return

            # 4b: Normal / Tribute Summon
            needed = rules.tributes_required(card_a)

            if needed == 0:
                result = submit_action("summon", {
                    "card":           card_a,
                    "owner":          owner_a,
                    "field_monsters": my_field,
                    "tributes":       [],
                    "game_state":     gs,
                })
                apply_result(result, game_objects)
                for msg in result.get("log", []):
                    print(f"[Summon] {msg}")
                if not result.get("ok"):
                    print(f"[Blocked] {result.get('error')}")
                    # Field card — not in hand, no add_card needed
                else:
                    game_objects["has_summoned_this_turn"] = True
                return

            # Guard: card_b must be a Monster to be tributed
            if "Monster" not in str(type_b):
                print(f"[Tribute] {name_b} is not a Monster and cannot be tributed.")
                return

            level = meta_a.get("level", "?")
            tribute.pending_card  = card_a
            tribute.pending_owner = owner_a
            tribute.selected      = [card_b]
            print(f"[Tribute] Lv{level} {name_a} needs {needed} tribute(s). "
                  f"Selected {name_b} (1/{needed}). "
                  f"Click another own monster to add more, or Esc to cancel.")

            if len(tribute.selected) >= needed:
                attempt_tribute_summon(
                    tribute.pending_card, tribute.pending_owner,
                    list(tribute.selected),
                    player_field, opp_field,
                    player_hand, opp_hand,
                    gs, game_objects,
                )
            return

    print(f"[Info] No interaction defined for {name_a} ({type_a}) "
          f"→ {name_b} ({type_b})")
