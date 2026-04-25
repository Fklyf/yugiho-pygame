"""
resolve_hand_action — dispatcher for "selected hand card → target click" gestures.

Decision tree
─────────────
  1. Pending tribute summon continuation
       (selected hand card is the pending summoner; click own monster as another tribute)
  2. Fusion Monster in hand + own field monster clicked
       → start / continue collecting fusion materials, then summon.
  3. Spell / Trap in hand + any card clicked
       → activate targeting that card.
  4. Low-level monster in hand + own field monster clicked
       → normal summon (no tribute needed, direct placement).
  5. High-level monster in hand + own field monster clicked
       → start tribute selection (stored in main.tribute).
  6. Anything else → log info, clear selection.

Returns
─────────
  True   — selection consumed; caller should clear clicked_card.
  False  — caller should KEEP the selection (mid-tribute selection still in progress).
"""

from cardengine import rules
from cardengine.game import submit_action, apply_result

from config import SCREEN_SIZE

from .. import tribute
from ..announcements import arm_announcement
from ..geometry import reposition_field_card
from ..state import build_game_state
from .tribute_summon import attempt_tribute_summon


def resolve_hand_action(
    hand_card, hand_owner,          # the selected hand card
    target_card, target_owner,      # the card it was used on (field or hand)
    active_player,
    player_field, opp_field,
    player_hand,  opp_hand,
    player_lp,    opp_lp,
    player_gy,    opp_gy,
    game_objects,
    player_deck,  opp_deck,
    turn_number,
    game_phase,
    has_drawn_this_turn,
    has_summoned_this_turn=False,
):
    meta_h = getattr(hand_card,   "meta", {}) or {}
    meta_t = getattr(target_card, "meta", {}) or {}

    type_h = meta_h.get("type", hand_card.card_type)
    type_t = meta_t.get("type", target_card.card_type)

    name_h = meta_h.get("name", "?")
    name_t = meta_t.get("name", "?")

    my_hand  = player_hand  if hand_owner == "player" else opp_hand
    my_field = player_field if hand_owner == "player" else opp_field

    gs = build_game_state(
        player_hand, player_field, player_gy,
        opp_hand, opp_field, opp_gy,
        len(player_deck), len(opp_deck),
        player_lp[0], opp_lp[0],
        turn_number, active_player,
        game_phase, has_drawn_this_turn,
        has_summoned_this_turn,
    )

    target_on_field = (target_card in player_field or target_card in opp_field)

    # ── Continuation of an existing pending tribute summon ────────────────
    if (tribute.pending_card is not None
            and hand_card is tribute.pending_card
            and hand_owner == tribute.pending_owner
            and target_owner == hand_owner
            and "Monster" in str(type_t)
            and target_on_field):

        if target_card not in tribute.selected:
            tribute.selected.append(target_card)
            level  = meta_h.get("level", 0)
            needed = rules.tributes_required(hand_card)
            have   = len(tribute.selected)
            print(f"[Tribute] Selected {name_t} as tribute "
                  f"({have}/{needed} for Lv{level} {name_h}).")
        else:
            print(f"[Tribute] {name_t} is already selected.")
            return False  # keep selection active

        needed = rules.tributes_required(tribute.pending_card)
        if len(tribute.selected) >= needed:
            attempt_tribute_summon(
                tribute.pending_card, tribute.pending_owner,
                list(tribute.selected),
                player_field, opp_field,
                player_hand, opp_hand,
                gs, game_objects,
            )
            return True   # selection resolved
        return False      # still collecting tributes

    # ── Fusion Monster from hand ──────────────────────────────────────────
    if rules.is_fusion(hand_card) and target_owner == hand_owner and target_on_field:
        result = submit_action("summon", {
            "card":           hand_card,
            "owner":          hand_owner,
            "field_monsters": my_field,
            "game_state":     gs,
        })
        apply_result(result, game_objects)
        for msg in result.get("log", []):
            print(f"[Fusion] {msg}")
        if not result.get("ok"):
            print(f"[Blocked] {result.get('error')}")
            # RMB-selected — still in hand, no add_card needed
        return True

    # ── Spell / Trap activated onto a target ──────────────────────────────
    if "Spell" in str(type_h) or "Trap" in str(type_h):
        if hand_owner != active_player:
            print("[Blocked] Can't activate opponent's card.")
            return True
        hand_card.owner   = hand_owner
        target_card.owner = target_owner
        result = submit_action("activate", {
            "card":          hand_card,
            "owner":         hand_owner,
            "active_player": active_player,
            "targets":       [target_card],
            "game_state":    gs,
            "player_field":  player_field,
            "opp_field":     opp_field,
        })
        apply_result(result, game_objects)
        for msg in result.get("log", []):
            print(f"[Activate] {msg}")
        if not result.get("ok"):
            print(f"[Blocked] {result.get('error')}")
        else:
            ann = game_objects.get("ann_state", [None, 0])
            arm_announcement(result, ann)
            game_objects["ann_state"] = ann
        return True

    # ── Normal summon / tribute onto own field ────────────────────────────
    if ("Monster" in str(type_h)
            and target_owner == hand_owner
            and target_on_field
            and not rules.is_fusion(hand_card)):

        needed = rules.tributes_required(hand_card)

        if needed == 0:
            # Level 4 or lower — just place it (no target needed, but we
            # accept any own field click as the "play to field" gesture)
            ok, reason = rules.can_normal_summon(hand_card, my_field, [], gs)
            if not ok:
                print(f"[Blocked] {reason}")
                # Still in hand — no add_card needed
                return True

            # ── Find a free monster zone BEFORE submit_action so the card
            # has correct world coords by the time apply_result repositions
            # its rect. Mirrors attempt_set_card / attempt_tribute_summon.
            zones      = game_objects.get("zones", {})
            zoom_level = game_objects.get("zoom_level", 1.0)
            cam_offset = game_objects.get("cam_offset", (0, 0))

            if zones:
                zone_prefix = "P_M" if hand_owner == "player" else "O_M"
                cx, cy       = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
                cam_x, cam_y = cam_offset
                placed = False
                for i in range(1, 6):
                    zn = f"{zone_prefix}{i}"
                    if zn in zones and not any(
                            getattr(fc, "zone_name", None) == zn for fc in my_field):
                        z_rect = zones[zn]
                        hand_card.world_x   = (z_rect.centerx - cx) / zoom_level - cam_x
                        hand_card.world_y   = (z_rect.centery - cy) / zoom_level - cam_y
                        hand_card.zone_name = zn
                        placed = True
                        break
                if not placed:
                    print("[Blocked] No free Monster zone.")
                    return True

            # Detach from hand BEFORE submit_action — without these resets,
            # the Hand layout pass next frame still treats this as a hand card
            # (in_hand=True) and yanks its rect back to the hand fan position,
            # which is what made summoned monsters not snap into the grid.
            my_hand.remove_card(hand_card)
            hand_card.in_hand     = False
            hand_card.is_dragging = False
            hand_card.angle       = 0
            hand_card.owner       = hand_owner

            result = submit_action("summon", {
                "card":           hand_card,
                "owner":          hand_owner,
                "field_monsters": my_field,
                "tributes":       [],
                "game_state":     gs,
            })
            apply_result(result, game_objects)
            for msg in result.get("log", []):
                print(f"[Summon] {msg}")
            if not result.get("ok"):
                print(f"[Blocked] {result.get('error')}")
                # Roll back: card goes back to hand, clear zone stamp.
                hand_card.zone_name = None
                hand_card.in_hand   = True
                my_hand.add_card(hand_card)
            else:
                game_objects["has_summoned_this_turn"] = True
                # Refresh visuals for the placed card
                if hasattr(hand_card, "update_visuals"):
                    hand_card.update_visuals(zoom_level)
                reposition_field_card(hand_card, zoom_level, cam_offset)
            return True

        # Needs tributes — begin accumulation.
        # Guard: the clicked field card must actually be a Monster — Spell/Trap
        # cards on the field cannot be used as tributes.
        if "Monster" not in str(type_t):
            print(f"[Tribute] {name_t} is not a Monster and cannot be tributed.")
            return True

        level = meta_h.get("level", "?")
        tribute.pending_card  = hand_card
        tribute.pending_owner = hand_owner
        tribute.selected      = [target_card]
        print(f"[Tribute] Lv{level} {name_h} needs {needed} tribute(s). "
              f"Selected {name_t} (1/{needed}). "
              f"Click another own field monster to continue, or Esc to cancel.")

        if len(tribute.selected) >= needed:
            attempt_tribute_summon(
                tribute.pending_card, tribute.pending_owner,
                list(tribute.selected),
                player_field, opp_field,
                player_hand, opp_hand,
                gs, game_objects,
            )
            return True
        return False   # mid-tribute, keep selection

    print(f"[Info] No interaction defined for hand card {name_h} ({type_h}) "
          f"→ {name_t} ({type_t})")
    return True  # clear selection
