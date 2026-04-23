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
)
from engine.card import Card
from engine.field import draw_field_zones
from engine.hand import Hand
from engine.graveyard import Graveyard
from ui import draw_snap_highlight, draw_field_overlays, draw_hud, lp_hit_test


# ---------------------------------------------------------------------------
# Snap-to-zone helper
# ---------------------------------------------------------------------------

# Legal drop-target zones for each side.
# GY / Deck / Extra are excluded — they have their own dedicated interactions.
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

    World-coord inverse of field.py's formula:
        screen_centre = cx + (world + cam) * zoom
        → world = (screen_centre - cx) / zoom - cam
    We also store the rect so the caller can set rect.center directly,
    bypassing any pivot-formula mismatch in update_screen_position.
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

    # World coords — matches field.py's draw formula exactly
    card.world_x   = (best_rect.centerx - cx) / zoom_level - cam_offset[0]
    card.world_y   = (best_rect.centery - cy) / zoom_level - cam_offset[1]
    card.zone_name = best_zone
    return True, best_rect



# ---------------------------------------------------------------------------
# Field-card screen positioning
# ---------------------------------------------------------------------------
# field.py draws zone centres at:  cx + (world + cam) * zoom
# We must use the SAME formula for field cards so snapped cards always sit
# exactly on their zone, regardless of pan or zoom level.

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
    """
    Serialises a card's full logical game status plus complete card metadata.

    hide_if_set=True is used for opponent face-down field cards — the LLM
    should not know what a SET card is until it is flipped.

    The player's own hand is always fully revealed (the LLM is acting as
    the player's assistant and needs to know every card in hand).
    The opponent's hand is always hidden — we only know the count.
    """
    mode    = card.mode                        # "ATK" | "DEF" | "SET" | "FACE_UP"
    face_up = (mode != "SET")
    hidden  = hide_if_set and not face_up      # True only for opp face-down field cards

    # Battle position for monsters; None for Spell/Trap
    if "Monster" in card.card_type:
        battle_position = "DEF" if mode in ("DEF", "SET") else "ATK"
    else:
        battle_position = None

    if hidden:
        # Opponent's face-down card — reveal nothing except field status
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

    # Full identity — pulled straight from the metadata dict the downloader wrote
    meta = getattr(card, "meta", {}) or {}
    return {
        # ── Card identity ──────────────────────────────────────────────────
        "id":              meta.get("id"),
        "name":            meta.get("name", "Unknown"),
        "type":            meta.get("type", card.card_type),
        "card_type":       card.card_type,
        "desc":            meta.get("desc", ""),
        "atk":             meta.get("atk"),      # None for non-monsters
        "def":             meta.get("def"),      # None for non-monsters
        # ── Field status ───────────────────────────────────────────────────
        "zone":            getattr(card, "zone_name", None),
        "in_hand":         card.in_hand,
        "face_up":         face_up,
        "battle_position": battle_position,      # "ATK" | "DEF" | null
        "mode":            mode,
    }


def build_game_state(player_hand, player_field, player_gy,
                     opp_hand,    opp_field,    opp_gy,
                     p_deck_count, o_deck_count,
                     player_lp,   opp_lp,
                     turn_number, active_player):
    """
    Builds the complete game state dict for export / LLM consumption.

    Visibility rules:
      • Player hand     → fully revealed (player is the LLM's user)
      • Opponent hand   → count only, no card details
      • Player field    → always fully revealed
      • Opponent field  → revealed except SET (face-down) cards
    """
    return {
        "meta": {
            "turn":          turn_number,
            "active_player": active_player,
            "timestamp":     datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "player": {
            "life_points": player_lp,
            "hand":        [card_to_state(c) for c in player_hand.cards],
            "field":       [card_to_state(c) for c in player_field],
            "graveyard":   [card_to_state(c) for c in player_gy.cards],
            "deck_count":  p_deck_count,
        },
        "opponent": {
            "life_points": opp_lp,
            # Opponent hand: count + hidden placeholders — LLM knows how many
            # cards they hold but not what they are
            "hand_count":  len(opp_hand.cards),
            "hand":        [{"name": "???", "id": None, "in_hand": True}
                            for _ in opp_hand.cards],
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
    folder = "assets/Deck_Yugi"

    # Card back
    bp = "assets/card_back.png"
    back_img = pygame.image.load(bp).convert_alpha() if os.path.exists(bp) \
               else pygame.Surface((400, 580))
    if not os.path.exists(bp):
        back_img.fill((50, 50, 50))

    # Deck
    try:
        with open(f"{folder}/metadata.json") as f:
            raw = json.load(f)
            deck_data = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    except Exception as e:
        print(f"Deck load error: {e}")
        return

    player_deck = list(deck_data);  random.shuffle(player_deck)
    opp_deck    = list(deck_data);  random.shuffle(opp_deck)

    # Game objects
    # Player hand sits at the screen bottom; opponent hand sits at the top.
    # We pass a flipped anchor_y so the opponent fan mirrors the player's.
    player_hand  = Hand()
    player_field = []
    player_gy    = Graveyard()

    opp_hand     = Hand(anchor_y_override=OPPONENT_HAND_Y_THRESHOLD - 10, visible=False)
    opp_field    = []
    opp_gy       = Graveyard()

    # Camera
    zoom_level     = 1.0
    cam_x, cam_y   = 0.0, 0.0
    is_panning     = False
    selected_card  = None
    selected_owner = None           # "player" | "opponent"

    turn_number   = 1
    active_player = "player"

    # Life points — start at 8000 each (standard Yu-Gi-Oh)
    player_lp = 8000
    opp_lp    = 8000

    zones            = {}           # refreshed every frame
    export_flash     = 0            # countdown frames for the export feedback
    lp_edit_target   = None         # "player" | "opponent" | None
    lp_input_buffer  = ""           # typed digits while the LP editor is open

    HINTS = [
        "LMB drag: move card   |   RMB: cycle ATK / DEF / SET",
        "MMB drag: pan   |   Scroll: zoom   |   Tab: end turn",
        "F5: export JSON state   |   Del: send dragged card → GY",
    ]

    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()
        screen.fill(BG_COLOR)

        zones    = draw_field_zones(screen, zoom_level, (cam_x, cam_y), font)
        p_deck_z = zones.get("P_Deck")
        p_gy_z   = zones.get("P_GY")
        o_deck_z = zones.get("O_Deck")
        o_gy_z   = zones.get("O_GY")

        # Snap highlight while dragging
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
                # ── LP editor keyboard input ───────────────────────────────
                if lp_edit_target and lp_edit_target != "__commit__":
                    if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                        try:
                            val = int(lp_input_buffer) if lp_input_buffer else 0
                            if lp_edit_target == "player":
                                player_lp = max(0, val)
                            else:
                                opp_lp = max(0, val)
                        except ValueError:
                            pass
                        lp_edit_target  = None
                        lp_input_buffer = ""
                    elif event.key == pygame.K_ESCAPE:
                        lp_edit_target  = None
                        lp_input_buffer = ""
                    elif event.key == pygame.K_BACKSPACE:
                        lp_input_buffer = lp_input_buffer[:-1]
                    elif event.unicode.isdigit():
                        lp_input_buffer += event.unicode
                # ──────────────────────────────────────────────────────────
                elif event.key == pygame.K_TAB:
                    active_player = ("opponent" if active_player == "player"
                                     else "player")
                    if active_player == "player":
                        turn_number += 1

                    # Swap hand cards so each player sees their own cards
                    player_hand.cards, opp_hand.cards = (
                        opp_hand.cards, player_hand.cards)
                    # Wipe stale lerp state so cards don't fly from wrong pos
                    for c in player_hand.cards + opp_hand.cards:
                        for attr in ("lerp_x", "lerp_y", "target_x", "target_y",
                                     "target_draw_x", "target_draw_y"):
                            try:
                                delattr(c, attr)
                            except AttributeError:
                                pass
                    player_hand._reposition()
                    opp_hand._reposition()

                elif event.key == pygame.K_F5:
                    state = build_game_state(
                        player_hand, player_field, player_gy,
                        opp_hand,    opp_field,    opp_gy,
                        len(player_deck), len(opp_deck),
                        player_lp, opp_lp,
                        turn_number, active_player,
                    )
                    export_game_state(state)
                    export_flash = 120

                    # --- NEW CLIPBOARD CODE ---
                    # Convert the dictionary to a nicely formatted JSON string
                    state_string = json.dumps(state, indent=2)
                    # Send it to the clipboard
                    pyperclip.copy(state_string)

                elif event.key == pygame.K_DELETE and selected_card:
                    dest_gy = player_gy if selected_owner == "player" else opp_gy
                    for lst in (player_field, opp_field):
                        if selected_card in lst:
                            lst.remove(selected_card)
                    player_hand.remove_card(selected_card)
                    opp_hand.remove_card(selected_card)
                    dest_gy.add_card(selected_card)
                    selected_card = selected_owner = None

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # LP box click — open editor for the clicked side
                    lp_hit = lp_hit_test(event.pos, player_lp, opp_lp)
                    if lp_hit:
                        lp_edit_target  = lp_hit      # "player" or "opponent"
                        lp_input_buffer = ""
                    # Deck clicks
                    if p_deck_z and p_deck_z.collidepoint(event.pos) and player_deck:
                        try:
                            player_hand.add_card(load_card(player_deck.pop(), folder, back_img))
                        except Exception as e:
                            print(f"Card error: {e}")

                    elif o_deck_z and o_deck_z.collidepoint(event.pos) and opp_deck:
                        try:
                            opp_hand.add_card(load_card(opp_deck.pop(), folder, back_img))
                        except Exception as e:
                            print(f"Card error: {e}")

                    else:
                        # Hand picks (player first, then opponent)
                        picked = False
                        for hand_obj, owner in ((player_hand, "player"),
                                                 (opp_hand,   "opponent")):
                            c = hand_obj.check_click(event.pos)
                            if c:
                                c.is_dragging  = True
                                selected_card  = c
                                selected_owner = owner
                                hand_obj.remove_card(c)
                                picked = True
                                break

                        if not picked:
                            # Field picks
                            for lst, owner in ((player_field, "player"),
                                               (opp_field,   "opponent")):
                                hit = next((c for c in reversed(lst)
                                            if c.rect.collidepoint(event.pos)), None)
                                if hit:
                                    hit.is_dragging = True
                                    selected_card   = hit
                                    selected_owner  = owner
                                    hit.zone_name   = None
                                    lst.remove(hit)
                                    break

                elif event.button == 2:
                    is_panning = True

                elif event.button == 3:
                    target = None
                    for lst in (player_field, opp_field):
                        target = next((c for c in reversed(lst)
                                       if c.rect.collidepoint(event.pos)), None)
                        if target:
                            break
                    if not target:
                        target = (player_hand.check_click(event.pos) or
                                  opp_hand.check_click(event.pos))
                    if target:
                        target.toggle_position()

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    is_panning = False

                if selected_card and event.button == 1:
                    drop_pos = event.pos
                    drop_y   = drop_pos[1]

                    if selected_owner == "player" and drop_y > PLAYER_HAND_Y_THRESHOLD:
                        selected_card.zone_name = None
                        player_hand.add_card(selected_card, drop_x=drop_pos[0])

                    elif selected_owner == "opponent" and drop_y < OPPONENT_HAND_Y_THRESHOLD:
                        selected_card.zone_name = None
                        opp_hand.add_card(selected_card, drop_x=drop_pos[0])

                    else:
                        snapped, snap_rect = try_snap(selected_card, drop_pos, zones,
                                                      zoom_level, (cam_x, cam_y), selected_owner)
                        if not snapped:
                            selected_card.world_x   = (drop_pos[0] - cx) / zoom_level - cam_x
                            selected_card.world_y   = (drop_pos[1] - cy) / zoom_level - cam_y
                            selected_card.zone_name = None

                        dest = player_field if selected_owner == "player" else opp_field
                        selected_card.in_hand     = False
                        selected_card.angle       = 0
                        selected_card.is_dragging = False
                        selected_card.update_visuals(zoom_level)

                        if snapped:
                            selected_card.rect.center = snap_rect.center
                        reposition_field_card(selected_card, zoom_level, (cam_x, cam_y))

                        dest.append(selected_card)

                    selected_card = selected_owner = None

            elif event.type == pygame.MOUSEMOTION:
                if selected_card:
                    selected_card.rect.center = mouse_pos
                elif is_panning:
                    rx, ry = event.rel
                    cam_x += rx / zoom_level
                    cam_y += ry / zoom_level
                    reposition_all_field_cards(
                        player_field + opp_field, zoom_level, (cam_x, cam_y))

        # ── Draw: field cards ──────────────────────────────────────────────
        for c in player_field + opp_field:
            c.draw(screen)

        # ── Draw: field overlays (DEF outlines, hover highlight) ───────────
        draw_field_overlays(screen, zones, player_field, opp_field, mouse_pos)

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

        # ── Draw: HUD + LP editor ─────────────────────────────────────────
        if export_flash > 0:
            export_flash -= 1
        lp_edit_target, lp_input_buffer = draw_hud(
            screen, font, small_font,
            active_player, turn_number,
            player_deck, opp_deck,
            player_lp, opp_lp,
            export_flash, HINTS,
            lp_edit_target, lp_input_buffer,
            mouse_pos)

        pygame.display.flip()
        clock.tick(FPS)


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