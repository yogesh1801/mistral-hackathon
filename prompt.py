"""
Prompt templates for LLM battle in ASCII Tanks.
"""

def build_rules(symbol: str) -> str:
    """Build the system prompt, telling the LLM which tank it controls."""
    if symbol == "A":
        side = "LEFT"
        enemy = "B"
    else:
        side = "RIGHT"
        enemy = "A"

    enemy_direction = "RIGHT" if symbol == "A" else "LEFT"

    return f"""\
You are playing ASCII Tanks, a turn-based artillery game.
You are tank [{symbol}], located on the {side} side of the map.
Your enemy is tank [{enemy}], to your {enemy_direction}. Destroy them!

## Your Actions
Each turn you respond with a JSON object:
{{ "move": <int>, "angle": <int>, "power": <int> }}

- **move**: How many cells to move before firing (positive=right, negative=left).
  Each step costs 1 fuel. You cannot move more than your remaining fuel.
  If you request more move than your remaining fuel, you will **only move as many cells as you have fuel left**.
  Set to 0 if you don't want to move.
- **angle**: Firing angle in degrees (0 to 180). 0=flat right, 90=straight up, 180=flat left.
  Since you are on the {side} side, aim with angles {'< 90 to shoot right toward the enemy' if symbol == 'A' else '> 90 to shoot left toward the enemy'}.
- **power**: Firing power (0 to 100). Higher power = farther shot.

## Terrain
The battlefield is an 80-column wide field with hilly terrain made of █ blocks.
Tanks sit on top of the terrain as [A] or [B].
The + symbol marks the barrel nozzle — this is where your shot fires from.
A column ruler (0·····1·····2···...) is shown at the bottom. Use it to estimate how far away the enemy is.
Your tank is [{symbol}].

## Objective
Reduce [{enemy}]'s HP to 0. Shots that land near a tank deal damage based on proximity.
Craters form on impact, changing the terrain.

## Tips
- Adjust angle and power based on where your shot landed last turn.
- Moving can help you dodge or get a better firing position.
- You MUST always respond with valid JSON, nothing else.
"""

OUTPUT_FORMAT_HINT = 'Respond ONLY with a JSON object: { "move": <int>, "angle": <int>, "power": <int> }'


def build_state_prompt(stats: dict, compact_ascii: str, player_symbol: str, feedback: dict = None) -> str:
    """
    Build the user message for a turn.
    stats: dict from /api/stats with 'players' list and game info.
    compact_ascii: raw text from /api/ascii/compact.
    player_symbol: 'A' or 'B' — which tank this LLM controls.
    feedback: dict with last shot results (damage_taken, enemy_hit, shot_direction).
    """
    players = stats.get("players", [])
    me = next((p for p in players if p["symbol"] == player_symbol), None)
    enemy = next((p for p in players if p["symbol"] != player_symbol), None)

    lines = []

    # ── Last turn feedback ──
    if feedback:
        lines.append("=== LAST TURN RESULT ===")
        prev_angle = feedback.get("prev_angle", "?")
        prev_power = feedback.get("prev_power", "?")
        if feedback.get("enemy_hit"):
            lines.append(f"  ✓ HIT! You dealt {feedback.get('enemy_damage', 0)} damage (angle={prev_angle}, power={prev_power}).")
        else:
            direction = feedback.get("shot_direction", "unknown")
            lines.append(f"  ✗ MISS (angle={prev_angle}, power={prev_power}). Your shot landed {direction} the enemy.")
        dmg_taken = feedback.get("damage_taken", 0)
        if dmg_taken > 0:
            lines.append(f"  ⚠ You took {dmg_taken} damage from the enemy last turn.")
        lines.append("")

    # ── Current stats ──
    lines.append("=== YOUR TURN ===")
    if me:
        lines.append(f"You are [{me['symbol']}] {me['name']}")
        lines.append(f"  HP: {me['health']}  |  Angle: {me['angle']}  |  Power: {me['power']}  |  Fuel: {me['fuel']}")
    if enemy:
        lines.append(f"Enemy [{enemy['symbol']}] {enemy['name']}")
        lines.append(f"  HP: {enemy['health']}")
    lines.append("")
    lines.append("=== BATTLEFIELD ===")
    lines.append(compact_ascii)
    lines.append("")
    lines.append(OUTPUT_FORMAT_HINT)

    return "\n".join(lines)
