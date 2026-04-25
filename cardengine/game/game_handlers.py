"""
cardengine/game_handlers.py
---------------------------
One handler function per action type.

Each handler receives a context dict from submit_action and returns a
result dict (built with _ok / _err from game_helpers).

Adding a new action type
------------------------
1.  Write _handle_<action>(ctx) here.
2.  Add it to the HANDLERS dict in game.py's submit_action.
3.  If the action produces a new result key (e.g. draw_count), make sure
    apply_result in game_apply.py reads and acts on it.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from cardengine import battle, rules, effects
from .game_helpers import _ok, _err, _name, _safe_remove, _lp_from_result

if TYPE_CHECKING:
    from engine.card import Card


# ---------------------------------------------------------------------------
# Attack
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
    # (e.g. Dark Magician Girl's GY boost) can read graveyards and field.
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

    # dmg_ctx: full game_state plus the hand/graveyard of the DEFENDING player
    # so that hand-trap effects (e.g. Kuriboh) can find and remove their card.
    # Whoever is NOT the active_player is the defending player.
    defending_player = "opponent" if active_player == "player" else "player"
    dmg_ctx = {
        "game_state":    game_state,
        "active_player": active_player,
        # --- hand-trap support ---
        "hand":          ctx.get(f"{defending_player}_hand",      []),
        "graveyard":     ctx.get(f"{defending_player}_graveyard", []),
        # pre-populate damage so on_damage_calc handlers can read/write it
        "damage":        0,
        "damage_target": defending_player,
    }

    effects.dispatch("on_damage_calc", attacker, dmg_ctx)
    effects.dispatch("on_damage_calc", defender, dmg_ctx)

    res = battle.resolve_attack(attacker, defender, battle_ctx)

    to_gy   = []
    eff_msg = dmg_ctx.get("effect_message")

    # If a damage-calc handler zeroed out damage (e.g. Kuriboh), respect it.
    if dmg_ctx.get("damage") == 0 and res["damage"] != 0:
        res = dict(res)   # don't mutate the battle module's dict directly
        res["damage"] = 0
        if eff_msg:
            log.append(eff_msg)

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


# ---------------------------------------------------------------------------
# Quick Effect (hand-trap activation via ⚡ button)
# ---------------------------------------------------------------------------

def _handle_quick_effect(ctx: dict) -> dict:
    """
    Resolves a quick effect activated from hand by the non-active player.

    This is the handler for action type "quick_effect".  Main.py calls it
    when the player clicks a ⚡ button produced by
    ui.quick_effect_btn_hit_test().

    Context keys
    ------------
    card          : Card    — the hand card whose effect is being activated
    hook          : str     — the hook to dispatch (e.g. "on_damage_calc")
    game_state    : dict    — full game state (forwarded to the handler)
    hand          : list    — activating player's hand (handler may remove card)
    graveyard     : list    — activating player's GY  (handler may append card)

    Any additional keys are forwarded verbatim to the effect handler so it
    can read context it needs (e.g. "damage", "damage_target" for Kuriboh).

    What the effect handler should do
    ----------------------------------
    1.  Read ctx to decide whether conditions are met.
    2.  Modify ctx in-place (e.g. ctx["damage"] = 0).
    3.  Set ctx["effect_message"] if it wants a log line.
    4.  Optionally append to ctx["send_to_gy"] if it moves cards.

    Adding a new "quick_effect" action type to game.py
    ---------------------------------------------------
    In game.py's HANDLERS dict:

        from cardengine.game_handlers import _handle_quick_effect
        HANDLERS = {
            ...
            "quick_effect": _handle_quick_effect,
        }
    """
    card       = ctx.get("card")
    hook       = ctx.get("hook")
    game_state = ctx.get("game_state", {})

    if card is None:
        return _err("No card provided for quick effect.")
    if not hook:
        return _err("No hook specified for quick effect.")

    if not effects.has_effect(card, hook):
        return _err(
            f"{_name(card)} has no handler registered for hook '{hook}'."
        )

    log = [f"Quick Effect — {_name(card)} activated!"]

    # Snapshot damage before dispatch so we can detect if it was zeroed
    damage_before = ctx.get("damage", 0)

    try:
        effects.dispatch(hook, card, ctx)
    except (effects.PhaseError, effects.ActivationConditionError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Effect Error: {str(e)}")

    eff_msg  = ctx.get("effect_message")
    send_gy  = ctx.get("send_to_gy") or []
    damage_after = ctx.get("damage", damage_before)

    if eff_msg:
        log.append(eff_msg)

    # If the effect reduced damage (e.g. Kuriboh), issue an LP refund.
    # This covers the case where the attack already resolved and LP was
    # already deducted — we give the difference back as negative lp_damage
    # (apply_result adds it, so a negative value adds LP back).
    damage_negated = max(0, damage_before - damage_after)
    damage_target  = ctx.get("damage_target", "player")
    if damage_negated:
        lp_refund = {
            "player":   -damage_negated if damage_target == "player"   else 0,
            "opponent": -damage_negated if damage_target == "opponent" else 0,
        }
    else:
        lp_refund = {"player": 0, "opponent": 0}

    result = _ok(
        log=log,
        send_to_gy=send_gy,
        effect_message=eff_msg,
        lp_damage=lp_refund,
    )

    # Forward any announcement keys the handler may have set
    for ann_key in ("announcement_title", "announcement_body", "announcement_kind"):
        if ann_key in ctx:
            result[ann_key] = ctx[ann_key]

    return result


# ---------------------------------------------------------------------------
# Summon
# ---------------------------------------------------------------------------

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
    game_state = ctx.get("game_state", {}) or {}
    ok, reason = rules.can_normal_summon(card, field_monsters, tributes, game_state)
    if not ok:
        return _err(reason)

    # Validate every tribute is actually on the field
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


# ---------------------------------------------------------------------------
# Activate (hand)
# ---------------------------------------------------------------------------

def _handle_activate(ctx: dict) -> dict:
    card    = ctx.get("card")
    targets = ctx.get("targets", [])

    if card is None:
        return _err("No card provided.")

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
        return _err(str(e))
    except Exception as e:
        return _err(f"Effect Error: {str(e)}")

    effect_gy  = ctx.get("send_to_gy") or []
    effect_msg = ctx.get("effect_message")
    if effect_msg:
        log.append(effect_msg)

    result = _ok(log=log, send_to_gy=effect_gy, effect_message=effect_msg)
    if ctx.get("draw_count"):
        result["draw_count"] = ctx["draw_count"]
    for ann_key in ("announcement_title", "announcement_body", "announcement_kind"):
        if ann_key in ctx:
            result[ann_key] = ctx[ann_key]
    return result


# ---------------------------------------------------------------------------
# Set (face-down)
# ---------------------------------------------------------------------------

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

    Effects are NOT fired on Set. The effect hook fires on flip_activate instead.
    Stamps card.turn_set so can_flip_activate can enforce the same-turn rule.
    """
    card        = ctx.get("card")
    owner       = ctx.get("owner", getattr(card, "owner", "player") if card else "player")
    field_cards = ctx.get("field_monsters", [])
    tributes    = ctx.get("tributes", []) or []
    game_state  = ctx.get("game_state", {}) or {}

    if card is None:
        return _err("No card provided.")

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
        if rules.is_extra_deck_monster(card):
            meta_type = (getattr(card, "meta", {}) or {}).get("type", "Extra Deck monster")
            return _err(f"{meta_type} cannot be Set.")

        monsters_only = [c for c in field_cards if rules.is_monster(c)]
        ok, reason = rules.can_set_monster(card, monsters_only, tributes, game_state)
        if not ok:
            return _err(reason)

        field_ids = set(id(m) for m in monsters_only)
        for t in tributes:
            if id(t) not in field_ids:
                return _err(f"Tribute '{_name(t)}' is not on your field and cannot be tributed.")

        for t in tributes:
            if not getattr(t, "owner", None):
                t.owner = owner

        card.mode = "SET"
        card.turn_set = game_state.get("turn") or game_state.get("meta", {}).get("turn")
        card.summoning_sickness = True

        log = [f"{_name(card)} Set face-down."]
        if tributes:
            log.append(f"Tributed: {', '.join(_name(t) for t in tributes)}")

        return _ok(
            log=log,
            send_to_gy=tributes,
            summoned_card=card,
        )

    return _err("This card type cannot be Set.")


# ---------------------------------------------------------------------------
# Flip-activate (face-down → face-up + resolve)
# ---------------------------------------------------------------------------

def _handle_flip_activate(ctx: dict) -> dict:
    """
    Flip a face-down Set Spell/Trap face-up and resolve its effect.
    Monsters are NOT routed here — use the position toggle in Main.py.
    """
    card = ctx.get("card")
    if card is None:
        return _err("No card provided.")

    if rules.is_monster(card):
        return _err("Use position toggle (not flip-activate) for monster cards.")

    game_state = ctx.get("game_state", {}) or {}

    ok, reason = rules.can_flip_activate(card, game_state)
    if not ok:
        return _err(reason)

    # Flip face-up BEFORE dispatching so live-field checks see it as face-up
    card.mode = "ATK"

    log = [f"{_name(card)} flipped face-up."]

    targets = ctx.get("targets", []) or []
    for target in targets:
        ok, reason = rules.can_be_targeted(target)
        if not ok:
            card.mode = "SET"
            return _err(f"Invalid target — {reason}")

    try:
        effects.dispatch("on_spell_activate", card, ctx)
    except (effects.PhaseError, effects.ActivationConditionError, effects.SetTimingError) as e:
        card.mode = "SET"
        return _err(str(e))
    except Exception as e:
        card.mode = "SET"
        return _err(f"Effect Error: {str(e)}")

    effect_gy  = ctx.get("send_to_gy") or []
    effect_msg = ctx.get("effect_message")
    if effect_msg:
        log.append(effect_msg)

    result = _ok(log=log, send_to_gy=effect_gy, effect_message=effect_msg)
    if ctx.get("draw_count"):
        result["draw_count"] = ctx["draw_count"]
    for ann_key in ("announcement_title", "announcement_body", "announcement_kind"):
        if ann_key in ctx:
            result[ann_key] = ctx[ann_key]
    return result


# ---------------------------------------------------------------------------
# Send to GY (destruction outside of battle)
# ---------------------------------------------------------------------------

def _handle_send_to_gy(ctx: dict) -> dict:
    card = ctx.get("card")
    if card is None:
        return _err("No card provided.")

    effects.dispatch("on_destroy", card, ctx)
    return _ok(
        log=[f"{_name(card)} sent to GY."],
        send_to_gy=[card],
    )


# ---------------------------------------------------------------------------
# Draw (phase draw action)
# ---------------------------------------------------------------------------

def _handle_draw(ctx: dict) -> dict:
    """
    Validates and approves a normal Draw Phase draw.
    Returns effect_message="execute_draw" so game_apply picks it up.
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