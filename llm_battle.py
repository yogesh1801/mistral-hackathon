#!/usr/bin/env python3
"""
LLM Battle — Mistral Small vs Ministral 3B fight each other in ASCII Tanks.

Usage:
    python3 llm_battle.py --matches 3 --turns 20
    (server.py must be running on localhost:3001)
"""

import os
import sys
import csv
import json
import argparse
import requests
from mistralai import Mistral
from loguru import logger

from prompt import build_rules, build_state_prompt

# ── Model / Player mapping ──────────────────────────
PLAYERS = [
    {"name": "Ministral 3B", "symbol": "A", "model": "ministral-3b-latest"},
    {"name": "Mistral Small", "symbol": "B", "model": "mistral-small-latest"},
]

CSV_FILE = "results.csv"
CSV_COLUMNS = [
    "match_number", "turns", "winner",
    f"health_{PLAYERS[0]['name'].replace(' ', '_')}",
    f"health_{PLAYERS[1]['name'].replace(' ', '_')}",
    "result",
]


def get_compact_state(server: str) -> str:
    """Fetch compact ASCII state from the game server."""
    resp = requests.get(f"{server}/api/ascii/compact", timeout=10)
    resp.raise_for_status()
    return resp.text


def get_stats(server: str) -> dict:
    """Fetch current game stats as JSON from the game server."""
    resp = requests.get(f"{server}/api/stats", timeout=10)
    resp.raise_for_status()
    return resp.json()


def fire(server: str, move: int, angle: int, power: int) -> dict:
    """Send the unified fire action to the game server."""
    resp = requests.post(
        f"{server}/api/fire",
        json={"move": move, "angle": angle, "power": power},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def reset_game(server: str) -> dict:
    """Reset the game to initial state."""
    resp = requests.post(f"{server}/api/reset", timeout=10)
    resp.raise_for_status()
    return resp.json()


def call_llm(client: Mistral, model: str, messages: list) -> dict:
    """Call Mistral API and parse JSON response."""
    chat_response = client.chat.complete(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    raw = chat_response.choices[0].message.content
    logger.debug("Raw LLM response: {}", raw)
    return json.loads(raw)


def clamp(val, lo, hi):
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, val))


def run_match(
    client: Mistral,
    match_num: int,
    max_turns: int,
    server: str,
    csv_writer,
):
    """Run a single match between the two models."""
    logger.info("═══ Match {} starting ═══", match_num)
    reset_game(server)

    # Each player gets a fresh conversation history per match
    conversations = [
        [{"role": "system", "content": build_rules("A")}],  # Player A
        [{"role": "system", "content": build_rules("B")}],  # Player B
    ]

    result = "draw"

    # Per-player feedback from their last shot
    # Keys: enemy_hit, enemy_damage, shot_direction, damage_taken
    last_feedback = [None, None]  # [Player A feedback, Player B feedback]

    for turn in range(1, max_turns + 1):
        # Fetch current stats and ASCII state
        stats = get_stats(server)
        state_text = get_compact_state(server)

        # Determine current player from stats
        pid = stats.get("currentPlayer", (turn - 1) % 2)

        player = PLAYERS[pid]
        model = player["model"]
        conv = conversations[pid]

        logger.info(
            "Match {} | Turn {} | {} ({}) thinking...",
            match_num, turn, player["name"], model,
        )

        # Build state prompt with stats + feedback and add to conversation
        user_msg = build_state_prompt(stats, state_text, player["symbol"], feedback=last_feedback[pid])
        logger.debug("Prompt to {}:\n{}", player["name"], user_msg)
        conv.append({"role": "user", "content": user_msg})

        # Call LLM
        try:
            action = call_llm(client, model, conv)
        except Exception as e:
            logger.error("LLM call failed: {}", e)
            # Default safe action
            action = {"move": 0, "angle": 45 if pid == 0 else 135, "power": 50}

        # Sanitize values
        move = int(action.get("move", 0))
        angle = clamp(int(action.get("angle", 90)), 0, 180)
        power = clamp(int(action.get("power", 50)), 0, 100)

        logger.info(
            "  → move={}, angle={}, power={}",
            move, angle, power,
        )

        # Append assistant response to conversation history
        conv.append({"role": "assistant", "content": json.dumps(action)})

        # Fire
        try:
            fire_result = fire(server, move, angle, power)
        except Exception as e:
            logger.error("Fire API failed: {}", e)
            fire_result = {"ok": False, "gameOver": False, "players": [], "message": str(e)}

        # Extract health and build feedback
        players_state = fire_result.get("players", [])
        health_a = players_state[0]["health"] if len(players_state) > 0 else "?"
        health_b = players_state[1]["health"] if len(players_state) > 1 else "?"
        game_over = fire_result.get("gameOver", False)
        state = "over" if game_over else "running"

        # Build feedback for this player's next turn
        enemy_pid = 1 - pid
        enemy_damage = 0
        enemy_hit = False
        if len(players_state) > enemy_pid:
            enemy_damage = players_state[enemy_pid].get("damage_taken", 0)
            enemy_hit = enemy_damage > 0

        # Determine if shot landed short or past the enemy
        impact_x = fire_result.get("impact_x")
        shot_direction = "unknown"
        if impact_x is not None and len(players_state) > enemy_pid:
            enemy_x = players_state[enemy_pid].get("x", 0)
            my_x = players_state[pid].get("x", 0)
            if my_x < enemy_x:
                # Player is LEFT of enemy
                shot_direction = "short of" if impact_x < enemy_x else "past"
            else:
                # Player is RIGHT of enemy
                shot_direction = "short of" if impact_x > enemy_x else "past"

        # Damage taken by this player from enemy's last shot
        my_damage_taken = players_state[pid].get("damage_taken", 0) if len(players_state) > pid else 0

        last_feedback[pid] = {
            "enemy_hit": enemy_hit,
            "enemy_damage": enemy_damage,
            "shot_direction": shot_direction,
            "damage_taken": my_damage_taken,
            "prev_angle": angle,
            "prev_power": power,
        }

        if enemy_hit:
            logger.info("  ✓ HIT! Dealt {} damage", enemy_damage)
        else:
            logger.info("  ✗ MISS — shot landed {} the enemy", shot_direction)

        # Log damage
        for ps in players_state:
            dmg = ps.get("damage_taken", 0)
            if dmg > 0:
                logger.info("  💥 {} took {} damage → HP {}", ps["name"], dmg, ps["health"])

        if game_over:
            msg = fire_result.get("message", "")
            if PLAYERS[0]["name"] in msg and "Wins" in msg:
                result = PLAYERS[0]["name"]
            elif PLAYERS[1]["name"] in msg and "Wins" in msg:
                result = PLAYERS[1]["name"]
            else:
                result = "draw"
        else:
            result = ""


        if game_over:
            logger.info("🏆 Match {} over: {}", match_num, fire_result.get("message", result))
            csv_writer.writerow([match_num, turn, result, health_a, health_b, result])
            return result

    # Turn limit reached — player with more HP wins
    stats = get_stats(server)
    players_info = stats.get("players", [])
    hp_a = players_info[0]["health"] if len(players_info) > 0 else 0
    hp_b = players_info[1]["health"] if len(players_info) > 1 else 0

    if hp_a > hp_b:
        result = PLAYERS[0]["name"]
    elif hp_b > hp_a:
        result = PLAYERS[1]["name"]
    else:
        result = "draw"

    logger.info("⏱ Match {} ended by turn limit | HP: {} {} vs {} {} → {}",
                match_num, PLAYERS[0]["name"], hp_a, PLAYERS[1]["name"], hp_b, result)
    csv_writer.writerow([match_num, max_turns, result, hp_a, hp_b, result])
    return result


def main():
    parser = argparse.ArgumentParser(description="LLM Battle for ASCII Tanks")
    parser.add_argument("--matches", type=int, default=1, help="Number of matches to play")
    parser.add_argument("--turns", type=int, default=20, help="Max turns per match")
    parser.add_argument("--server", type=str, default="http://localhost:3001", help="Game server URL")
    args = parser.parse_args()

    # Configure loguru
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
    logger.add("battle.log", level="DEBUG", rotation="5 MB")

    # Mistral client
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY environment variable not set!")
        sys.exit(1)
    client = Mistral(api_key=api_key)

    # Summary tracking
    wins = {PLAYERS[0]["name"]: 0, PLAYERS[1]["name"]: 0, "draw": 0}

    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)

        for match_num in range(1, args.matches + 1):
            winner = run_match(client, match_num, args.turns, args.server, writer)
            if winner in wins:
                wins[winner] += 1
            else:
                wins["draw"] += 1
            f.flush()

    # Print summary
    logger.info("═══════════════════════════════════")
    logger.info("Final Results after {} matches:", args.matches)
    for name, count in wins.items():
        logger.info("  {}: {} wins", name, count)
    logger.info("═══════════════════════════════════")


if __name__ == "__main__":
    main()
