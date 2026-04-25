"""
cardengine/game.py
------------------
Coordinator between Main.py's event loop and the cardengine subsystems.

Main.py calls exactly two things:
    action_result = game.submit_action(action, context)
    game.apply_result(action_result, game_objects)

Everything else (battle resolution, rule checks, effect dispatch, LP damage)
happens in here.  Main.py never needs to import battle.py, rules.py, or
effects.py directly.

─────────────────────────────────────────────────────────────────────────────
Action types
─────────────────────────────────────────────────────────────────────────────
    "attack"        — one monster attacks another (or direct)
    "summon"        — a card is played from hand / Extra Deck to field
    "activate"      — a spell/trap is activated
    "send_to_gy"    — card is destroyed / discarded outside of battle
    "draw"          — active player draws the top card of their deck
                      (only legal in Draw Phase, once per turn)

─────────────────────────────────────────────────────────────────────────────
Result dict (always returned by submit_action)
─────────────────────────────────────────────────────────────────────────────
    {
        "ok":               bool,
        "error":            str | None,
        "log":              list[str],
        "send_to_gy":       list[Card],
        "lp_damage": {
            "player":       int,
            "opponent":     int,
        },
        "effect_message":   str | None,
        "summoned_card":    Card | None,
    }
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from cardengine import battle, rules, effects
from cardengine.cards import dark_magic_attack

try:
    from config import RULES_MODE
except ImportError:
    RULES_MODE = "loose"

if TYPE_CHECKING:
    from engine.card import Card


# ---------------------------------------------------------------------------
# Public API — called from Main.py
# ---------------------------------------------------------------------------

def submit_action(action: str, context: dict) -> dict:
    handlers = {
        "attack":         _handle_attack,
        "summon":         _handle_summon,
        "activate":       _handle_activate,
        "set":            _handle_set,
        "flip_activate":  _handle_flip_activate,
        "send_to_gy":     _handle_send_to_gy,
        "draw":           _handle_draw,
    }
    handler = handlers.get(action)
    if handler is None:
        return _err(f"Unknown action: '{action}'")
    return handler(context)


def apply_result(result: dict, game_objects: dict) -> None:
    """
    Mutates game_objects in-place to reflect a successful action result.

    Handles:
      • LP damage  (player_lp / opp_lp)
      • Cards sent to the graveyard  (send_to_gy)
      • A newly summoned card placed on the field  (summoned_card)
      • Drawing a card from the deck  (effect_message == "execute_draw")
    """
    if not result.get("ok"):
        return

    # ── 1. LP damage ──────────────────────────────────────────────────────
    lp_damage = result.get("lp_damage", {})
    p_dmg = lp_damage.get("player", 0)
    o_dmg = lp_damage.get("opponent", 0)

    if p_dmg:
        game_objects["player_lp"][0] = max(0, game_objects["player_lp"][0] - p_dmg)
    if o_dmg:
        game_objects["opp_lp"][0]    = max(0, game_objects["opp_lp"][0]    - o_dmg)

    # ── 2. Cards sent to GY ───────────────────────────────────────────────
    _gy_debug = result.get("send_to_gy") or []
    if _gy_debug:
        def _gdbg(msg):
            print(msg)
            try:
                with open("dma_debug.txt", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
        _gdbg(f"[apply_result] processing {len(_gy_debug)} send_to_gy cards")
        _gdbg(f"[apply_result] player_field len before: {len(game_objects['player_field'])}")
        _gdbg(f"[apply_result] opp_field    len before: {len(game_objects['opp_field'])}")

    for card in result.get("send_to_gy", []):
        owner = getattr(card, "owner", None)
        if _gy_debug:
            name = (getattr(card, "meta", {}) or {}).get("name", "?")
            in_pf = card in game_objects["player_field"]
            in_of = card in game_objects["opp_field"]
            _gdbg(f"[apply_result]   card={name!r} owner={owner!r} "
                  f"in_player_field={in_pf} in_opp_field={in_of}")

        # Remove from whichever field/hand it might still be in
        _safe_remove(game_objects["player_field"], card)
        _safe_remove(game_objects["opp_field"],    card)
        game_objects["player_hand"].remove_card(card)
        game_objects["opp_hand"].remove_card(card)

        # Route to the correct graveyard
        if owner == "opponent":
            game_objects["opp_gy"].add_card(card)
        else:
            # Default: player-owned or unowned cards go to player GY
            game_objects["player_gy"].add_card(card)

    if _gy_debug:
        _gdbg(f"[apply_result] player_field len after:  {len(game_objects['player_field'])}")
        _gdbg(f"[apply_result] opp_field    len after:  {len(game_objects['opp_field'])}")
        _gdbg(f"[apply_result] player_gy    len after:  {len(game_objects['player_gy'].cards)}")
        _gdbg(f"[apply_result] opp_gy       len after:  {len(game_objects['opp_gy'].cards)}")

    # ── 3. Summoned card → field ──────────────────────────────────────────
    # apply_result is the single source of truth for placing a card on the
    # field list.  Main.py must NOT also call dest.append after this runs.
    summoned = result.get("summoned_card")
    if summoned is not None:
        owner = getattr(summoned, "owner", "player")

        # Remove from hand first — safe no-op if already removed
        game_objects["player_hand"].remove_card(summoned)
        game_objects["opp_hand"].remove_card(summoned)

        field = game_objects["player_field"] if owner == "player" \
                else game_objects["opp_field"]
        if summoned not in field:
            field.append(summoned)

        # Reposition the card's screen rect using current camera/zoom so it
        # doesn't render at (0, 0) as a ghost.  Uses game_objects spatial
        # helpers injected by Main.py each frame.
        zoom_level = game_objects.get("zoom_level", 1.0)
        cam_offset = game_objects.get("cam_offset", (0, 0))
        if hasattr(summoned, "rect") and hasattr(summoned, "world_x"):
            from config import SCREEN_SIZE as _SS
            cx, cy   = _SS[0] // 2, _SS[1] // 2
            cam_x, cam_y = cam_offset
            summoned.rect.centerx = int(cx + (summoned.world_x + cam_x) * zoom_level)
            summoned.rect.centery = int(cy + (summoned.world_y + cam_y) * zoom_level)

    # ── 4. Draw action ────────────────────────────────────────────────────
    if result.get("effect_message") == "execute_draw":
        active_player = game_objects.get("active_player", "player")

        if active_player == "player":
            deck      = game_objects["player_deck"]
            hand      = game_objects["player_hand"]
            deck_path = game_objects.get("player_deck_path", "")
        else:
            deck      = game_objects["opp_deck"]
            hand      = game_objects["opp_hand"]
            deck_path = game_objects.get("opp_deck_path", "")

        if deck:
            # Main.py injects a load_card helper + back_img so we can build
            # a proper Card object from raw deck data here.
            load_card = game_objects.get("load_card")
            back_img  = game_objects.get("back_img")

            if load_card and back_img is not None:
                card_data  = deck.pop()
                drawn_card = load_card(card_data, deck_path, back_img)
            else:
                # Fallback: deck items are already Card objects
                drawn_card = deck.pop()

            hand.add_card(drawn_card)

        # Track draw state.  For the second player's opening hand we count
        # down draws_remaining instead of using the single has_drawn flag.
        game_state = game_objects.get("game_state", game_objects)
        if game_state.get("second_player_first_turn", False):
            remaining = game_state.get("draws_remaining", 1)
            game_state["draws_remaining"] = max(0, remaining - 1)
            if game_state["draws_remaining"] <= 0:
                # Opening hand complete — clear the special flag so normal
                # turn rules take over from here.
                game_state["second_player_first_turn"] = False
                game_state["has_drawn_this_turn"] = True
        else:
            # Normal turn: mark the single draw as consumed.
            game_objects["has_drawn_this_turn"] = True


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_attack(ctx: dict) -> dict:
    attacker: Card      = ctx.get("attacker")
    defender: Card|None = ctx.get("defender")
    active_player: str  = ctx.get("active_player", "player")
    game_state: dict    = ctx.get("game_state", {})

    if attacker is None:
        return _err("No attacker provided.")

    ok, reason = rules.can_attack(attacker, {"active_player": active_player})
    if not ok:
        return _err(reason)

    log = []
    if reason:
        log.append(f"[Rule warning] {reason}")

    a_name = _name(attacker)

    # Battle math needs the full game_state so continuous effects
    # (e.g. Dark Magician Girl's +300/DM-or-MoBC-in-GY bonus) can read
    # the graveyards and field. Merge active_player onto the state
    # dict the caller supplied.
    battle_ctx = dict(game_state) if game_state else {}
    battle_ctx["active_player"] = active_player

    if defender is None:
        res = battle.resolve_direct_attack(attacker, battle_ctx)
        log.append(f"{a_name} attacks directly for {res['damage']} damage!")
        return _ok(log=log, lp_damage=_lp_from_result(res))

    ok, reason = rules.can_be_attacked(defender)
    if not ok:
        return _err(reason)

    d_name = _name(defender)
    log.append(f"{a_name} attacks {d_name}.")

    dmg_ctx = {"game_state": game_state, "active_player": active_player}
    effects.dispatch("on_damage_calc", attacker, dmg_ctx)
    effects.dispatch("on_damage_calc", defender, dmg_ctx)

    res = battle.resolve_attack(attacker, defender, battle_ctx)

    to_gy   = []
    eff_msg = dmg_ctx.get("effect_message")

    if res["attacker_destroyed"]:
        log.append(f"{a_name} is destroyed.")
        to_gy.append(attacker)
        effects.dispatch("on_destroy", attacker, {"game_state": game_state})

    if res["defender_destroyed"]:
        log.append(f"{d_name} is destroyed.")
        to_gy.append(defender)
        effects.dispatch("on_destroy", defender, {"game_state": game_state})

    if res["damage"]:
        target = res["damage_target"] or "opponent"
        log.append(f"{res['damage']} damage to {target}.")

    return _ok(
        log=log,
        send_to_gy=to_gy,
        lp_damage=_lp_from_result(res),
        effect_message=eff_msg,
    )


def _handle_summon(ctx: dict) -> dict:
    card           = ctx.get("card")
    field_monsters = ctx.get("field_monsters", [])
    tributes       = ctx.get("tributes", [])
    owner          = ctx.get("owner", getattr(card, "owner", "player") if card else "player")

    if card is None:
        return _err("No card provided.")

    # ── Fusion Summon ──────────────────────────────────────────────────────
    if rules.is_fusion(card):
        ok, reason = rules.can_fusion_summon(card, field_monsters)
        if not ok:
            return _err(reason)

        materials_needed = rules.fusion_materials(card)
        materials_used   = []
        remaining        = list(field_monsters)

        for mat_name in materials_needed:
            for m in remaining:
                if (getattr(m, "meta", {}) or {}).get("name", "") == mat_name:
                    materials_used.append(m)
                    remaining.remove(m)
                    break

        for m in materials_used:
            if not getattr(m, "owner", None):
                m.owner = owner

        card.summoning_sickness = True
        effects.dispatch("on_summon", card, ctx)

        log = [f"{_name(card)} Fusion Summoned!"]
        log.append(f"Materials used: {', '.join(_name(m) for m in materials_used)}")

        return _ok(
            log=log,
            send_to_gy=materials_used,
            summoned_card=card,
        )

    # ── Normal / Tribute Summon ────────────────────────────────────────────
    # Pass game_state through so rules.can_normal_summon can enforce the
    # phase restriction (Main Phase 1/2 only) and other state-dependent
    # rules. Without this the rule check sees an empty dict and silently
    # short-circuits the phase guard.
    game_state = ctx.get("game_state", {}) or {}
    ok, reason = rules.can_normal_summon(card, field_monsters, tributes, game_state)
    if not ok:
        return _err(reason)

    # Validate that every tribute is actually on the field — prevents the
    # visual ghost bug where the engine accepts a tribute that was never
    # removed from the field list before placing the new card.
    field_set = set(id(m) for m in field_monsters)
    for t in tributes:
        if id(t) not in field_set:
            return _err(
                f"Tribute '{_name(t)}' is not on your field and cannot be tributed."
            )

    log = [f"{_name(card)} summoned."]
    if tributes:
        log.append(f"Tributed: {', '.join(_name(t) for t in tributes)}")

    for t in tributes:
        if not getattr(t, "owner", None):
            t.owner = owner

    card.summoning_sickness = True
    effects.dispatch("on_summon", card, ctx)

    return _ok(
        log=log,
        send_to_gy=tributes,
        summoned_card=card,
    )


def _handle_activate(ctx: dict) -> dict:
    card    = ctx.get("card")
    targets = ctx.get("targets", [])

    if card is None:
        return _err("No card provided.")

    # game_state must flow through so spell effects can read field/phase.
    # Main.py is responsible for including it in the context dict it passes,
    # the same way it does for "attack" actions.
    log = [f"{_name(card)} activated."]

    for target in targets:
        ok, reason = rules.can_be_targeted(target)
        if not ok:
            return _err(f"Invalid target — {reason}")

    meta      = getattr(card, "meta", {}) or {}
    card_type = meta.get("type", getattr(card, "card_type", ""))

    if "Equip" in card_type and targets:
        target = targets[0]
        if not hasattr(target, "equipped_with"):
            target.equipped_with = []
        card.equipped_to = target
        target.equipped_with.append(card)
        log.append(f"{_name(card)} equipped to {_name(target)}.")

    try:
        effects.dispatch("on_spell_activate", card, ctx)
    except (effects.PhaseError, effects.ActivationConditionError) as e:
        # Clean rule-level blocks — show the card's own message, not a crash.
        return _err(str(e))
    except Exception as e:
        return _err(f"Effect Error: {str(e)}")

    # Read back whatever the effect wrote into ctx.
    # Previously this was _ok(log=log) which silently discarded any cards the
    # effect queued for destruction and any effect_message it produced.
    effect_gy  = ctx.get("send_to_gy") or []
    effect_msg = ctx.get("effect_message")
    if effect_msg:
        log.append(effect_msg)

    result = _ok(log=log, send_to_gy=effect_gy, effect_message=effect_msg)
    for ann_key in ("announcement_title", "announcement_body", "announcement_kind"):
        if ann_key in ctx:
            result[ann_key] = ctx[ann_key]
    return result


def _handle_set(ctx: dict) -> dict:
    """
    Set a card face-down in the appropriate zone.

    Context keys
    ------------
    card           : Card            — the card being Set
    owner          : "player" | "opponent"
    field_monsters : list[Card]      — owner's full field list (monsters+S/T)
    tributes       : list[Card]      — only for monster Sets that need tributes
    game_state     : dict            — current turn number flows through here

    Effects are NOT fired on Set. For monsters that's vanilla rules; for
    spells/traps the effect hook fires on ``flip_activate`` instead.

    Stamps ``card.turn_set = turn_number`` so ``can_flip_activate`` can
    enforce the 'same turn' rule later.
    """
    card           = ctx.get("card")
    owner          = ctx.get("owner", getattr(card, "owner", "player") if card else "player")
    field_cards    = ctx.get("field_monsters", [])
    tributes       = ctx.get("tributes", []) or []
    game_state     = ctx.get("game_state", {}) or {}

    if card is None:
        return _err("No card provided.")

    # Stamp owner so apply_result can route correctly if needed
    if not getattr(card, "owner", None):
        card.owner = owner

    # ── Spell / Trap Set ──────────────────────────────────────────────────
    if rules.is_spell(card) or rules.is_trap(card):
        ok, reason = rules.can_set_spell_trap(card, field_cards, game_state)
        if not ok:
            return _err(reason)
        card.mode = "SET"
        card.turn_set = game_state.get("turn") or game_state.get("meta", {}).get("turn")
        return _ok(
            log=[f"{_name(card)} set face-down."],
            summoned_card=card,
        )

    # ── Monster Set (face-down DEF) ───────────────────────────────────────
    if rules.is_monster(card):
        # Extra Deck monsters cannot be Set any more than they can be Normal Summoned.
        if rules.is_extra_deck_monster(card):
            meta_type = (getattr(card, "meta", {}) or {}).get("type", "Extra Deck monster")
            return _err(f"{meta_type} cannot be Set.")

        # Only monster cards count toward tribute accounting & zone cap here.
        monsters_only = [c for c in field_cards if rules.is_monster(c)]
        ok, reason = rules.can_set_monster(card, monsters_only, tributes, game_state)
        if not ok:
            return _err(reason)

        # Validate tributes exist on field (same guard as Normal Summon)
        field_ids = set(id(m) for m in monsters_only)
        for t in tributes:
            if id(t) not in field_ids:
                return _err(f"Tribute '{_name(t)}' is not on your field and cannot be tributed.")

        for t in tributes:
            if not getattr(t, "owner", None):
                t.owner = owner

        card.mode = "SET"
        card.turn_set = game_state.get("turn") or game_state.get("meta", {}).get("turn")
        card.summoning_sickness = True   # Set still consumes the once-per-turn budget

        log = [f"{_name(card)} Set face-down."]
        if tributes:
            log.append(f"Tributed: {', '.join(_name(t) for t in tributes)}")

        return _ok(
            log=log,
            send_to_gy=tributes,
            summoned_card=card,
        )

    return _err("This card type cannot be Set.")


def _handle_flip_activate(ctx: dict) -> dict:
    """
    Flip a face-down Set Spell/Trap face-up and resolve its effect through
    the same pipeline as a hand-activated Spell.

    Monsters are NOT routed through here — flipping a face-down Set monster
    face-up is handled by Main.py's ``toggle_position`` cycle (ATK/DEF).
    """
    card = ctx.get("card")
    if card is None:
        return _err("No card provided.")

    if rules.is_monster(card):
        return _err("Use position toggle (not flip-activate) for monster cards.")

    game_state = ctx.get("game_state", {}) or {}

    # Timing rule: Traps / Quick-Play Spells can't activate the turn they were Set.
    ok, reason = rules.can_flip_activate(card, game_state)
    if not ok:
        return _err(reason)

    # Flip face-up BEFORE dispatching the effect so _controls_monster and
    # similar live-field checks see the card as face-up (not "SET").
    card.mode = "ATK"   # spells/traps don't have a battle position; "ATK"
                        # just means 'face-up' in our mode enum

    log = [f"{_name(card)} flipped face-up."]

    # Targeting checks (if the caller supplied targets)
    targets = ctx.get("targets", []) or []
    for target in targets:
        ok, reason = rules.can_be_targeted(target)
        if not ok:
            # Revert the flip since activation failed
            card.mode = "SET"
            return _err(f"Invalid target — {reason}")

    try:
        effects.dispatch("on_spell_activate", card, ctx)
    except (effects.PhaseError, effects.ActivationConditionError, effects.SetTimingError) as e:
        # Revert the flip so the card stays Set and can be tried later.
        card.mode = "SET"
        return _err(str(e))
    except Exception as e:
        card.mode = "SET"
        return _err(f"Effect Error: {str(e)}")

    effect_gy  = ctx.get("send_to_gy") or []
    effect_msg = ctx.get("effect_message")
    if effect_msg:
        log.append(effect_msg)

    # If it's a Normal Spell or Trap, caller (Main.py) is responsible for
    # sending THIS card to GY after resolution. Continuous/Equip/Field stay.
    result = _ok(log=log, send_to_gy=effect_gy, effect_message=effect_msg)
    for ann_key in ("announcement_title", "announcement_body", "announcement_kind"):
        if ann_key in ctx:
            result[ann_key] = ctx[ann_key]
    return result


def _handle_send_to_gy(ctx: dict) -> dict:
    card = ctx.get("card")
    if card is None:
        return _err("No card provided.")

    effects.dispatch("on_destroy", card, ctx)
    return _ok(
        log=[f"{_name(card)} sent to GY."],
        send_to_gy=[card],
    )


def _handle_draw(ctx: dict) -> dict:
    """
    Validates and approves a draw action.

    Validation (via rules.can_draw):
      • Must be the Draw Phase.
      • May only draw once per turn via this action.

    On success, returns effect_message="execute_draw" so apply_result
    physically moves the top card of the deck into hand and marks
    has_drawn_this_turn in game_objects.
    """
    active_player = ctx.get("active_player", "player")
    game_state    = ctx.get("game_state", {})

    ok, reason = rules.can_draw(game_state)
    if not ok:
        return _err(reason)

    return _ok(
        log=[f"{active_player.capitalize()} draws a card."],
        effect_message="execute_draw",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(*, log=None, send_to_gy=None, lp_damage=None,
        effect_message=None, summoned_card=None) -> dict:
    return {
        "ok":             True,
        "error":          None,
        "log":            log or [],
        "send_to_gy":     send_to_gy or [],
        "lp_damage":      lp_damage or {"player": 0, "opponent": 0},
        "effect_message": effect_message,
        "summoned_card":  summoned_card,
    }


def _err(reason: str) -> dict:
    return {
        "ok":             False,
        "error":          reason,
        "log":            [f"Illegal action: {reason}"],
        "send_to_gy":     [],
        "lp_damage":      {"player": 0, "opponent": 0},
        "effect_message": None,
        "summoned_card":  None,
    }


def _lp_from_result(res: dict) -> dict:
    target = res.get("damage_target")
    damage = res.get("damage", 0)
    return {
        "player":   damage if target == "player"   else 0,
        "opponent": damage if target == "opponent" else 0,
    }


def _name(card) -> str:
    return (getattr(card, "meta", {}) or {}).get("name", "Unknown")


def _safe_remove(lst: list, item) -> None:
    try:
        lst.remove(item)
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Card effect modules
# ---------------------------------------------------------------------------
# Explicit imports here guarantee every card's register() call has executed
# by the time submit_action is reachable. This is more reliable than relying
# on cardengine/__init__.py auto-discovery, which can silently miss files.
# When you add a new card effect module, add it to this list.

from cardengine.cards import dark_magic_attack  # noqa: F401