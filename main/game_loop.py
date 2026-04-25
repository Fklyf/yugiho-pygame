"""
run_game — pygame event loop and renderer.

This is by far the largest module in the package because it owns the game's
mutable state for the lifetime of one run: zoom/camera, drag/click state,
turn number, phase, LP, hand/field lists, and so on.  Per-gesture logic has
been pushed out to main.gestures.* — this module just dispatches to them.

State that other modules read:
  • main.tribute.pending_card / .pending_owner / .selected — shared via
    the tribute module so resolvers can read/write without `global`.

State carried via the game_objects dict (passed into apply_result and the
action helpers):
  • zoom_level, cam_offset, zones — for screen-space card placement
  • ann_state — 2-element [announcement, timer] list
  • pending_battle_damage — for the ⚡ Kuriboh quick-effect button
  • battle_damage_negation_pending — set by Kuriboh, consumed on next damage
"""

import json
import os
import random

import pygame

from config import (
    SCREEN_SIZE, BG_COLOR, FPS,
    PLAYER_HAND_Y_THRESHOLD,
    OPPONENT_HAND_Y_THRESHOLD,
    PLAYER_DECK_PATH,
    OPPONENT_DECK_PATH,
    STARTING_HAND_SIZE,
    INSTANT_HAND,
)

from engine.field import draw_field_zones
from engine.hand import Hand
from engine.graveyard import Graveyard

from ui import (
    draw_snap_highlight, draw_field_overlays, draw_hud, lp_hit_test,
    draw_selection_highlight, draw_card_info_panel, draw_announcement,
    phase_btn_hit_test, draw_quick_effect_buttons, quick_effect_btn_hit_test,
)
from ui.hud import draw_qe_panel_button, qe_panel_btn_hit_test
from ui.quick_effects import (
    open_panel as qe_open, close_panel as qe_close,
    is_open as qe_is_open, draw_panel as qe_draw_panel,
    panel_hit_test as qe_panel_hit_test,
)

from cardengine.effects import get_quick_effects
import cardengine                                          # auto-registers all card effects
from cardengine.game import submit_action, apply_result
from cardengine import rules

import ui_graveyard_viewer as gy_viewer

# Local package imports
from . import tribute
from .announcements import arm_announcement
from .constants import DRAG_THRESHOLD
from .geometry import (
    try_snap,
    reposition_field_card,
    reposition_all_field_cards,
    is_own_side_click,
)
from .helpers import safe_remove
from .phases import advance_phase
from .state import (
    card_to_state,
    build_game_state,
    export_game_state,
    load_card,
)
from .gestures.hand import resolve_hand_action
from .gestures.field import resolve_interaction
from .gestures.direct_attack import attempt_direct_attack
from .gestures.set_card import attempt_set_card
from .gestures.flip_activate import attempt_flip_activate


def run_game():
    pygame.init()
    screen     = pygame.display.set_mode(SCREEN_SIZE)
    pygame.display.set_caption("YGO Field Tracker")
    clock      = pygame.time.Clock()
    font       = pygame.font.SysFont("Arial", 18, bold=True)
    small_font = pygame.font.SysFont("Arial", 14)

    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2

    # ── Deck loading ───────────────────────────────────────────────────────
    try:
        with open(f"{PLAYER_DECK_PATH}/metadata.json", encoding="utf-8") as f:
            raw_p = json.load(f)
            p_data = raw_p["data"] if isinstance(raw_p, dict) and "data" in raw_p else raw_p

        with open(f"{OPPONENT_DECK_PATH}/metadata.json", encoding="utf-8") as f:
            raw_o = json.load(f)
            o_data = raw_o["data"] if isinstance(raw_o, dict) and "data" in raw_o else raw_o

    except Exception as e:
        print(f"Deck load error: {e}")
        return

    player_deck = list(p_data)
    random.shuffle(player_deck)
    opp_deck = list(o_data)
    random.shuffle(opp_deck)

    # Card back
    bp = "assets/card_back.png"
    back_img = pygame.image.load(bp).convert_alpha() if os.path.exists(bp) \
               else pygame.Surface((400, 580))
    if not os.path.exists(bp):
        back_img.fill((50, 50, 50))

    # ── Game objects ───────────────────────────────────────────────────────
    player_hand  = Hand()
    player_field = []
    player_gy    = Graveyard()

    opp_hand  = Hand(visible=False)
    opp_field = []
    opp_gy    = Graveyard()

    active_hand_obj   = player_hand
    inactive_hand_obj = opp_hand

    # Camera
    zoom_level     = 1.0
    cam_x, cam_y   = 0.0, 0.0
    is_panning     = False

    # ── Card interaction state ─────────────────────────────────────────────
    # selected_card / selected_owner: card currently being DRAGGED
    selected_card  = None
    selected_owner = None

    # clicked_card / clicked_owner: card that has been LEFT-CLICKED once
    # (gold border; used to initiate interactions on the next click)
    clicked_card  = None
    clicked_owner = None

    # drag_candidate: a hand card that the player pressed LMB on but hasn't
    # moved far enough yet to trigger a drag.  Stored so we can either
    # promote to a drag (on MOUSEMOTION) or treat as a select (on MOUSEUP).
    drag_candidate       = None
    drag_candidate_owner = None
    drag_start_pos       = None   # screen position of the initial press

    # field_drag_candidate: threshold system for placed field cards.
    # Saves original zone/world so a tiny nudge snaps back without
    # triggering the game engine.
    field_drag_candidate       = None
    field_drag_candidate_owner = None
    field_drag_start_pos       = None
    field_drag_saved_zone      = None   # zone_name before lift
    field_drag_saved_world     = None   # (world_x, world_y) before lift

    # ── Turn / phase state ─────────────────────────────────────────────────
    turn_number            = 1
    active_player          = "player"
    has_drawn_this_turn    = False
    has_summoned_this_turn = False

    # Opening hand draw tracking (only used when INSTANT_HAND = False).
    # Each player clicks their deck freely until they've drawn STARTING_HAND_SIZE
    # cards, after which the game enters the normal Draw Phase.
    if INSTANT_HAND:
        game_phase = "Draw"
        opening_draws_remaining = {"player": 0, "opponent": 0}
    else:
        game_phase = "Opening"
        opening_draws_remaining = {
            "player":   STARTING_HAND_SIZE,
            "opponent": STARTING_HAND_SIZE,
        }
        print(f"[Setup] Click your deck {STARTING_HAND_SIZE} times to draw your opening hand.")

    # Life points
    player_lp = [8000]
    opp_lp    = [8000]

    # Double-click detection for hand Spell/Trap cards (LMB).
    _dbl_last_card = None   # card clicked on last LMB down
    _dbl_last_time = 0      # pygame.time.get_ticks() of that click
    DBL_CLICK_MS   = 400    # milliseconds window

    zones        = {}
    export_flash = 0
    lp_edit_target  = None
    lp_input_buffer = ""
    pending_battle_damage = 0   # ATK of the attacking monster; set on attack declaration

    # Announcement banner state
    # Set announcement + announcement_timer whenever a spell fires or damage lands.
    announcement       = None   # dict: {title, body, kind}  |  None
    announcement_timer = 0      # frames remaining (180 = 3 s at 60 fps)

    # Mutable 2-element list so nested helpers can arm it without nonlocal
    ann_state = [announcement, announcement_timer]

    # Quick-effect panel — closed until the player clicks the HUD button
    qe_close()
    quick_effs = []   # computed each frame; pre-declare so event handler sees it

    # Reset shared tribute state at game start (in case a prior run left it set)
    tribute.reset()

    # ── game_objects dict passed to apply_result ───────────────────────────
    # Includes helper references so apply_result can drive the draw action
    # without any coupling back to this module's local scope.
    game_objects = {
        "player_field":    player_field,
        "opp_field":       opp_field,
        "player_gy":       player_gy,
        "opp_gy":          opp_gy,
        "player_hand":     player_hand,
        "opp_hand":        opp_hand,
        "player_lp":       player_lp,
        "opp_lp":          opp_lp,
        "player_deck":     player_deck,
        "opp_deck":        opp_deck,
        "player_deck_path": PLAYER_DECK_PATH,
        "opp_deck_path":    OPPONENT_DECK_PATH,
        "active_player":   active_player,
        "has_drawn_this_turn":    has_drawn_this_turn,
        "has_summoned_this_turn": has_summoned_this_turn,
        "load_card":       load_card,
        "back_img":        back_img,
        # Spatial helpers used by attempt_tribute_summon for screen placement
        "zoom_level": 1.0,
        "cam_offset": (0.0, 0.0),
        "zones":      {},
        # Announcement state — shared with helper functions
        "ann_state":  ann_state,
    }

    # ── Opening hand ───────────────────────────────────────────────────────
    # When INSTANT_HAND is True, both players start with STARTING_HAND_SIZE
    # cards already in hand.  When False, players draw manually each turn.
    if INSTANT_HAND:
        for _ in range(min(STARTING_HAND_SIZE, len(player_deck))):
            card_data  = player_deck.pop()
            drawn_card = load_card(card_data, PLAYER_DECK_PATH, back_img)
            player_hand.add_card(drawn_card)

        for _ in range(min(STARTING_HAND_SIZE, len(opp_deck))):
            card_data  = opp_deck.pop()
            drawn_card = load_card(card_data, OPPONENT_DECK_PATH, back_img)
            opp_hand.add_card(drawn_card)

        print(f"[Setup] Opening hands dealt ({STARTING_HAND_SIZE} cards each).")
    else:
        print("[Setup] INSTANT_HAND disabled — players draw manually.")

    HINTS = [
        "RMB: select hand/field card  |  click selected card on target to interact",
        "LMB hand card: drag to field  |  RMB field card: cycle ATK / DEF / SET",
        "MMB drag: pan   |   Scroll: zoom   |   Tab: end turn   |   Del: send → GY",
        "Deck click draws (Draw Phase only, once per turn)   |   Esc: cancel / deselect",
    ]

    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()
        screen.fill(BG_COLOR)

        # Keep game_objects in sync with mutable locals
        game_objects["active_player"]          = active_player
        game_objects["has_drawn_this_turn"]    = has_drawn_this_turn
        game_objects["has_summoned_this_turn"] = has_summoned_this_turn

        # Pull back any flags mutated inside helper functions
        has_drawn_this_turn    = game_objects["has_drawn_this_turn"]
        has_summoned_this_turn = game_objects["has_summoned_this_turn"]
        pending_battle_damage  = game_objects.get("pending_battle_damage", pending_battle_damage)

        # Sync announcement state from game_objects (helpers write to ann_state)
        ann_state          = game_objects["ann_state"]
        announcement       = ann_state[0]
        announcement_timer = ann_state[1]

        zones    = draw_field_zones(screen, zoom_level, (cam_x, cam_y), font,
                                    active_player=active_player)

        # Keep spatial helpers available to attempt_tribute_summon
        game_objects["zoom_level"] = zoom_level
        game_objects["cam_offset"] = (cam_x, cam_y)
        game_objects["zones"]      = zones
        p_deck_z = zones.get("P_Deck")
        p_gy_z   = zones.get("P_GY")
        o_deck_z = zones.get("O_Deck")
        o_gy_z   = zones.get("O_GY")

        if selected_card and selected_owner:
            draw_snap_highlight(screen, zones, mouse_pos, selected_owner)

        # ── Events ────────────────────────────────────────────────────────
        for event in pygame.event.get():
            # GY viewer absorbs all events while open — must come first so
            # it can close itself on Esc/RMB without the underlying game
            # reacting to those events.
            if gy_viewer.is_open():
                if gy_viewer.handle_event(event):
                    continue

            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.MOUSEWHEEL:
                zoom_level = max(0.2, min(zoom_level + event.y * 0.05, 2.0))
                for c in player_field + opp_field:
                    c.update_visuals(zoom_level)
                reposition_all_field_cards(
                    player_field + opp_field, zoom_level, (cam_x, cam_y))

            elif event.type == pygame.KEYDOWN:
                # ── LP editor ─────────────────────────────────────────────
                if lp_edit_target and lp_edit_target != "__commit__":
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        try:
                            val = int(lp_input_buffer) if lp_input_buffer else 0
                            if lp_edit_target == "player":
                                player_lp[0] = max(0, val)
                            else:
                                opp_lp[0] = max(0, val)
                        except ValueError:
                            pass
                        lp_edit_target  = None
                        lp_input_buffer = ""
                    elif event.key == pygame.K_ESCAPE:
                        lp_edit_target  = None
                        lp_input_buffer = ""
                        clicked_card = clicked_owner = None
                    elif event.key == pygame.K_BACKSPACE:
                        lp_input_buffer = lp_input_buffer[:-1]
                    elif event.unicode.isdigit():
                        lp_input_buffer += event.unicode

                elif event.key == pygame.K_SPACE:
                    # Advance phase: Main → Battle → End.
                    # See advance_phase() for the full rule. Click on the
                    # Next Phase button does the same thing via the same
                    # function so behaviour can't drift between the two.
                    game_phase = advance_phase(game_phase, active_player)

                elif event.key == pygame.K_ESCAPE:
                    # Close quick-effect panel first; don't propagate further
                    if qe_is_open():
                        qe_close()
                    # Cancel tribute summon or deselect
                    if tribute.pending_card is not None:
                        active_hand = player_hand if tribute.pending_owner == "player" \
                                      else opp_hand
                        tribute.cancel(active_hand)
                    # Snap back any field card being nudged
                    if field_drag_candidate is not None:
                        c = field_drag_candidate
                        if field_drag_saved_world is not None:
                            c.world_x = field_drag_saved_world[0]
                            c.world_y = field_drag_saved_world[1]
                        c.zone_name   = field_drag_saved_zone
                        c.is_dragging = False
                        reposition_field_card(c, zoom_level, (cam_x, cam_y))
                        field_drag_candidate = field_drag_candidate_owner = None
                        field_drag_start_pos = field_drag_saved_zone = None
                        field_drag_saved_world = None
                    # If we have a selected hand card mid-tribute, return it
                    if drag_candidate is not None:
                        active_hand_obj.add_card(drag_candidate)
                        drag_candidate = drag_candidate_owner = drag_start_pos = None
                    clicked_card = clicked_owner = None

                elif event.key == pygame.K_TAB:
                    # End turn
                    if tribute.pending_card is not None:
                        active_hand = player_hand if tribute.pending_owner == "player" \
                                      else opp_hand
                        tribute.cancel(active_hand)
                    # Cancel any field card being nudged
                    if field_drag_candidate is not None:
                        fdc = field_drag_candidate
                        if field_drag_saved_world:
                            fdc.world_x = field_drag_saved_world[0]
                            fdc.world_y = field_drag_saved_world[1]
                        fdc.zone_name = field_drag_saved_zone
                        fdc.is_dragging = False
                        field_drag_candidate = field_drag_candidate_owner = None
                        field_drag_start_pos = field_drag_saved_zone = None
                        field_drag_saved_world = None

                    active_player = ("opponent" if active_player == "player"
                                     else "player")
                    if active_player == "player":
                        turn_number += 1

                    # Reset per-turn flags
                    game_phase             = "Draw"
                    has_drawn_this_turn    = False
                    has_summoned_this_turn = False

                    if active_player == "player":
                        active_hand_obj   = player_hand
                        inactive_hand_obj = opp_hand
                    else:
                        active_hand_obj   = opp_hand
                        inactive_hand_obj = player_hand

                    active_hand_obj.visible   = True
                    inactive_hand_obj.visible = False

                    for c in player_hand.cards + opp_hand.cards:
                        for attr in ("lerp_x", "lerp_y", "target_x", "target_y",
                                     "target_draw_x", "target_draw_y"):
                            try:
                                delattr(c, attr)
                            except AttributeError:
                                pass
                    player_hand._reposition()
                    opp_hand._reposition()

                    new_side = player_field if active_player == "player" else opp_field
                    for c in new_side:
                        c.summoning_sickness = False
                        c.attack_used        = False

                    clicked_card = clicked_owner = None
                    print(f"[Turn {turn_number}] {active_player.upper()} — Draw Phase")

                elif event.key == pygame.K_F5:
                    state = build_game_state(
                        player_hand, player_field, player_gy,
                        opp_hand,    opp_field,    opp_gy,
                        len(player_deck), len(opp_deck),
                        player_lp[0], opp_lp[0],
                        turn_number, active_player,
                        game_phase, has_drawn_this_turn,
                        has_summoned_this_turn,
                    )
                    export_game_state(state)
                    export_flash = 120
                    try:
                        import pyperclip
                        pyperclip.copy(json.dumps(state, indent=2))
                    except Exception:
                        pass

                elif event.key == pygame.K_DELETE:
                    # Delete selected / dragged card → GY
                    target_del = selected_card or clicked_card
                    owner_del  = selected_owner or clicked_owner
                    if target_del:
                        player_hand.remove_card(target_del)
                        opp_hand.remove_card(target_del)
                        safe_remove(player_field, target_del)
                        safe_remove(opp_field,    target_del)
                        if owner_del == "player":
                            player_gy.add_card(target_del)
                        else:
                            opp_gy.add_card(target_del)
                        name = (getattr(target_del, "meta", {}) or {}).get("name", "Card")
                        print(f"[Graveyard] Sent {name} to the GY.")
                        selected_card = selected_owner = None
                        clicked_card  = clicked_owner  = None

            # ── Mouse button down ──────────────────────────────────────────
            elif event.type == pygame.MOUSEBUTTONDOWN:

                if event.button == 1:
                    # 0a. Quick-effect panel — row click or dismiss
                    if qe_is_open():
                        hit = qe_panel_hit_test(event.pos)
                        if hit:
                            qe_close()
                            gs_qe_click = build_game_state(
                                player_hand, player_field, player_gy,
                                opp_hand, opp_field, opp_gy,
                                len(player_deck), len(opp_deck),
                                player_lp[0], opp_lp[0],
                                turn_number, active_player,
                                game_phase, has_drawn_this_turn,
                                has_summoned_this_turn,
                            )
                            qe_ctx = {
                                "card":             hit.card,
                                "hook":             hit.hook,
                                "game_state":       gs_qe_click,
                                "hand":             player_hand.cards,
                                "graveyard":        player_gy.cards,
                                "activate_kuriboh": True,
                                "damage":           pending_battle_damage,
                                "damage_target":    "player",
                            }
                            result = submit_action("quick_effect", qe_ctx)
                            apply_result(result, game_objects)
                            for msg in result.get("log", []):
                                print(f"[QuickEffect] {msg}")
                            if result.get("ok"):
                                ann_s = game_objects["ann_state"]
                                arm_announcement(result, ann_s)
                                game_objects["ann_state"] = ann_s
                                # Arm Kuriboh-style negation for the NEXT
                                # battle damage event targeting the player,
                                # regardless of when the button was clicked
                                # relative to attack declaration.
                                qe_card_name = (getattr(hit.card, "meta", {}) or {}).get("name", "")
                                if qe_card_name == "Kuriboh":
                                    game_objects["battle_damage_negation_pending"] = True
                                    print("[QuickEffect] Next battle damage to "
                                          "player will be negated.")
                            else:
                                print(f"[Blocked] {result.get('error')}")
                        else:
                            # Clicked outside panel rows → dismiss
                            qe_close()
                        continue

                    # 0b. Quick-effect HUD button → open panel
                    if qe_panel_btn_hit_test(event.pos, bool(quick_effs)):
                        qe_open(quick_effs)
                        continue

                    # 0c. Per-card ⚡ buttons (legacy fallback)
                    qe_hit = quick_effect_btn_hit_test(event.pos, quick_effs)
                    if qe_hit:
                        gs_qe_click = build_game_state(
                            player_hand, player_field, player_gy,
                            opp_hand, opp_field, opp_gy,
                            len(player_deck), len(opp_deck),
                            player_lp[0], opp_lp[0],
                            turn_number, active_player,
                            game_phase, has_drawn_this_turn,
                            has_summoned_this_turn,
                        )
                        qe_ctx = {
                            "card":             qe_hit.card,
                            "hook":             qe_hit.hook,
                            "game_state":       gs_qe_click,
                            "hand":             player_hand.cards,
                            "graveyard":        player_gy.cards,
                            # card-specific activation flags
                            "activate_kuriboh": True,
                            "damage":           pending_battle_damage,
                            "damage_target":    "player",
                        }
                        result = submit_action("quick_effect", qe_ctx)
                        apply_result(result, game_objects)
                        for msg in result.get("log", []):
                            print(f"[QuickEffect] {msg}")
                        if result.get("ok"):
                            ann_s = game_objects["ann_state"]
                            arm_announcement(result, ann_s)
                            game_objects["ann_state"] = ann_s
                            # See panel-path comment above. Mirror it here for
                            # players using the legacy per-card ⚡ button.
                            qe_card_name = (getattr(qe_hit.card, "meta", {}) or {}).get("name", "")
                            if qe_card_name == "Kuriboh":
                                game_objects["battle_damage_negation_pending"] = True
                                print("[QuickEffect] Next battle damage to "
                                      "player will be negated.")
                        else:
                            print(f"[Blocked] {result.get('error')}")
                        continue

                    # 0b. Next Phase button (HUD overlay) — checked before LP /
                    # deck / card hit tests so it isn't swallowed by them.
                    if phase_btn_hit_test(event.pos, game_phase):
                        game_phase = advance_phase(game_phase, active_player)
                        continue

                    # 1. LP box
                    lp_hit = lp_hit_test(event.pos, player_lp[0], opp_lp[0])
                    if lp_hit:
                        lp_edit_target  = lp_hit
                        lp_input_buffer = ""

                    # 2. Deck zones — draw via game engine
                    elif p_deck_z and p_deck_z.collidepoint(event.pos):
                        if opening_draws_remaining["player"] > 0:
                            # Opening hand — draw freely up to the limit,
                            # regardless of current game_phase.
                            if player_deck:
                                card_data  = player_deck.pop()
                                drawn_card = load_card(card_data, PLAYER_DECK_PATH, back_img)
                                player_hand.add_card(drawn_card)
                                opening_draws_remaining["player"] -= 1
                                left = opening_draws_remaining["player"]
                                print(f"[Opening] Player draws ({left} remaining).")
                                # Only advance phase once BOTH sides are done
                                if left == 0 and opening_draws_remaining["opponent"] == 0:
                                    game_phase = "Draw"
                                    print(f"[Setup] Opening hands complete — Turn 1 Draw Phase.")
                        else:
                            gs = build_game_state(
                                player_hand, player_field, player_gy,
                                opp_hand, opp_field, opp_gy,
                                len(player_deck), len(opp_deck),
                                player_lp[0], opp_lp[0],
                                turn_number, active_player,
                                game_phase, has_drawn_this_turn,
                                has_summoned_this_turn,
                            )
                            result = submit_action("draw", {
                                "active_player": active_player,
                                "game_state":    gs,
                            })
                            if result["ok"]:
                                apply_result(result, game_objects)
                                has_drawn_this_turn = game_objects["has_drawn_this_turn"]
                                for msg in result["log"]:
                                    print(f"[Draw] {msg}")
                                # Automatically advance to Standby Phase after drawing
                                if game_phase == "Draw":
                                    game_phase = "Main"
                                    print(f"[Phase] {active_player.upper()} — Main Phase")
                            else:
                                print(f"[Blocked] {result['error']}")

                    elif o_deck_z and o_deck_z.collidepoint(event.pos):
                        if opening_draws_remaining["opponent"] > 0:
                            # Opening hand for opponent — same logic, independent
                            # of game_phase so they get their full hand even if
                            # the player finished first and phase already moved on.
                            if opp_deck:
                                card_data  = opp_deck.pop()
                                drawn_card = load_card(card_data, OPPONENT_DECK_PATH, back_img)
                                opp_hand.add_card(drawn_card)
                                opening_draws_remaining["opponent"] -= 1
                                left = opening_draws_remaining["opponent"]
                                print(f"[Opening] Opponent draws ({left} remaining).")
                                if left == 0 and opening_draws_remaining["player"] == 0:
                                    game_phase = "Draw"
                                    print(f"[Setup] Opening hands complete — Turn 1 Draw Phase.")
                        else:
                            gs = build_game_state(
                                player_hand, player_field, player_gy,
                                opp_hand, opp_field, opp_gy,
                                len(player_deck), len(opp_deck),
                                player_lp[0], opp_lp[0],
                                turn_number, active_player,
                                game_phase, has_drawn_this_turn,
                                has_summoned_this_turn,
                            )
                            result = submit_action("draw", {
                                "active_player": active_player,
                                "game_state":    gs,
                            })
                            if result["ok"]:
                                apply_result(result, game_objects)
                                has_drawn_this_turn = game_objects["has_drawn_this_turn"]
                                for msg in result["log"]:
                                    print(f"[Draw] {msg}")
                                if game_phase == "Draw":
                                    game_phase = "Main"
                                    print(f"[Phase] {active_player.upper()} — Main Phase")
                            else:
                                print(f"[Blocked] {result['error']}")

                    else:
                        # 3. Hand card — LMB = DRAG to field, or double-click to activate Spell/Trap
                        c = active_hand_obj.check_click(event.pos)
                        if c:
                            if tribute.pending_card is not None and c is not tribute.pending_card:
                                active_hand = player_hand if tribute.pending_owner == "player" \
                                              else opp_hand
                                tribute.cancel(active_hand)

                            now = pygame.time.get_ticks()
                            is_dbl = (c is _dbl_last_card
                                      and (now - _dbl_last_time) < DBL_CLICK_MS)
                            _dbl_last_card = c
                            _dbl_last_time = now

                            if is_dbl and ("Spell" in c.card_type or "Trap" in c.card_type):
                                _dbl_last_card = None
                                c.owner = active_player
                                gs = build_game_state(
                                    player_hand, player_field, player_gy,
                                    opp_hand, opp_field, opp_gy,
                                    len(player_deck), len(opp_deck),
                                    player_lp[0], opp_lp[0],
                                    turn_number, active_player,
                                    game_phase, has_drawn_this_turn,
                                    has_summoned_this_turn,
                                )
                                result = submit_action("activate", {
                                    "card":          c,
                                    "owner":         active_player,
                                    "active_player": active_player,
                                    "targets":       [],
                                    "game_state":    gs,
                                    "player_field":  player_field,
                                    "opp_field":     opp_field,
                                })
                                apply_result(result, game_objects)
                                for msg in result.get("log", []):
                                    print(f"[Activate] {msg}")
                                if result.get("ok"):
                                    ann_s = game_objects["ann_state"]
                                    arm_announcement(result, ann_s)
                                    game_objects["ann_state"] = ann_s
                                    announcement       = ann_s[0]
                                    announcement_timer = ann_s[1]
                                    active_hand_obj.remove_card(c)
                                    meta_c = getattr(c, "meta", {}) or {}
                                    spell_type = meta_c.get("type", c.card_type)
                                    if "Normal" in str(spell_type) and "Spell" in str(spell_type):
                                        gy = player_gy if active_player == "player" else opp_gy
                                        gy.add_card(c)
                                    else:
                                        prefix = "P_S/T" if active_player == "player" else "O_S/T"
                                        for i in range(1, 6):
                                            zn = f"{prefix}{i}"
                                            dest_f = player_field if active_player == "player" else opp_field
                                            if zn in zones and not any(
                                                    getattr(fc, "zone_name", None) == zn
                                                    for fc in dest_f):
                                                z_rect = zones[zn]
                                                c.world_x = (z_rect.centerx - cx) / zoom_level - cam_x
                                                c.world_y = (z_rect.centery - cy) / zoom_level - cam_y
                                                c.zone_name = zn
                                                break
                                        c.in_hand = False
                                        c.is_dragging = False
                                        c.angle = 0
                                        c.update_visuals(zoom_level)
                                        if c not in dest_f:
                                            dest_f.append(c)
                                        reposition_field_card(c, zoom_level, (cam_x, cam_y))
                                else:
                                    print(f"[Blocked] {result.get('error')}")
                                drag_candidate = drag_candidate_owner = drag_start_pos = None
                            else:
                                drag_candidate       = c
                                drag_candidate_owner = active_player
                                drag_start_pos       = event.pos

                        else:
                            # 4. Field card — LMB = begin drag candidate
                            # (card is not lifted until DRAG_THRESHOLD is crossed)
                            hit       = None
                            hit_owner = None
                            for lst, owner in ((player_field, "player"),
                                               (opp_field,    "opponent")):
                                h = next((fc for fc in reversed(lst)
                                          if fc.rect.collidepoint(event.pos)), None)
                                if h:
                                    hit       = h
                                    hit_owner = owner
                                    break

                            if hit:
                                # Store as candidate; actual lift happens in MOUSEMOTION
                                field_drag_candidate       = hit
                                field_drag_candidate_owner = hit_owner
                                field_drag_start_pos       = event.pos
                                field_drag_saved_zone      = getattr(hit, "zone_name", None)
                                field_drag_saved_world     = (getattr(hit, "world_x", 0),
                                                              getattr(hit, "world_y", 0))
                                clicked_card  = hit
                                clicked_owner = hit_owner

                elif event.button == 2:
                    is_panning = True

                elif event.button == 3:
                    # RMB on GY zone → open the graveyard viewer overlay.
                    # This takes priority over everything else so GY zones
                    # act as pure viewer triggers and never leak through to
                    # hand/field click handlers behind them.
                    if (p_gy_z and p_gy_z.collidepoint(event.pos)) or \
                       (o_gy_z and o_gy_z.collidepoint(event.pos)):
                        qe_close()
                        gy_viewer.open()
                        continue

                    # RMB on hand card → select / interact
                    c = active_hand_obj.check_click(event.pos)
                    if c:
                        if tribute.pending_card is not None and c is not tribute.pending_card:
                            active_hand = player_hand if tribute.pending_owner == "player" \
                                          else opp_hand
                            tribute.cancel(active_hand)
                        clicked_card  = c
                        clicked_owner = active_player
                        print(f"[Select] {(getattr(c, 'meta', {}) or {}).get('name', '?')} "
                              f"selected from hand.")

                    else:
                        # RMB on field card → interact or cycle ATK/DEF/SET
                        hit       = None
                        hit_owner = None
                        for lst, owner in ((player_field, "player"),
                                           (opp_field,    "opponent")):
                            h = next((fc for fc in reversed(lst)
                                      if fc.rect.collidepoint(event.pos)), None)
                            if h:
                                hit       = h
                                hit_owner = owner
                                break

                        if hit:
                            # ── Interaction: hand card → field card ───
                            if (clicked_card is not None
                                    and clicked_card.in_hand):
                                keep_selected = resolve_hand_action(
                                    clicked_card, clicked_owner,
                                    hit,          hit_owner,
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
                                    has_summoned_this_turn,
                                )
                                if not keep_selected:
                                    # Mid-tribute: keep clicked_card = pending summon card
                                    clicked_card  = tribute.pending_card
                                    clicked_owner = tribute.pending_owner
                                else:
                                    clicked_card = clicked_owner = None

                            # ── Interaction: field card → field card ──
                            elif (clicked_card is not None
                                    and clicked_card is not hit):
                                resolve_interaction(
                                    clicked_card, clicked_owner,
                                    hit,          hit_owner,
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
                                    has_summoned_this_turn,
                                )
                                if tribute.pending_card is None:
                                    clicked_card = clicked_owner = None
                                else:
                                    clicked_card  = tribute.pending_card
                                    clicked_owner = tribute.pending_owner

                            elif tribute.pending_card is None:
                                # No selection active → cycle ATK / DEF / SET
                                hit.toggle_position()

                        else:
                            # Clicked empty space — route through possible actions.
                            direct_attack_fired = False
                            set_fired           = False
                            flip_fired          = False

                            # ── 1. Set from hand ─────────────────────────
                            # Selected hand card + click on own side → Set face-down.
                            if (clicked_card is not None
                                    and clicked_card.in_hand
                                    and clicked_owner == active_player
                                    and tribute.pending_card is None
                                    and is_own_side_click(event.pos, active_player, zones)):
                                meta_s = getattr(clicked_card, "meta", {}) or {}
                                type_s = str(meta_s.get("type", clicked_card.card_type))
                                # Only Set Spells / Traps / low-level Monsters here.
                                settable = ("Spell" in type_s or "Trap" in type_s
                                            or "Monster" in type_s)
                                if settable:
                                    set_fired = attempt_set_card(
                                        clicked_card, clicked_owner, active_player,
                                        player_field, opp_field,
                                        player_hand,  opp_hand,
                                        player_lp,    opp_lp,
                                        player_gy,    opp_gy,
                                        game_objects,
                                        player_deck,  opp_deck,
                                        turn_number,
                                        game_phase,
                                        has_drawn_this_turn,
                                        has_summoned_this_turn,
                                        zones=zones,
                                        zoom_level=zoom_level,
                                        cam_offset=(cam_x, cam_y),
                                    )
                                    if set_fired:
                                        # Refresh has_summoned_this_turn from game_objects
                                        # in case attempt_set_card flipped it.
                                        has_summoned_this_turn = game_objects.get(
                                            "has_summoned_this_turn", has_summoned_this_turn)

                            # ── 2. Flip-activate from field ──────────────
                            # Selected face-down field Spell/Trap + click on
                            # empty space → flip face-up & resolve.
                            elif (clicked_card is not None
                                    and not clicked_card.in_hand
                                    and clicked_owner == active_player
                                    and getattr(clicked_card, "mode", None) == "SET"
                                    and tribute.pending_card is None):
                                meta_c = getattr(clicked_card, "meta", {}) or {}
                                type_c = str(meta_c.get("type", clicked_card.card_type))
                                if "Spell" in type_c or "Trap" in type_c:
                                    flip_fired = attempt_flip_activate(
                                        clicked_card, clicked_owner, active_player,
                                        player_field, opp_field,
                                        player_hand,  opp_hand,
                                        player_lp,    opp_lp,
                                        player_gy,    opp_gy,
                                        game_objects,
                                        player_deck,  opp_deck,
                                        turn_number,
                                        game_phase,
                                        has_drawn_this_turn,
                                        has_summoned_this_turn,
                                    )

                            # ── 3. Direct attack ─────────────────────────
                            # (Unchanged — friendly monster + RMB on opp side.)
                            elif (clicked_card is not None
                                    and not clicked_card.in_hand
                                    and clicked_owner == active_player
                                    and "Monster" in getattr(clicked_card, "card_type", "")
                                    and tribute.pending_card is None):
                                click_y = event.pos[1]
                                screen_mid = SCREEN_SIZE[1] // 2
                                clicked_opp_side = (
                                    (active_player == "player" and click_y < screen_mid) or
                                    (active_player == "opponent" and click_y > screen_mid)
                                )
                                clicked_zone_name = next(
                                    (n for n, r in zones.items()
                                     if r.collidepoint(event.pos)), None)
                                is_opp_zone = (
                                    clicked_zone_name is not None and
                                    clicked_zone_name.startswith(
                                        "O_" if active_player == "player" else "P_")
                                )
                                if clicked_opp_side or is_opp_zone:
                                    direct_attack_fired = attempt_direct_attack(
                                        clicked_card, clicked_owner,
                                        player_field, opp_field,
                                        player_gy, opp_gy,
                                        player_lp, opp_lp,
                                        game_objects,
                                        turn_number, active_player, game_phase,
                                    )

                            if not (direct_attack_fired or set_fired or flip_fired):
                                if tribute.pending_card is not None:
                                    active_hand = player_hand \
                                                  if tribute.pending_owner == "player" \
                                                  else opp_hand
                                    tribute.cancel(active_hand)
                                # Return any selected hand card
                                if clicked_card is not None and clicked_card.in_hand:
                                    # Card was selected from hand but never acted on — keep it
                                    pass
                                clicked_card = clicked_owner = None
                            else:
                                # Any of the three actions consumed the selection.
                                clicked_card = clicked_owner = None

            # ── Mouse motion ───────────────────────────────────────────────
            elif event.type == pygame.MOUSEMOTION:
                if selected_card:
                    # Dragging a field card
                    selected_card.rect.center = mouse_pos

                elif field_drag_candidate is not None:
                    # Promote field card to full drag once threshold crossed
                    # (3x the hand threshold so placed cards resist small nudges)
                    fdx = mouse_pos[0] - field_drag_start_pos[0]
                    fdy = mouse_pos[1] - field_drag_start_pos[1]
                    if (fdx * fdx + fdy * fdy) >= (DRAG_THRESHOLD * 3) ** 2:
                        c = field_drag_candidate
                        (player_field if field_drag_candidate_owner == "player"
                         else opp_field).remove(c)
                        c.is_dragging = True
                        c.zone_name   = None
                        c._dragged_from_field = True
                        c._field_saved_world  = field_drag_saved_world
                        c._field_saved_zone   = field_drag_saved_zone
                        selected_card  = c
                        selected_owner = field_drag_candidate_owner
                        c.rect.center  = mouse_pos
                        field_drag_candidate = field_drag_candidate_owner = None
                        field_drag_start_pos = field_drag_saved_zone = None
                        field_drag_saved_world = None

                elif drag_candidate is not None:
                    # Check if we've moved far enough to start a drag
                    dx = mouse_pos[0] - drag_start_pos[0]
                    dy = mouse_pos[1] - drag_start_pos[1]
                    if (dx * dx + dy * dy) >= DRAG_THRESHOLD ** 2:
                        # Promote drag_candidate to a full drag
                        c = drag_candidate
                        # If it was selected as clicked_card, clear that
                        if clicked_card is c:
                            clicked_card = clicked_owner = None

                        active_hand_obj.remove_card(c)
                        c.is_dragging = True
                        c._dragged_from_field = False
                        selected_card  = c
                        selected_owner = drag_candidate_owner
                        c.rect.center  = mouse_pos
                        drag_candidate = drag_candidate_owner = drag_start_pos = None

                elif is_panning:
                    rx, ry = event.rel
                    cam_x += rx / zoom_level
                    cam_y += ry / zoom_level
                    reposition_all_field_cards(
                        player_field + opp_field, zoom_level, (cam_x, cam_y))

            # ── Mouse button up ────────────────────────────────────────────
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    is_panning = False

                if event.button == 3:
                    # RMB up — select/interact lives on RMB, nothing to do except
                    # clear any drag_candidate if one somehow got set.
                    if drag_candidate is not None:
                        drag_candidate = drag_candidate_owner = drag_start_pos = None

                if event.button == 1:
                    # ── LMB up: field card nudge — snap back without engine action
                    if field_drag_candidate is not None:
                        c = field_drag_candidate
                        if field_drag_saved_world is not None:
                            c.world_x = field_drag_saved_world[0]
                            c.world_y = field_drag_saved_world[1]
                        c.zone_name   = field_drag_saved_zone
                        c.is_dragging = False
                        reposition_field_card(c, zoom_level, (cam_x, cam_y))
                        field_drag_candidate = field_drag_candidate_owner = None
                        field_drag_start_pos = field_drag_saved_zone = None
                        field_drag_saved_world = None
                        # keep clicked_card so RMB interactions still work

                    # ── LMB up: drop a dragged hand card ──────────────────
                    elif drag_candidate is not None:
                        # Released before crossing drag threshold → discard candidate
                        drag_candidate = drag_candidate_owner = drag_start_pos = None

                    # ── Drop a dragged card ────────────────────────────────
                    elif selected_card:
                        drop_pos = event.pos
                        drop_y   = drop_pos[1]
                        from_field = getattr(selected_card, "_dragged_from_field", False)

                        # Field cards: only go to hand if dragged into
                        # hand strip deliberately. Otherwise always snap
                        # back to saved zone without any summon logic.
                        if (from_field
                                and selected_owner == "player"
                                and drop_y > PLAYER_HAND_Y_THRESHOLD):
                            selected_card._dragged_from_field = False
                            selected_card.zone_name = None
                            player_hand.add_card(selected_card, drop_x=drop_pos[0])
                            selected_card = selected_owner = None

                        elif (from_field
                                and selected_owner == "opponent"
                                and drop_y < OPPONENT_HAND_Y_THRESHOLD):
                            selected_card._dragged_from_field = False
                            selected_card.zone_name = None
                            opp_hand.add_card(selected_card, drop_x=drop_pos[0])
                            selected_card = selected_owner = None

                        elif from_field:
                            # Dropped on field - snap back to saved position.
                            # No summon logic, no phase change.
                            c = selected_card
                            saved = getattr(c, "_field_saved_world", None)
                            saved_zone = getattr(c, "_field_saved_zone", None)
                            if saved:
                                c.world_x = saved[0]
                                c.world_y = saved[1]
                            c.zone_name   = saved_zone
                            c.is_dragging = False
                            c.angle       = 0
                            c._dragged_from_field = False
                            dest = (player_field if selected_owner == "player"
                                    else opp_field)
                            if c not in dest:
                                dest.append(c)
                            reposition_field_card(c, zoom_level, (cam_x, cam_y))
                            selected_card = selected_owner = None

                        elif (selected_owner == "player"
                                and drop_y > PLAYER_HAND_Y_THRESHOLD):
                            selected_card.zone_name = None
                            player_hand.add_card(selected_card, drop_x=drop_pos[0])

                        elif (selected_owner == "opponent"
                                and drop_y < OPPONENT_HAND_Y_THRESHOLD):
                            selected_card.zone_name = None
                            opp_hand.add_card(selected_card, drop_x=drop_pos[0])

                        else:
                            dest      = player_field if selected_owner == "player" \
                                        else opp_field
                            my_hand   = player_hand  if selected_owner == "player" \
                                        else opp_hand
                            summon_ok = True

                            if rules.is_monster(selected_card):
                                selected_card.owner = selected_owner

                                # ── Drop-on-monster gesture ─────────────────
                                # Detect whether the card was dropped on top of
                                # an own field monster. If so, this is a drag
                                # tribute attempt:
                                #   • Level 5-6 → auto-tribute that monster.
                                #   • Level 7+  → block with a hint to use the
                                #     right-click multi-tribute selector.
                                #   • Level 1-4 → block (zones can't share).
                                # Fusions are never tributed this way; they go
                                # through can_fusion_summon below.
                                drop_target = None
                                if not rules.is_fusion(selected_card):
                                    for fc in dest:
                                        if (fc is not selected_card
                                                and rules.is_monster(fc)
                                                and getattr(fc, "rect", None) is not None
                                                and fc.rect.collidepoint(drop_pos)):
                                            drop_target = fc
                                            break

                                drag_tributes = []
                                if drop_target is not None:
                                    needed = rules.tributes_required(selected_card)
                                    if needed == 0:
                                        print("[Summon blocked] Cannot drop on an "
                                              "occupied zone — pick an empty zone.")
                                        selected_card.is_dragging = False
                                        selected_card.in_hand     = True
                                        selected_card.angle       = 0
                                        my_hand.add_card(selected_card)
                                        selected_card = selected_owner = None
                                        continue
                                    elif needed == 1:
                                        drag_tributes = [drop_target]
                                        print(f"[Tribute] Drag-tributing "
                                              f"{(getattr(drop_target, 'meta', {}) or {}).get('name', '?')}.")
                                    else:  # needed >= 2
                                        print(f"[Tribute] Level {(getattr(selected_card, 'meta', {}) or {}).get('level', '?')} "
                                              f"requires {needed} tributes — right-click the card "
                                              f"in hand to start multi-tribute selection.")
                                        selected_card.is_dragging = False
                                        selected_card.in_hand     = True
                                        selected_card.angle       = 0
                                        my_hand.add_card(selected_card)
                                        selected_card = selected_owner = None
                                        continue

                                if rules.is_fusion(selected_card):
                                    ok, reason = rules.can_fusion_summon(
                                        selected_card, dest)
                                    if not ok:
                                        print(f"[Summon blocked] {reason}")
                                        selected_card.is_dragging = False
                                        selected_card.in_hand     = True
                                        selected_card.angle       = 0
                                        my_hand.add_card(selected_card)
                                        selected_card = selected_owner = None
                                        continue
                                    summon_ok = True
                                else:
                                    # Build a full gs for the pre-flight check
                                    # so the phase rule fires here too — without
                                    # this, the engine-side check would still
                                    # block the summon, but the card would
                                    # visually snap to the field for one frame
                                    # before being yanked back to hand. Building
                                    # gs once and reusing for both checks is
                                    # cheaper than two separate constructions.
                                    pre_gs = build_game_state(
                                        player_hand, player_field, player_gy,
                                        opp_hand, opp_field, opp_gy,
                                        len(player_deck), len(opp_deck),
                                        player_lp[0], opp_lp[0],
                                        turn_number, active_player,
                                        game_phase, has_drawn_this_turn,
                                        has_summoned_this_turn,
                                    )
                                    ok, reason = rules.can_normal_summon(
                                        selected_card, dest, drag_tributes, pre_gs)
                                    if not ok:
                                        print(f"[Summon blocked] {reason}")
                                        selected_card.is_dragging = False
                                        selected_card.in_hand     = True
                                        selected_card.angle       = 0
                                        my_hand.add_card(selected_card)
                                        selected_card = selected_owner = None
                                        continue

                            snapped, snap_rect = try_snap(
                                selected_card, drop_pos, zones,
                                zoom_level, (cam_x, cam_y), selected_owner)
                            if not snapped:
                                selected_card.world_x   = (drop_pos[0] - cx) / zoom_level - cam_x
                                selected_card.world_y   = (drop_pos[1] - cy) / zoom_level - cam_y
                                selected_card.zone_name = None

                            selected_card.in_hand     = False
                            selected_card.angle       = 0
                            selected_card.is_dragging = False
                            selected_card.update_visuals(zoom_level)

                            if snapped:
                                selected_card.rect.center = snap_rect.center
                            reposition_field_card(
                                selected_card, zoom_level, (cam_x, cam_y))

                            if rules.is_monster(selected_card):
                                gs = build_game_state(
                                    player_hand, player_field, player_gy,
                                    opp_hand, opp_field, opp_gy,
                                    len(player_deck), len(opp_deck),
                                    player_lp[0], opp_lp[0],
                                    turn_number, active_player,
                                    game_phase, has_drawn_this_turn,
                                    has_summoned_this_turn,
                                )
                                result = submit_action("summon", {
                                    "card":           selected_card,
                                    "owner":          selected_owner,
                                    "field_monsters": dest,
                                    "tributes":       drag_tributes,
                                    "game_state":     gs,
                                })
                                apply_result(result, game_objects)
                                for msg in result.get("log", []):
                                    print(f"[Summon] {msg}")
                                if not result.get("ok"):
                                    print(f"[Summon blocked] {result['error']}")
                                    selected_card.is_dragging = False
                                    selected_card.in_hand     = True
                                    selected_card.angle       = 0
                                    my_hand.add_card(selected_card)
                                    selected_card = selected_owner = None
                                    continue
                                else:
                                    has_summoned_this_turn = True
                                # apply_result already appended to field — no dest.append needed.
                            else:
                                # ── Spell / Trap dragged to field ─────────
                                # Always fire submit_action("activate") so the
                                # card engine runs phase checks, condition
                                # checks, and effect hooks.  If activation is
                                # blocked the card returns to hand; otherwise
                                # it lands on the field (dest.append below).
                                ann_state = [announcement, announcement_timer]
                                if "Spell" in selected_card.card_type or \
                                   "Trap"  in selected_card.card_type:
                                    selected_card.owner = selected_owner
                                    gs = build_game_state(
                                        player_hand, player_field, player_gy,
                                        opp_hand, opp_field, opp_gy,
                                        len(player_deck), len(opp_deck),
                                        player_lp[0], opp_lp[0],
                                        turn_number, active_player,
                                        game_phase, has_drawn_this_turn,
                                        has_summoned_this_turn,
                                    )
                                    result = submit_action("activate", {
                                        "card":          selected_card,
                                        "owner":         selected_owner,
                                        "active_player": active_player,
                                        "targets":       [],
                                        "game_state":    gs,
                                        "player_field":  player_field,
                                        "opp_field":     opp_field,
                                    })
                                    apply_result(result, game_objects)
                                    for msg in result.get("log", []):
                                        print(f"[Activate] {msg}")
                                    if not result.get("ok"):
                                        print(f"[Blocked] {result['error']}")
                                        selected_card.is_dragging = False
                                        selected_card.in_hand     = True
                                        selected_card.angle       = 0
                                        my_hand.add_card(selected_card)
                                        selected_card = selected_owner = None
                                        continue
                                    # Arm announcement — write back to game_objects
                                    # so the draw loop picks it up this frame.
                                    ann_state = game_objects["ann_state"]
                                    arm_announcement(result, ann_state)
                                    game_objects["ann_state"] = ann_state
                                    announcement       = ann_state[0]
                                    announcement_timer = ann_state[1]
                                    # Normal Spells go straight to GY after
                                    # resolving — don't place on field.
                                    # Match by exclusion so this works for
                                    # both "Normal Spell Card" and bare
                                    # "Spell Card" metadata formats.
                                    meta_s = getattr(selected_card, "meta", {}) or {}
                                    spell_type = str(meta_s.get("type",
                                                 selected_card.card_type))
                                    is_spell      = "Spell" in spell_type
                                    is_persistent = any(kw in spell_type for kw in
                                                        ("Continuous", "Equip",
                                                         "Field", "Quick-Play",
                                                         "Trap"))
                                    if is_spell and not is_persistent:
                                        # apply_result already routed GY cards;
                                        # send the spell itself to GY too
                                        gy = player_gy if selected_owner == "player" \
                                             else opp_gy
                                        gy.add_card(selected_card)
                                        selected_card = selected_owner = None
                                        continue
                                # Continuous / Equip / Trap — stays on field
                                dest.append(selected_card)

                        selected_card = selected_owner = None

        # ── Draw: field cards ──────────────────────────────────────────────
        for c in player_field + opp_field:
            c.draw(screen)

        # ── Draw: tribute selection highlights ────────────────────────────
        if tribute.selected:
            for tribute_card in tribute.selected:
                pygame.draw.rect(screen, (255, 165, 0),
                                 tribute_card.rect.inflate(6, 6), 3)

        # ── Draw: field overlays ───────────────────────────────────────────
        draw_field_overlays(screen, zones, player_field, opp_field, mouse_pos)

        # ── Draw: selection + hover target ────────────────────────────────
        hover_target = None
        if clicked_card:
            hover_target = next(
                (c for c in reversed(player_field + opp_field)
                 if c.rect.collidepoint(mouse_pos) and c is not clicked_card),
                None
            )
        draw_selection_highlight(screen, clicked_card, hover_target)

        # Also highlight drag_candidate (hand card under cursor, not yet dragged)
        if drag_candidate and getattr(drag_candidate, "rect", None):
            pygame.draw.rect(screen, (200, 200, 80),
                             drag_candidate.rect.inflate(4, 4), 2)

        # ── Draw: graveyards ───────────────────────────────────────────────
        player_gy.draw_top_card(screen, p_gy_z)
        opp_gy.draw_top_card(screen, o_gy_z)

        # ── Draw: hands ────────────────────────────────────────────────────
        player_hand.update(mouse_pos)
        player_hand.draw(screen)
        opp_hand.update(mouse_pos)
        opp_hand.draw(screen)

        # ── Draw: quick-effect buttons (above hand, below dragged card) ──────
        gs_qe = {
            "active_player": active_player,
            "phase":         game_phase,
        }
        quick_effs = get_quick_effects(player_hand.cards, gs_qe)
        draw_quick_effect_buttons(screen, font, quick_effs, mouse_pos)

        # ── Draw: ⚡ Quick Effects HUD button ──────────────────────────────
        draw_qe_panel_button(screen, font, mouse_pos,
                             has_quick_effects=bool(quick_effs),
                             panel_open=qe_is_open())

        # ── Draw: actively dragged card (always on top) ────────────────────
        if selected_card:
            selected_card.draw(screen)

        # ── Draw: selected card info panel ────────────────────────────────
        # Build a slim game_state so continuous-effect modifiers (e.g. Dark
        # Magician Girl's +300 per Dark Magician / Magician of Black Chaos
        # in either GY) are reflected in the displayed ATK/DEF.  We only
        # populate the graveyards here because that's all DMG reads — extend
        # this dict if a future continuous effect needs more state.
        info_state = {
            "active_player": active_player,
            "player":   {"graveyard": [card_to_state(c) for c in player_gy.cards]},
            "opponent": {"graveyard": [card_to_state(c) for c in opp_gy.cards]},
        }
        draw_card_info_panel(screen, clicked_card, font, small_font, info_state)

        # ── Draw: HUD + LP editor ─────────────────────────────────────────
        if export_flash > 0:
            export_flash -= 1
        lp_edit_target, lp_input_buffer = draw_hud(
            screen, font, small_font,
            active_player, turn_number,
            player_deck, opp_deck,
            player_lp[0], opp_lp[0],
            export_flash, HINTS,
            lp_edit_target, lp_input_buffer,
            mouse_pos,
            game_phase=game_phase)

        # ── Draw: centre-screen announcement banner ────────────────────────
        if announcement and announcement_timer > 0:
            alpha = min(255, announcement_timer * 4)   # fade out last ~64 frames
            draw_announcement(screen,
                              announcement["title"],
                              announcement["body"],
                              alpha,
                              announcement["kind"])
            announcement_timer -= 1
            if announcement_timer <= 0:
                announcement = None
            # Write back so helpers see the decremented value next frame
            ann_state[0] = announcement
            ann_state[1] = announcement_timer

        # ── Draw: graveyard viewer overlay (on top of everything) ──────────
        if gy_viewer.is_open():
            gy_viewer.draw(screen, font, small_font, player_gy, opp_gy)

        # ── Draw: quick-effect panel overlay (above GY viewer) ─────────────
        if qe_is_open():
            qe_draw_panel(screen, font, small_font)

        pygame.display.flip()
        clock.tick(FPS)
