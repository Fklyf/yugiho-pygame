"""
Game-state serialisation and card loading.

The card-engine speaks JSON-ish dicts; this module is the bridge between the
in-memory pygame Card objects and those dicts.  build_game_state() is what
gets passed into rules / submit_action / apply_result.

  card_to_state         Single-card snapshot (with optional face-down hide).
  build_game_state      Whole-board snapshot — feeds rules.* and the engine.
  export_game_state     Dump a snapshot to JSON on disk.
  load_card             Construct an in-memory Card from a metadata dict.
"""

import datetime
import json
import os

import pygame

from engine.card import Card


# ---------------------------------------------------------------------------
# Serialisation
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
                     game_phase="Main",
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
    """Construct a Card from a metadata dict.  Falls back to a red surface
    if the image file can't be found."""
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
