"""
cardengine/game_apply.py
------------------------
apply_result — the single function Main.py calls after submit_action.

Mutates game_objects in-place to reflect a resolved action.

What it handles
---------------
  1. LP damage          (player_lp / opp_lp)
  2. Cards sent to GY   (send_to_gy)
  3. Summoned card      (summoned_card → field)
  4a. Spell-effect draws (draw_count — e.g. Pot of Greed)
  4b. Phase draw action  (effect_message == "execute_draw")

game_objects keys expected
--------------------------
  player_lp, opp_lp        — list[int] (mutable single-element wrappers)
  player_field, opp_field   — list[Card]
  player_hand, opp_hand     — Hand objects with add_card / remove_card
  player_gy, opp_gy         — GY objects with add_card / .cards
  player_deck, opp_deck     — list[card_data] (popped from the right/top)
  player_deck_path          — str, path used by load_card
  opp_deck_path             — str
  load_card                 — callable(card_data, deck_path, back_img) → Card
  back_img                  — surface/image passed to load_card
  active_player             — "player" | "opponent"
  has_drawn_this_turn       — bool (mutated here on phase draw)
  game_state                — dict with second_player_first_turn, draws_remaining
  zoom_level                — float (for card rect repositioning)
  cam_offset                — (int, int)
"""

from __future__ import annotations
from .game_helpers import _safe_remove


def apply_result(result: dict, game_objects: dict) -> None:
    if not result.get("ok"):
        return

    # ── 1. LP damage ──────────────────────────────────────────────────────
    lp_damage = result.get("lp_damage", {})
    p_dmg = lp_damage.get("player", 0)
    o_dmg = lp_damage.get("opponent", 0)

    if p_dmg > 0:
        game_objects["player_lp"][0] = max(0, game_objects["player_lp"][0] - p_dmg)
    elif p_dmg < 0:
        # Negative = refund (e.g. Kuriboh activated after damage was dealt)
        game_objects["player_lp"][0] = min(8000, game_objects["player_lp"][0] + abs(p_dmg))
    if o_dmg > 0:
        game_objects["opp_lp"][0] = max(0, game_objects["opp_lp"][0] - o_dmg)
    elif o_dmg < 0:
        game_objects["opp_lp"][0] = min(8000, game_objects["opp_lp"][0] + abs(o_dmg))

    # ── 2. Cards sent to GY ───────────────────────────────────────────────
    gy_cards = result.get("send_to_gy") or []
    if gy_cards:
        def _gdbg(msg):
            print(msg)
            try:
                with open("dma_debug.txt", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
        _gdbg(f"[apply_result] processing {len(gy_cards)} send_to_gy cards")
        _gdbg(f"[apply_result] player_field len before: {len(game_objects['player_field'])}")
        _gdbg(f"[apply_result] opp_field    len before: {len(game_objects['opp_field'])}")

    for card in gy_cards:
        owner = getattr(card, "owner", None)
        if gy_cards:
            name  = (getattr(card, "meta", {}) or {}).get("name", "?")
            in_pf = card in game_objects["player_field"]
            in_of = card in game_objects["opp_field"]
            _gdbg(f"[apply_result]   card={name!r} owner={owner!r} "
                  f"in_player_field={in_pf} in_opp_field={in_of}")

        _safe_remove(game_objects["player_field"], card)
        _safe_remove(game_objects["opp_field"],    card)
        game_objects["player_hand"].remove_card(card)
        game_objects["opp_hand"].remove_card(card)

        if owner == "opponent":
            game_objects["opp_gy"].add_card(card)
        else:
            game_objects["player_gy"].add_card(card)

    if gy_cards:
        _gdbg(f"[apply_result] player_field len after:  {len(game_objects['player_field'])}")
        _gdbg(f"[apply_result] opp_field    len after:  {len(game_objects['opp_field'])}")
        _gdbg(f"[apply_result] player_gy    len after:  {len(game_objects['player_gy'].cards)}")
        _gdbg(f"[apply_result] opp_gy       len after:  {len(game_objects['opp_gy'].cards)}")

    # ── 3. Summoned card → field ──────────────────────────────────────────
    summoned = result.get("summoned_card")
    if summoned is not None:
        owner = getattr(summoned, "owner", "player")

        game_objects["player_hand"].remove_card(summoned)
        game_objects["opp_hand"].remove_card(summoned)

        field = game_objects["player_field"] if owner == "player" \
                else game_objects["opp_field"]
        if summoned not in field:
            field.append(summoned)

        # Reposition rect using current camera/zoom so it doesn't ghost at (0,0)
        zoom_level = game_objects.get("zoom_level", 1.0)
        cam_offset = game_objects.get("cam_offset", (0, 0))
        if hasattr(summoned, "rect") and hasattr(summoned, "world_x"):
            from config import SCREEN_SIZE as _SS
            cx, cy       = _SS[0] // 2, _SS[1] // 2
            cam_x, cam_y = cam_offset
            summoned.rect.centerx = int(cx + (summoned.world_x + cam_x) * zoom_level)
            summoned.rect.centery = int(cy + (summoned.world_y + cam_y) * zoom_level)

    # ── 4a. Spell-effect draws (e.g. Pot of Greed) ───────────────────────
    draw_count = result.get("draw_count", 0) or 0
    if draw_count:
        _draw_cards(draw_count, game_objects)

    # ── 4b. Phase draw action ─────────────────────────────────────────────
    if result.get("effect_message") == "execute_draw":
        _draw_cards(1, game_objects)

        game_state = game_objects.get("game_state", game_objects)
        if game_state.get("second_player_first_turn", False):
            remaining = game_state.get("draws_remaining", 1)
            game_state["draws_remaining"] = max(0, remaining - 1)
            if game_state["draws_remaining"] <= 0:
                game_state["second_player_first_turn"] = False
                game_state["has_drawn_this_turn"] = True
        else:
            game_objects["has_drawn_this_turn"] = True


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _draw_cards(count: int, game_objects: dict) -> None:
    """Pop `count` cards from the active player's deck into their hand."""
    active_player = game_objects.get("active_player", "player")

    if active_player == "player":
        deck      = game_objects["player_deck"]
        hand      = game_objects["player_hand"]
        deck_path = game_objects.get("player_deck_path", "")
    else:
        deck      = game_objects["opp_deck"]
        hand      = game_objects["opp_hand"]
        deck_path = game_objects.get("opp_deck_path", "")

    load_card = game_objects.get("load_card")
    back_img  = game_objects.get("back_img")

    for _ in range(count):
        if not deck:
            break
        if load_card and back_img is not None:
            card_data  = deck.pop()
            drawn_card = load_card(card_data, deck_path, back_img)
        else:
            drawn_card = deck.pop()
        hand.add_card(drawn_card)
