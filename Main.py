"""
Main.py — YGO Field Tracker entry point and main event loop.

Key interaction model
─────────────────────
Hand cards
  • RIGHT CLICK → select the card (gold border, info panel).  If a hand card
                  is already selected, the new click is treated as a target /
                  material click and routed through _resolve_hand_action().
  • LEFT DRAG   → pressing LMB on a hand card and moving > DRAG_THRESHOLD
                  pixels lifts the card and starts a free drag.
  • RIGHT CLICK (field) → cycle ATK / DEF / SET when no card is selected.

Field cards
  • LEFT CLICK (first)  → pick up card and begin dragging.
  • RIGHT CLICK (first) → select card (gold border + info panel).
  • RIGHT CLICK (second)→ interact with first-selected card via cardengine.

Deck zone
  • LEFT CLICK → submit_action("draw") through the game engine.  Only legal
                 during Draw Phase; once per turn.  apply_result() handles
                 physically moving the card from deck list to hand.
"""

import pygame
import json
import os
import random
import traceback
import datetime
import pyperclip

from config import (
    SCREEN_SIZE, BG_COLOR, FPS,
    SNAP_RADIUS,
    PLAYER_HAND_Y_THRESHOLD,
    OPPONENT_HAND_Y_THRESHOLD,
    PLAYER_DECK_PATH,
    OPPONENT_DECK_PATH,
    STARTING_HAND_SIZE,
    INSTANT_HAND,
)
from engine.card import Card
from engine.field import draw_field_zones
from engine.hand import Hand
from engine.graveyard import Graveyard
from ui import draw_snap_highlight, draw_field_overlays, draw_hud, lp_hit_test, \
               draw_selection_highlight, draw_card_info_panel, draw_announcement
import cardengine                                          # auto-registers all card effects
from cardengine.game import submit_action, apply_result
from cardengine import rules


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pixels the mouse must move while holding LMB on a hand card before the card
# is lifted into a drag.  Below this threshold, releasing the button registers
# as a plain "select" click.
DRAG_THRESHOLD = 6

# Turn phases in order.  We cycle through them with Tab (end-turn advances
# automatically to Draw Phase for the new active player).
PHASES = ["Draw", "Standby", "Main 1", "Battle", "Main 2", "End"]


# ---------------------------------------------------------------------------
# Snap-to-zone helper
# ---------------------------------------------------------------------------

_PLAYER_ZONES   = ({f"P_M{i}"   for i in range(1, 6)} |
                   {f"P_S/T{i}" for i in range(1, 6)} |
                   {"P_Field"})
_OPPONENT_ZONES = ({f"O_M{i}"   for i in range(1, 6)} |
                   {f"O_S/T{i}" for i in range(1, 6)} |
                   {"O_Field"})


def try_snap(card, drop_screen_pos, zones, zoom_level, cam_offset, owner):
    """
    If the drop position is within SNAP_RADIUS of an eligible zone centre,
    snaps the card to that zone and returns (True, snapped_rect).
    Returns (False, None) otherwise.
    """
    cx, cy  = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    legal   = _PLAYER_ZONES if owner == "player" else _OPPONENT_ZONES
    dx, dy  = drop_screen_pos

    best_dist = float("inf")
    best_zone = None
    best_rect = None

    for name, z_rect in zones.items():
        if name not in legal:
            continue
        dist = ((dx - z_rect.centerx) ** 2 + (dy - z_rect.centery) ** 2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_zone = name
            best_rect = z_rect

    if best_zone is None or best_dist > SNAP_RADIUS:
        return False, None

    card.world_x   = (best_rect.centerx - cx) / zoom_level - cam_offset[0]
    card.world_y   = (best_rect.centery - cy) / zoom_level - cam_offset[1]
    card.zone_name = best_zone
    return True, best_rect


# ---------------------------------------------------------------------------
# Field-card screen positioning
# ---------------------------------------------------------------------------

def reposition_field_card(card, zoom_level, cam_offset):
    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    cam_x, cam_y = cam_offset
    card.rect.centerx = int(cx + (card.world_x + cam_x) * zoom_level)
    card.rect.centery = int(cy + (card.world_y + cam_y) * zoom_level)


def reposition_all_field_cards(field_cards, zoom_level, cam_offset):
    for c in field_cards:
        reposition_field_card(c, zoom_level, cam_offset)


# ---------------------------------------------------------------------------
# Game-state serialisation
# ---------------------------------------------------------------------------

def card_to_state(card, hide_if_set=False):
    mode    = card.mode
    face_up = (mode != "SET")
    hidden  = hide_if_set and not face_up

    if "Monster" in card.card_type:
        battle_position = "DEF" if mode in ("DEF", "SET") else "ATK"
    else:
        battle_position = None

    if hidden:
        return {
            "name":            "???",
            "id":              None,
            "card_type":       "???",
            "zone":            getattr(card, "zone_name", None),
            "in_hand":         card.in_hand,
            "face_up":         False,
            "battle_position": battle_position,
            "mode":            mode,
            "desc":            None,
            "atk":             None,
            "def":             None,
        }

    meta = getattr(card, "meta", {}) or {}
    return {
        "id":              meta.get("id"),
        "name":            meta.get("name", "Unknown"),
        "type":            meta.get("type", card.card_type),
        "card_type":       card.card_type,
        "desc":            meta.get("desc", ""),
        "atk":             meta.get("atk"),
        "def":             meta.get("def"),
        "zone":            getattr(card, "zone_name", None),
        "in_hand":         card.in_hand,
        "face_up":         face_up,
        "battle_position": battle_position,
        "mode":            mode,
    }


def build_game_state(player_hand, player_field, player_gy,
                     opp_hand,    opp_field,    opp_gy,
                     p_deck_count, o_deck_count,
                     player_lp,   opp_lp,
                     turn_number, active_player,
                     game_phase="Main 1",
                     has_drawn_this_turn=False,
                     has_summoned_this_turn=False):
    return {
        "meta": {
            "turn":          turn_number,
            "active_player": active_player,
            "phase":         game_phase,
            "timestamp":     datetime.datetime.now().isoformat(timespec="seconds"),
        },
        # Top-level keys used by rules.can_draw / rules.can_normal_summon
        "phase":                  game_phase,
        "has_drawn_this_turn":    has_drawn_this_turn,
        "has_summoned_this_turn": has_summoned_this_turn,
        "player": {
            "life_points": player_lp,
            "hand":        [card_to_state(c) for c in player_hand.cards],
            "field":       [card_to_state(c) for c in player_field],
            "graveyard":   [card_to_state(c) for c in player_gy.cards],
            "deck_count":  p_deck_count,
        },
        "opponent": {
            "life_points": opp_lp,
            "hand_count":  len(opp_hand.cards),
            "hand":        [card_to_state(c) for c in opp_hand.cards],
            "field":       [card_to_state(c, hide_if_set=True) for c in opp_field],
            "graveyard":   [card_to_state(c) for c in opp_gy.cards],
            "deck_count":  o_deck_count,
        },
    }


def export_game_state(state, filepath="game_state.json"):
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)
    print(f"[State exported → {filepath}]")


# ---------------------------------------------------------------------------
# Card loading
# ---------------------------------------------------------------------------

def load_card(card_data, folder, back_img):
    raw = (card_data.get("image_path") or
           card_data.get("image") or
           card_data.get("file_name"))
    if not raw and "id" in card_data:
        raw = f"{card_data['id']}.jpg"

    path = os.path.join(folder, str(raw)) if raw else ""
    if raw and os.path.exists(path):
        front = pygame.image.load(path).convert_alpha()
    else:
        front = pygame.Surface((400, 580))
        front.fill((200, 50, 50))

    card           = Card(front, back_img, card_data.get("type", "Monster"))
    card.meta      = card_data
    card.zone_name = None
    return card


# ---------------------------------------------------------------------------
# Tribute-summon globals
# ---------------------------------------------------------------------------

pending_summon_card  = None
pending_summon_owner = None
selected_tributes    = []


def _cancel_pending_tribute(hand_obj):
    global pending_summon_card, pending_summon_owner, selected_tributes
    if pending_summon_card is not None:
        name = (getattr(pending_summon_card, "meta", {}) or {}).get("name", "?")
        if pending_summon_card not in getattr(hand_obj, "cards", []):
            pending_summon_card.in_hand = True
            hand_obj.add_card(pending_summon_card)
        print(f"[Tribute] Summon cancelled — {name} returned to hand.")
    pending_summon_card  = None
    pending_summon_owner = None
    selected_tributes    = []


# ---------------------------------------------------------------------------
# Hand-card action resolver
# ---------------------------------------------------------------------------

def _resolve_hand_action(
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
    """
    Called when a hand card (hand_card) is clicked while already selected,
    and then the player clicks a target card (target_card).

    Decision tree
    ─────────────
    1. Fusion Monster in hand + own field monster clicked
       → start / continue collecting fusion materials, then summon.
    2. High-level monster in hand + own field monster clicked
       → start tribute selection.
    3. Spell / Trap in hand + any card clicked
       → activate targeting that card.
    4. Low-level monster in hand + own field monster clicked
       → normal summon (no tribute needed, direct placement).
    5. Anything else → print info message.
    """
    global pending_summon_card, pending_summon_owner, selected_tributes

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
    if (pending_summon_card is not None
            and hand_card is pending_summon_card
            and hand_owner == pending_summon_owner
            and target_owner == hand_owner
            and "Monster" in str(type_t)
            and target_on_field):

        if target_card not in selected_tributes:
            selected_tributes.append(target_card)
            level  = meta_h.get("level", 0)
            needed = rules.tributes_required(hand_card)
            have   = len(selected_tributes)
            print(f"[Tribute] Selected {name_t} as tribute "
                  f"({have}/{needed} for Lv{level} {name_h}).")
        else:
            print(f"[Tribute] {name_t} is already selected.")
            return False  # keep selection active

        needed = rules.tributes_required(pending_summon_card)
        if len(selected_tributes) >= needed:
            _attempt_tribute_summon(
                pending_summon_card, pending_summon_owner,
                list(selected_tributes),
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
        hand_card.owner  = hand_owner
        target_card.owner = target_owner
        result = submit_action("activate", {
            "card":       hand_card,
            "owner":      hand_owner,
            "targets":    [target_card],
            "game_state": gs,
        })
        apply_result(result, game_objects)
        for msg in result.get("log", []):
            print(f"[Activate] {msg}")
        if not result.get("ok"):
            print(f"[Blocked] {result.get('error')}")
            # RMB-selected — still in hand, no add_card needed
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
                # Still in hand — no add_card needed
            else:
                game_objects["has_summoned_this_turn"] = True
            return True

        # Needs tributes — begin accumulation
        level = meta_h.get("level", "?")
        pending_summon_card  = hand_card
        pending_summon_owner = hand_owner
        selected_tributes    = [target_card]
        print(f"[Tribute] Lv{level} {name_h} needs {needed} tribute(s). "
              f"Selected {name_t} (1/{needed}). "
              f"Click another own field monster to continue, or Esc to cancel.")

        if len(selected_tributes) >= needed:
            _attempt_tribute_summon(
                pending_summon_card, pending_summon_owner,
                list(selected_tributes),
                player_field, opp_field,
                player_hand, opp_hand,
                gs, game_objects,
            )
            return True
        return False   # mid-tribute, keep selection

    print(f"[Info] No interaction defined for hand card {name_h} ({type_h}) "
          f"→ {name_t} ({type_t})")
    return True  # clear selection


# ---------------------------------------------------------------------------
# Field-card interaction resolver (unchanged logic, signature extended)
# ---------------------------------------------------------------------------

def _resolve_interaction(
    card_a, owner_a,
    card_b, owner_b,
    active_player,
    player_field, opp_field,
    player_hand,  opp_hand,
    player_lp,    opp_lp,
    player_gy,    opp_gy,
    game_objects,
    build_game_state,
    player_deck,  opp_deck,
    turn_number,
    game_phase="Main 1",
    has_drawn_this_turn=False,
    has_summoned_this_turn=False,
):
    """
    Decides what cardengine action to fire when field card_a is used on card_b.
    """
    global pending_summon_card, pending_summon_owner, selected_tributes

    meta_a = getattr(card_a, "meta", {}) or {}
    meta_b = getattr(card_b, "meta", {}) or {}

    type_a = meta_a.get("type", card_a.card_type)
    type_b = meta_b.get("type", card_b.card_type)

    name_a = meta_a.get("name", "?")
    name_b = meta_b.get("name", "?")

    my_hand  = player_hand  if owner_a == "player" else opp_hand
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
    if (pending_summon_card is not None
            and card_a is pending_summon_card
            and owner_a == pending_summon_owner
            and owner_b == owner_a
            and "Monster" in str(type_b)
            and (card_b in player_field or card_b in opp_field)):

        if card_b not in selected_tributes:
            selected_tributes.append(card_b)
            level  = (getattr(pending_summon_card, "meta", {}) or {}).get("level", 0)
            needed = rules.tributes_required(pending_summon_card)
            have   = len(selected_tributes)
            print(f"[Tribute] Selected {name_b} as tribute "
                  f"({have}/{needed} for Lv{level} {name_a}).")
        else:
            print(f"[Tribute] {name_b} is already selected as a tribute.")
            return

        needed = rules.tributes_required(pending_summon_card)
        if len(selected_tributes) >= needed:
            _attempt_tribute_summon(
                pending_summon_card, pending_summon_owner,
                list(selected_tributes),
                player_field, opp_field,
                player_hand, opp_hand,
                gs, game_objects,
            )
        return

    # ── Case 2: Monster attacks opponent's monster ─────────────────────────
    if ("Monster" in type_a and "Monster" in type_b and owner_a != owner_b):
        card_a.owner = owner_a
        card_b.owner = owner_b
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
        else:
            # Build a damage announcement if LP was dealt
            dmg = result.get("lp_damage", {})
            p_dmg = dmg.get("player", 0)
            o_dmg = dmg.get("opponent", 0)
            if p_dmg or o_dmg:
                target   = "Player" if p_dmg else "Opponent"
                amount   = p_dmg or o_dmg
                attacker_name = (getattr(card_a, "meta", {}) or {}).get("name", "?")
                ann = game_objects.get("ann_state", [None, 0])
                _arm_announcement({
                    "announcement_title": f"⚔ {amount} Battle Damage!",
                    "announcement_body":  [
                        f"{attacker_name} deals {amount} damage to {target}.",
                        f"{target} LP: {game_objects['player_lp'][0] if p_dmg else game_objects['opp_lp'][0]:,}",
                    ],
                    "announcement_kind":  "damage",
                }, ann)
                game_objects["ann_state"] = ann
        return

    # ── Case 3: Spell/Trap activated targeting a card ─────────────────────
    if "Spell" in type_a or "Trap" in type_a:
        if owner_a != active_player:
            print("[Blocked] Can't activate opponent's card.")
            return
        card_a.owner = owner_a
        card_b.owner = owner_b
        result = submit_action("activate", {
            "card":         card_a,
            "owner":        owner_a,
            "targets":      [card_b],
            "game_state":   gs,
            "player_field": player_field,
            "opp_field":    opp_field,
        })
        apply_result(result, game_objects)
        for msg in result["log"]:
            print(f"[Activate] {msg}")
        if not result["ok"]:
            print(f"[Blocked] {result['error']}")
        else:
            ann = game_objects.get("ann_state", [None, 0])
            _arm_announcement(result, ann)
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

            level = meta_a.get("level", "?")
            pending_summon_card  = card_a
            pending_summon_owner = owner_a
            selected_tributes    = [card_b]
            print(f"[Tribute] Lv{level} {name_a} needs {needed} tribute(s). "
                  f"Selected {name_b} (1/{needed}). "
                  f"Click another own monster to add more, or Esc to cancel.")

            if len(selected_tributes) >= needed:
                _attempt_tribute_summon(
                    pending_summon_card, pending_summon_owner,
                    list(selected_tributes),
                    player_field, opp_field,
                    player_hand, opp_hand,
                    gs, game_objects,
                )
            return

    print(f"[Info] No interaction defined for {name_a} ({type_a}) "
          f"→ {name_b} ({type_b})")


def _attempt_tribute_summon(
    summon_card, summon_owner,
    tributes,
    player_field, opp_field,
    player_hand,  opp_hand,
    gs, game_objects,
):
    global pending_summon_card, pending_summon_owner, selected_tributes

    my_hand  = player_hand  if summon_owner == "player" else opp_hand
    my_field = player_field if summon_owner == "player" else opp_field

    # Remove summon card from hand BEFORE submit_action.
    # apply_result also calls remove_card but if the hand has already
    # repositioned visually it can silently no-op, leaving the card in
    # both hand and field at the same time.
    my_hand.remove_card(summon_card)
    summon_card.in_hand     = False
    summon_card.is_dragging = False
    summon_card.angle       = 0
    summon_card.owner       = summon_owner

    # Stamp owner on tributes so apply_result routes them to the right GY.
    for t in tributes:
        t.owner = summon_owner

    # Rebuild gs so has_summoned_this_turn is current — the gs passed in
    # was snapshotted at the first tribute click and may be stale.
    fresh_gs = dict(gs)
    fresh_gs["has_summoned_this_turn"] = game_objects.get("has_summoned_this_turn", False)

    result = submit_action("summon", {
        "card":           summon_card,
        "owner":          summon_owner,
        "field_monsters": my_field,
        "tributes":       tributes,
        "game_state":     fresh_gs,
    })

    apply_result(result, game_objects)

    for msg in result.get("log", []):
        print(f"[Summon] {msg}")

    if not result.get("ok"):
        print(f"[Blocked] {result.get('error')}")
        # Summon failed — return card to hand; tributes stay on field
        summon_card.in_hand = True
        my_hand.add_card(summon_card)
    else:
        # Position the summoned card on screen
        zoom_level = game_objects.get("zoom_level", 1.0)
        cam_offset = game_objects.get("cam_offset", (0, 0))
        zones      = game_objects.get("zones", {})

        default_screen_x = SCREEN_SIZE[0] // 2
        default_screen_y = (SCREEN_SIZE[1] // 2 + 120) if summon_owner == "player" \
                           else (SCREEN_SIZE[1] // 2 - 120)

        snapped, snap_rect = try_snap(
            summon_card,
            (default_screen_x, default_screen_y),
            zones, zoom_level, cam_offset, summon_owner,
        )
        if not snapped:
            cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
            cam_x, cam_y = cam_offset
            summon_card.world_x = (default_screen_x - cx) / zoom_level - cam_x
            summon_card.world_y = (default_screen_y - cy) / zoom_level - cam_y

        summon_card.update_visuals(zoom_level)
        reposition_field_card(summon_card, zoom_level, cam_offset)
        game_objects["has_summoned_this_turn"] = True

    pending_summon_card  = None
    pending_summon_owner = None
    selected_tributes    = []


def _arm_announcement(result: dict, announcement_state: list) -> None:
    """
    Reads announcement keys written by effect handlers into a result dict
    and stores them in announcement_state so the draw loop can display them.

    announcement_state is a 2-element list [announcement, timer] so it can
    be mutated from inside nested functions without nonlocal declarations:
        announcement_state = [None, 0]
        _arm_announcement(result, announcement_state)
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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

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

    zones        = {}
    export_flash = 0
    lp_edit_target  = None
    lp_input_buffer = ""

    # Announcement banner state
    # Set announcement + announcement_timer whenever a spell fires or damage lands.
    announcement       = None   # dict: {title, body, kind}  |  None
    announcement_timer = 0      # frames remaining (180 = 3 s at 60 fps)

    # Mutable 2-element list so nested helpers can arm it without nonlocal
    ann_state = [announcement, announcement_timer]

    # ── game_objects dict passed to apply_result ───────────────────────────
    # Includes helper references so apply_result can drive the draw action
    # without any coupling back to Main.py's local scope.
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
        # Spatial helpers used by _attempt_tribute_summon for screen placement
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

        # Sync announcement state from game_objects (helpers write to ann_state)
        ann_state          = game_objects["ann_state"]
        announcement       = ann_state[0]
        announcement_timer = ann_state[1]

        zones    = draw_field_zones(screen, zoom_level, (cam_x, cam_y), font,
                                    active_player=active_player)

        # Keep spatial helpers available to _attempt_tribute_summon
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

                elif event.key == pygame.K_ESCAPE:
                    # Cancel tribute summon or deselect
                    if pending_summon_card is not None:
                        active_hand = player_hand if pending_summon_owner == "player" \
                                      else opp_hand
                        _cancel_pending_tribute(active_hand)
                    # If we have a selected hand card mid-tribute, return it
                    if drag_candidate is not None:
                        active_hand_obj.add_card(drag_candidate)
                        drag_candidate = drag_candidate_owner = drag_start_pos = None
                    clicked_card = clicked_owner = None

                elif event.key == pygame.K_TAB:
                    # End turn
                    if pending_summon_card is not None:
                        active_hand = player_hand if pending_summon_owner == "player" \
                                      else opp_hand
                        _cancel_pending_tribute(active_hand)

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
                        _safe_remove(player_field, target_del)
                        _safe_remove(opp_field,    target_del)
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
                                    game_phase = "Standby"
                                    print(f"[Phase] {active_player.upper()} — Standby Phase")
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
                                    game_phase = "Standby"
                                    print(f"[Phase] {active_player.upper()} — Standby Phase")
                            else:
                                print(f"[Blocked] {result['error']}")

                    else:
                        # 3. Hand card — LMB = DRAG to field
                        c = active_hand_obj.check_click(event.pos)
                        if c:
                            if pending_summon_card is not None and c is not pending_summon_card:
                                active_hand = player_hand if pending_summon_owner == "player" \
                                              else opp_hand
                                _cancel_pending_tribute(active_hand)
                            drag_candidate       = c
                            drag_candidate_owner = active_player
                            drag_start_pos       = event.pos

                        else:
                            # 4. Field card — LMB = begin drag
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
                                # ── First click: select + begin drag ──
                                clicked_card  = hit
                                clicked_owner = hit_owner
                                hit.is_dragging = True
                                selected_card   = hit
                                selected_owner  = hit_owner
                                hit.zone_name   = None
                                (player_field if hit_owner == "player"
                                 else opp_field).remove(hit)

                elif event.button == 2:
                    is_panning = True

                elif event.button == 3:
                    # RMB on hand card → select / interact
                    c = active_hand_obj.check_click(event.pos)
                    if c:
                        if pending_summon_card is not None and c is not pending_summon_card:
                            active_hand = player_hand if pending_summon_owner == "player" \
                                          else opp_hand
                            _cancel_pending_tribute(active_hand)
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
                                keep_selected = _resolve_hand_action(
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
                                    # Mid-tribute: keep clicked_card = pending_summon_card
                                    clicked_card  = pending_summon_card
                                    clicked_owner = pending_summon_owner
                                else:
                                    clicked_card = clicked_owner = None

                            # ── Interaction: field card → field card ──
                            elif (clicked_card is not None
                                    and clicked_card is not hit):
                                _resolve_interaction(
                                    clicked_card, clicked_owner,
                                    hit,          hit_owner,
                                    active_player,
                                    player_field, opp_field,
                                    player_hand,  opp_hand,
                                    player_lp,    opp_lp,
                                    player_gy,    opp_gy,
                                    game_objects,
                                    build_game_state,
                                    player_deck,  opp_deck,
                                    turn_number,
                                    game_phase,
                                    has_drawn_this_turn,
                                    has_summoned_this_turn,
                                )
                                if pending_summon_card is None:
                                    clicked_card = clicked_owner = None
                                else:
                                    clicked_card  = pending_summon_card
                                    clicked_owner = pending_summon_owner

                            elif pending_summon_card is None:
                                # No selection active → cycle ATK / DEF / SET
                                hit.toggle_position()

                        else:
                            # Clicked empty space
                            if pending_summon_card is not None:
                                active_hand = player_hand \
                                              if pending_summon_owner == "player" \
                                              else opp_hand
                                _cancel_pending_tribute(active_hand)
                            # Return any selected hand card
                            if clicked_card is not None and clicked_card.in_hand:
                                # Card was selected from hand but never acted on — keep it
                                pass
                            clicked_card = clicked_owner = None

            # ── Mouse motion ───────────────────────────────────────────────
            elif event.type == pygame.MOUSEMOTION:
                if selected_card:
                    # Dragging a field card
                    selected_card.rect.center = mouse_pos

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
                    # ── LMB up: drop a dragged hand card ──────────────────
                    if drag_candidate is not None:
                        # Released before crossing drag threshold → discard candidate
                        drag_candidate = drag_candidate_owner = drag_start_pos = None

                    # ── Drop a dragged card ────────────────────────────────
                    elif selected_card:
                        drop_pos = event.pos
                        drop_y   = drop_pos[1]

                        if (selected_owner == "player"
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
                                    ok, reason = rules.can_normal_summon(
                                        selected_card, dest, [],
                                        {"has_summoned_this_turn": has_summoned_this_turn})
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
                                    "tributes":       [],
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
                                        "card":         selected_card,
                                        "owner":        selected_owner,
                                        "targets":      [],
                                        "game_state":   gs,
                                        "player_field": player_field,
                                        "opp_field":    opp_field,
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
                                    # Arm announcement from effect output
                                    _arm_announcement(result, ann_state)
                                    announcement       = ann_state[0]
                                    announcement_timer = ann_state[1]
                                    # Normal Spells go straight to GY after
                                    # resolving — don't place on field
                                    meta_s = getattr(selected_card, "meta", {}) or {}
                                    spell_type = meta_s.get("type",
                                                 selected_card.card_type)
                                    if "Normal" in str(spell_type) and \
                                       "Spell"  in str(spell_type):
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
        if selected_tributes:
            for tribute_card in selected_tributes:
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

        # ── Draw: actively dragged card (always on top) ────────────────────
        if selected_card:
            selected_card.draw(screen)

        # ── Draw: selected card info panel ────────────────────────────────
        draw_card_info_panel(screen, clicked_card, font, small_font)

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
            mouse_pos)

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

        pygame.display.flip()
        clock.tick(FPS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_remove(lst, item):
    try:
        lst.remove(item)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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


if __name__ == "__main__":
    main()