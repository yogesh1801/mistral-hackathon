#!/usr/bin/env python3
"""
ASCII Tanks — Python Edition
A terminal-based artillery game with ANSI colors and parrot.live-style streaming.

Usage:
    python server.py
    curl -N localhost:3001/stream        # Watch the game live
    curl -X POST localhost:3001/api/fire # Fire a shot
"""

import math
import json
import time
import random
import threading
import csv
import os
import re
from flask import Flask, request, jsonify, Response

# ═══════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════

SCREEN_WIDTH = 80
SCREEN_HEIGHT = 30
GRAVITY = 9.8
EXPLOSION_RADIUS = 4
TICK_RATE = 0.2        # 5 fps
DT = 0.5               # Physics step per tick (fast projectiles)
SUB_STEPS = 8
PORT = 3001

# ═══════════════════════════════════════════════════
#  ANSI COLOR HELPERS
# ═══════════════════════════════════════════════════

RESET = "\033[0m"
BOLD = "\033[1m"
CLEAR_SCREEN = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"

def fg256(n):
    """256-color foreground."""
    return f"\033[38;5;{n}m"

def bg256(n):
    """256-color background."""
    return f"\033[48;5;{n}m"

# Named colors
C_BORDER     = fg256(240)
C_SKY_BG     = bg256(0)    # Black background for sky
C_STAR       = fg256(245) + bg256(0)
C_P1         = fg256(46)   # Bright green
C_P1_DIM     = fg256(34)
C_P2         = fg256(201)  # Bright magenta
C_P2_DIM     = fg256(165)  # Dim magenta
C_BARREL     = fg256(255)  # White
C_PROJECTILE = f"{BOLD}{fg256(255)}"
C_TERRAIN_TOP    = fg256(34)   # Green
C_TERRAIN_MID    = fg256(28)
C_TERRAIN_BOTTOM = fg256(22)   # Dark green
C_EXPL_HOT   = fg256(226)  # Yellow
C_EXPL_MED   = fg256(208)  # Orange
C_EXPL_COOL  = fg256(196)  # Red
C_SKY        = fg256(17)   # Dark blue background
C_STATUS     = fg256(229)   # Light yellow
C_STATUS_HP  = fg256(46)
C_STATUS_HP2 = fg256(201)
C_MSG        = fg256(51)    # Cyan


# ═══════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════

class Player:
    def __init__(self, pid, name, x, y, symbol, color, color_dim):
        self.id = pid
        self.name = name
        self.x = x
        self.y = y
        self.angle = 45 if pid == 0 else 135
        self.power = 50
        self.health = 100
        self.symbol = symbol
        self.color = color
        self.color_dim = color_dim
        self.fuel = 20

class Projectile:
    def __init__(self, x, y, vx, vy, owner_id, radius=EXPLOSION_RADIUS, damage=50):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.active = True
        self.owner_id = owner_id
        self.radius = radius
        self.damage = damage

class Particle:
    def __init__(self, x, y, vx, vy, life=1.0, char='*'):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.char = char


# ═══════════════════════════════════════════════════
#  TERRAIN GENERATION (stair-step style)
# ═══════════════════════════════════════════════════

def generate_terrain():
    """Generate rolling-hill terrain as a heightmap (integer y per x column)."""
    terrain = []
    frequency = 0.05
    amplitude = 10
    noise_freq = 0.2
    noise_amp = 2

    # Add random offsets so each game has unique terrain
    phase1 = random.uniform(0, math.pi * 2)
    phase2 = random.uniform(0, math.pi * 2)

    for x in range(SCREEN_WIDTH):
        base = math.sin(x * frequency + phase1) * amplitude
        noise = math.sin(x * noise_freq * 3.7 + phase2) * noise_amp

        height = int(SCREEN_HEIGHT - (SCREEN_HEIGHT / 3 + base + noise))
        height = max(10, min(SCREEN_HEIGHT - 2, height))
        terrain.append(height)

    return terrain


def flatten_terrain(terrain, cx, radius):
    """Create a crater centered at cx with given radius."""
    new_terrain = terrain[:]
    for i in range(cx - radius, cx + radius + 1):
        if 0 <= i < SCREEN_WIDTH:
            dist = abs(i - cx)
            depth = math.sqrt(max(0, radius * radius - dist * dist))
            new_terrain[i] = min(SCREEN_HEIGHT - 1, int(new_terrain[i] + depth))
    return new_terrain


# ═══════════════════════════════════════════════════
#  PHYSICS
# ═══════════════════════════════════════════════════

def update_projectile(p, dt):
    """Advance projectile by one physics step."""
    p.x += p.vx * dt
    p.y += p.vy * dt
    p.vy += (GRAVITY * 0.5) * dt


def check_collision(x, y, terrain):
    """Check if position (x,y) has hit the ground or gone out of bounds."""
    if x < 0 or x >= SCREEN_WIDTH or y >= SCREEN_HEIGHT:
        return True
    if y < 0:
        return False
    ix = int(x)
    if ix < 0 or ix >= SCREEN_WIDTH:
        return True
    return y >= terrain[ix]


# ═══════════════════════════════════════════════════
#  RENDERER (ANSI colored output)
# ═══════════════════════════════════════════════════

def terrain_color(y, surface_y):
    """Pick terrain color based on depth from surface."""
    depth = y - surface_y
    if depth <= 0:
        return C_TERRAIN_TOP
    elif depth <= 3:
        return C_TERRAIN_MID
    else:
        return C_TERRAIN_BOTTOM


def render_frame(game):
    """Render the full game frame as a list of ANSI-colored strings."""
    # Build a 2D buffer: each cell is (char, color_string)
    buf = [[(' ', C_SKY_BG) for _ in range(SCREEN_WIDTH)] for _ in range(SCREEN_HEIGHT)]

    def put(x, y, ch, color=''):
        if 0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT:
            buf[y][x] = (ch, color)

    # ── Stars ──
    for star in game['stars']:
        put(star[0], star[1], '.', C_STAR)

    # ── Border ──
    for x in range(SCREEN_WIDTH):
        put(x, 0, '─', C_BORDER)
        put(x, SCREEN_HEIGHT - 1, '─', C_BORDER)
    for y in range(SCREEN_HEIGHT):
        put(0, y, '│', C_BORDER)
        put(SCREEN_WIDTH - 1, y, '│', C_BORDER)
    put(0, 0, '┌', C_BORDER)
    put(SCREEN_WIDTH - 1, 0, '┐', C_BORDER)
    put(0, SCREEN_HEIGHT - 1, '└', C_BORDER)
    put(SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, '┘', C_BORDER)

    # ── Terrain (stair blocks) ──
    terrain = game['terrain']
    for x in range(SCREEN_WIDTH):
        surface = terrain[x]
        for y in range(surface, SCREEN_HEIGHT):
            color = terrain_color(y, surface)
            put(x, y, '█', color)

    # ── Tanks ──
    for i, player in enumerate(game['players']):
        px = int(player.x)
        py = int(player.y)
        is_active = game['current_player'] == i
        color = player.color if is_active else player.color_dim

        # Tank body: [A] or [B]
        put(px - 1, py, '[', color)
        put(px, py, player.symbol, color)
        put(px + 1, py, ']', color)

        # Barrel nozzle
        rad = player.angle * math.pi / 180
        bx = round(px + math.cos(rad) * 2)
        by = round((py - 1) - math.sin(rad) * 2)
        put(bx, by, '+', C_BARREL)

    # ── Projectiles ──
    for p in game['projectiles']:
        put(int(p.x), int(p.y), 'o', C_PROJECTILE)

    # ── Particles ──
    for p in game['particles']:
        if p.life > 0.7:
            ch, color = '*', C_EXPL_HOT
        elif p.life > 0.4:
            ch, color = '·', C_EXPL_MED
        else:
            ch, color = '.', C_EXPL_COOL
        put(int(p.x), int(p.y), ch, color)

    # ── Assemble lines ──
    lines = []
    for row in buf:
        parts = []
        for ch, color in row:
            if color:
                parts.append(f"{color}{ch}{RESET}")
            else:
                parts.append(ch)
        lines.append(''.join(parts))

    return lines


def render_status(game):
    """Render the status bar lines with colors."""
    p1 = game['players'][0]
    p2 = game['players'][1]

    msg_line = f"{C_MSG}--- {game['message']} ---{RESET}"

    hp1_color = C_STATUS_HP if p1.health > 30 else C_EXPL_COOL
    hp2_color = C_STATUS_HP2 if p2.health > 30 else C_EXPL_COOL

    stats_p1 = (
        f"{C_P1}{p1.name} ({p1.symbol}){RESET}: "
        f"hp:{hp1_color}{p1.health}{RESET}  "
        f"ang:{C_STATUS}{p1.angle}{RESET}  "
        f"pow:{C_STATUS}{p1.power}{RESET}  "
        f"fuel:{C_STATUS}{p1.fuel}{RESET}"
    )

    stats_p2 = (
        f"{C_P2}{p2.name} ({p2.symbol}){RESET}: "
        f"hp:{hp2_color}{p2.health}{RESET}  "
        f"ang:{C_STATUS}{p2.angle}{RESET}  "
        f"pow:{C_STATUS}{p2.power}{RESET}  "
        f"fuel:{C_STATUS}{p2.fuel}{RESET}"
    )

    return [msg_line, stats_p1, stats_p2]


def render_compact_game(game):
    """Render a minimal, token-efficient ASCII frame without colors, borders, or stars, and right-trimmed."""
    min_y = SCREEN_HEIGHT - 1
    for x in range(SCREEN_WIDTH):
        min_y = min(min_y, game['terrain'][x])
    for p in game['players']:
        min_y = min(min_y, int(p.y) - 1)
    for p in game['projectiles']:
        min_y = min(min_y, int(p.y))
    min_y = max(0, min_y - 2)

    buf = [[' ' for _ in range(SCREEN_WIDTH)] for _ in range(SCREEN_HEIGHT)]
    def put(x, y, ch):
        if 0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT:
            buf[y][x] = ch

    for x in range(SCREEN_WIDTH):
        surf = game['terrain'][x]
        for y in range(surf, SCREEN_HEIGHT):
            put(x, y, '█')

    for player in game['players']:
        px, py = int(player.x), int(player.y)
        put(px - 1, py, '[')
        put(px, py, player.symbol)
        put(px + 1, py, ']')
        rad = player.angle * math.pi / 180
        put(round(px + math.cos(rad) * 2), round((py - 1) - math.sin(rad) * 2), '+')

    for p in game['projectiles']:
        put(int(p.x), int(p.y), 'o')

    lines = []
    for y in range(min_y, SCREEN_HEIGHT):
        lines.append(''.join(buf[y]).rstrip())

    # Add column ruler for spatial reference
    ruler = ''.join(str(x // 10) if x % 10 == 0 else '·' for x in range(SCREEN_WIDTH))
    lines.append(ruler.rstrip())

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════
#  GAME STATE MANAGEMENT
# ═══════════════════════════════════════════════════

def create_initial_state():
    terrain = generate_terrain()

    p1_x = 10
    p2_x = SCREEN_WIDTH - 10

    players = [
        Player(0, 'Ministral 3B', p1_x, terrain[p1_x] - 1, 'A', C_P1, C_P1_DIM),
        Player(1, 'Mistral Small', p2_x, terrain[p2_x] - 1, 'B', C_P2, C_P2_DIM),
    ]

    stars = [
        (random.randint(1, SCREEN_WIDTH - 2), random.randint(1, SCREEN_HEIGHT // 3))
        for _ in range(30)
    ]

    return {
        'terrain': terrain,
        'players': players,
        'current_player': 0,
        'projectiles': [],
        'particles': [],
        'stars': stars,
        'message': f"{players[0].name}'s Turn | angle/power/move/fire",
        'game_over': False,
        'wind': 0,
        'last_impact_x': None,
    }


# Global game state + lock
game_lock = threading.Lock()
game = create_initial_state()


# ═══════════════════════════════════════════════════
#  GAME LOOP (background thread)
# ═══════════════════════════════════════════════════

def tick():
    """One game-loop tick: update physics, particles, gravity."""
    global game

    with game_lock:
        if game['game_over']:
            return

        # ── Update projectiles ──
        if game['projectiles']:
            sub_dt = DT / SUB_STEPS
            still_active = []

            for proj in game['projectiles']:
                if not proj.active:
                    continue

                alive = True
                for _ in range(SUB_STEPS):
                    update_projectile(proj, sub_dt)

                    if check_collision(proj.x, proj.y, game['terrain']):
                        proj.active = False
                        alive = False
                        hit_x = int(proj.x)
                        game['last_impact_x'] = hit_x

                        # Crater
                        game['terrain'] = flatten_terrain(
                            game['terrain'], hit_x, proj.radius
                        )

                        # Damage players
                        for pl in game['players']:
                            dist = math.sqrt(
                                (pl.x - hit_x) ** 2 + (pl.y - proj.y) ** 2
                            )
                            impact_r = proj.radius + 2
                            if dist < impact_r:
                                dmg = int((1 - dist / impact_r) * proj.damage)
                                pl.health = max(0, pl.health - dmg)

                        break

                if alive:
                    still_active.append(proj)

            game['projectiles'] = still_active

            # Check win / turn change
            dead = None
            for pl in game['players']:
                if pl.health <= 0:
                    dead = pl
                    break

            if dead:
                game['game_over'] = True
                winner = game['players'][1].name if dead.id == 0 else game['players'][0].name
                game['message'] = f"GAME OVER! {winner} Wins!"
                game['projectiles'] = []
            elif not game['projectiles']:
                game['current_player'] = (game['current_player'] + 1) % 2
                cur = game['players'][game['current_player']]
                game['message'] = f"{cur.name}'s Turn | A:{cur.angle} P:{cur.power}"

        # ── Update particles ──
        alive_particles = []
        for p in game['particles']:
            p.x += p.vx
            p.y += p.vy
            p.life -= 0.1
            if p.life > 0:
                alive_particles.append(p)
        game['particles'] = alive_particles

        # ── Player gravity ──
        for pl in game['players']:
            ix = int(pl.x)
            if 0 <= ix < SCREEN_WIDTH:
                ground = game['terrain'][ix]
                target = ground - 1
                if pl.y < target:
                    pl.y = min(target, pl.y + 1)
                elif pl.y > target:
                    pl.y = target


def game_loop():
    """Run the game tick on a background thread."""
    while True:
        tick()
        time.sleep(TICK_RATE)


# Start the background game loop
t = threading.Thread(target=game_loop, daemon=True)
t.start()


# ═══════════════════════════════════════════════════
#  RESULTS TABLE RENDERING
# ═══════════════════════════════════════════════════

def read_results_csv():
    """Read the results.csv file and return list of rows."""
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, 'results.csv')
    
    if not os.path.exists(csv_path):
        return []
    
    rows = []
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except:
        pass
    return rows


def render_results_table():
    """Render a full-width detailed results table as ASCII lines."""
    results = read_results_csv()
    lines = []
    
    # Full-width table with all details - column widths: 7, 8, 18, 14, 14
    header_line = (
        f"{C_STATUS}┌───────┬────────┬──────────────────┬──────────────┬──────────────┐{RESET}"
    )
    lines.append(header_line)
    
    # Column headers - full form
    header_text = (
        f"{C_STATUS}│ Match │  Turns │     Winner       │Ministral 3B  │Mistral Small │{RESET}"
    )
    lines.append(header_text)
    
    # HP label row
    hp_header = (
        f"{C_STATUS}│       │        │                  │      HP      │      HP      │{RESET}"
    )
    lines.append(hp_header)
    
    # Separator
    sep_line = (
        f"{C_STATUS}├───────┼────────┼──────────────────┼──────────────┼──────────────┤{RESET}"
    )
    lines.append(sep_line)
    
    # Data rows (show last 25 completed matches)
    for row in results[-25:]:
        match_num = row.get('match_number', '-')
        turns = row.get('turns', '-')
        winner = row.get('winner', '-')
        health_a = row.get('health_Ministral_3B', '-')
        health_b = row.get('health_Mistral_Small', '-')
        result = row.get('result', '-')
        
        # Format winner with full name - exactly 18 chars for column
        if winner:
            if 'Ministral' in winner or 'Ministral 3B' in winner:
                winner_display = 'Mistral 3B'
                winner_color = C_P1
            elif 'Mistral Small' in winner or ('Mistral' in winner and 'Small' not in winner):
                winner_display = 'Mistral Smll'
                winner_color = C_P2
            elif winner == 'draw':
                winner_display = 'draw'
                winner_color = ''
            else:
                winner_display = winner[:18]
                winner_color = ''
        else:
            winner_display = '-'
            winner_color = ''
        
        # Color the winner name - pad to exactly 18 chars
        if winner_color:
            winner_colored = f"{winner_color}{winner_display:<18}{RESET}"
        else:
            winner_colored = f"{winner_display:<18}"
        
        # Format health values with color - exactly 14 chars per column
        try:
            hp_a_val = int(health_a) if health_a != '-' else -1
            hp_b_val = int(health_b) if health_b != '-' else -1
            hp_a_str = f"{hp_a_val:>3}" if hp_a_val >= 0 else '  -'
            hp_b_str = f"{hp_b_val:>3}" if hp_b_val >= 0 else '  -'
        except (ValueError, TypeError):
            hp_a_str = str(health_a)[:3] if health_a != '-' else '  -'
            hp_b_str = str(health_b)[:3] if health_b != '-' else '  -'
        
        # Color HP values based on health level
        if hp_a_val >= 0:
            if hp_a_val > 60:
                hp_a_colored = f"{C_P1}{hp_a_str}{RESET}"
            elif hp_a_val > 30:
                hp_a_colored = f"{fg256(208)}{hp_a_str}{RESET}"
            else:
                hp_a_colored = f"{C_EXPL_COOL}{hp_a_str}{RESET}"
        else:
            hp_a_colored = hp_a_str
        
        # Hardcode exactly 14 visible columns (6 spaces left, 3 char text, 5 spaces right)
        hp_a_padded = f"      {hp_a_colored}     "
        
        if hp_b_val >= 0:
            if hp_b_val > 60:
                hp_b_colored = f"{C_P2}{hp_b_str}{RESET}"
            elif hp_b_val > 30:
                hp_b_colored = f"{fg256(208)}{hp_b_str}{RESET}"
            else:
                hp_b_colored = f"{C_EXPL_COOL}{hp_b_str}{RESET}"
        else:
            hp_b_colored = hp_b_str
            
        hp_b_padded = f"      {hp_b_colored}     "
        
        # Build row with exact column alignment (7, 8, 18, 14, 14) - colorful
        row_line = (
            f"{C_STATUS}│{RESET}{fg256(51)}{str(match_num):>7}{RESET}{C_STATUS}│{RESET}{fg256(226)}{str(turns):>8}{RESET}"
            f"{C_STATUS}│{RESET}{winner_colored}{C_STATUS}│{RESET}{hp_a_padded}"
            f"{C_STATUS}│{RESET}{hp_b_padded}{C_STATUS}│{RESET}"
        )
        lines.append(row_line)
    
    # Bottom border
    bottom_line = (
        f"{C_STATUS}└───────┴────────┴──────────────────┴──────────────┴──────────────┘{RESET}"
    )
    lines.append(bottom_line)
    
    # Add a small header above the table
    header_info = f"{C_MSG}📊 LIVE MATCH RESULTS{RESET}"
    lines.insert(0, header_info)
    lines.insert(1, '')
    
    return lines


# ═══════════════════════════════════════════════════
#  FLASK APP
# ═══════════════════════════════════════════════════

app = Flask(__name__)


@app.route('/stream')
def stream():
    """
    parrot.live-style streaming endpoint with live results table.
    Usage: curl -N localhost:3001/stream
    Continuously streams ANSI-colored game frames with results table below.
    """
    def generate():
        yield HIDE_CURSOR
        while True:
            with game_lock:
                frame_lines = render_frame(game)
                status_lines = render_status(game)
            
            # Get results table
            results_lines = render_results_table()

            # Build the full frame with clear screen
            frame = CLEAR_SCREEN

            # Helper function to strip ANSI codes for length calculation
            def strip_ansi(text):
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                return ansi_escape.sub('', text)
            
            # Combine status lines and game frame lines
            all_game_lines = status_lines + frame_lines
            
            # Calculate max lines needed
            max_lines = max(len(all_game_lines), len(results_lines))
            
            # Build side-by-side layout
            for i in range(max_lines):
                # Left side: game frame
                if i < len(all_game_lines):
                    game_line = all_game_lines[i].rstrip('\n')
                    # Pad game line to SCREEN_WIDTH (accounting for ANSI codes)
                    visible_length = len(strip_ansi(game_line))
                    padding_needed = SCREEN_WIDTH - visible_length
                    game_line_padded = game_line + (' ' * padding_needed)
                else:
                    game_line_padded = ' ' * SCREEN_WIDTH
                
                # Right side: results table
                if i < len(results_lines):
                    table_line = results_lines[i].rstrip('\n')
                else:
                    table_line = ''
                
                # Add separator between game and table
                separator = f" {C_STATUS}│{RESET} "
                frame += game_line_padded + separator + table_line + '\n'
            
            yield frame
            time.sleep(TICK_RATE)

    return Response(
        generate(),
        mimetype='text/plain; charset=utf-8',
        headers={
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-cache',
            'Transfer-Encoding': 'chunked',
        }
    )


@app.route('/api/ascii/compact')
def api_ascii_compact():
    """Compact text state and frame for LLMs."""
    with game_lock:
        compact_frame = render_compact_game(game)
    return Response(compact_frame, mimetype='text/plain')


@app.route('/api/fire', methods=['POST'])
def api_fire():
    """
    Unified action endpoint.
    Accepts JSON: { "move": int, "angle": int, "power": int }
    - move:  number of cells to move (positive=right, negative=left).
             Capped by remaining fuel. Cannot exceed bounds or steep terrain.
    - angle: firing angle in degrees (0–180). Set directly (not a delta).
    - power: firing power (0–100). Set directly (not a delta).
    All three are optional; omitted fields keep the current value.
    After applying move/angle/power, a projectile is fired automatically.
    """
    global game

    with game_lock:
        if game['game_over']:
            return jsonify({'error': 'Game over. POST /api/reset'}), 400
        if game['projectiles']:
            return jsonify({'error': 'Projectile already in flight'}), 400

        data = request.get_json(silent=True) or {}
        player = game['players'][game['current_player']]
        errors = []

        # ── Validate angle ──
        if 'angle' in data:
            angle_val = data['angle']
            if not isinstance(angle_val, (int, float)):
                errors.append('angle must be a number')
            elif angle_val < 0 or angle_val > 180:
                errors.append('angle must be between 0 and 180')

        # ── Validate power ──
        if 'power' in data:
            power_val = data['power']
            if not isinstance(power_val, (int, float)):
                errors.append('power must be a number')
            elif power_val < 0 or power_val > 100:
                errors.append('power must be between 0 and 100')

        # ── Validate move ──
        if 'move' in data:
            move_val = data['move']
            if not isinstance(move_val, (int, float)):
                errors.append('move must be a number')
            else:
                move_val = int(move_val)

                # Ensure fuel is never treated as negative
                if player.fuel < 0:
                    player.fuel = 0

                # Clamp requested move to available fuel (by magnitude)
                max_steps = player.fuel
                if abs(move_val) > max_steps:
                    move_val = max_steps if move_val > 0 else -max_steps

        if errors:
            return jsonify({'error': '; '.join(errors)}), 400

        # ── Apply move (step-by-step to respect terrain and fuel) ──
        if 'move' in data:
            direction = 1 if move_val > 0 else -1
            steps = abs(move_val)
            moved = 0
            for _ in range(steps):
                # Out of fuel: stop moving before fuel can go negative
                if player.fuel <= 0:
                    errors.append(f'out of fuel after {moved} steps')
                    break
                new_x = player.x + direction
                if new_x < 3 or new_x >= SCREEN_WIDTH - 3:
                    errors.append(f'hit boundary after {moved} steps')
                    break
                new_y = game['terrain'][int(new_x)] - 1
                old_y = game['terrain'][int(player.x)] - 1
                if old_y - new_y > 2:
                    errors.append(f'terrain too steep after {moved} steps')
                    break
                player.x = new_x
                player.y = new_y
                player.fuel -= 1
                moved += 1

        # ── Apply angle ──
        if 'angle' in data:
            player.angle = int(data['angle'])

        # ── Apply power ──
        if 'power' in data:
            player.power = int(data['power'])

        # ── Fire ──
        rad = player.angle * math.pi / 180
        power = player.power / 4

        spawn_x = player.x + math.cos(rad) * 2
        spawn_y = (player.y - 1) - math.sin(rad) * 2

        health_before = [p.health for p in game['players']]

        game['projectiles'].append(Projectile(
            spawn_x, spawn_y,
            math.cos(rad) * power,
            -math.sin(rad) * power,
            player.id,
        ))
        game['message'] = f"{player.name} fired!"

    # Wait for projectile to resolve
    for _ in range(100):
        time.sleep(0.2)
        with game_lock:
            if not game['projectiles']:
                result = {
                    'ok': True,
                    'firedBy': player.name,
                    'angle': player.angle,
                    'power': player.power,
                    'move': data.get('move', 0),
                    'warnings': errors if errors else None,
                    'impact_x': game.get('last_impact_x'),
                    'turn': game['players'][game['current_player']].name,
                    'players': [
                        {
                            'name': p.name,
                            'health': p.health,
                            'damage_taken': health_before[i] - p.health,
                            'x': int(p.x),
                        }
                        for i, p in enumerate(game['players'])
                    ],
                    'gameOver': game['game_over'],
                    'message': game['message'],
                }
                return jsonify(result)

    return jsonify({'error': 'Timeout waiting for projectile'}), 500


@app.route('/api/stats')
def api_stats():
    """Current game stats as JSON (for LLM battle clients)."""
    with game_lock:
        cur = game['players'][game['current_player']]
        return jsonify({
            'turn': cur.name,
            'currentPlayer': game['current_player'],
            'message': game['message'],
            'gameOver': game['game_over'],
            'players': [
                {
                    'name': p.name, 'symbol': p.symbol, 'health': p.health,
                    'x': int(p.x), 'y': int(p.y),
                    'angle': p.angle, 'power': p.power, 'fuel': p.fuel,
                }
                for p in game['players']
            ],
            'terrain': game['terrain']
        })


@app.route('/api/reset', methods=['POST'])
def api_reset():
    """Reset the game to initial state."""
    global game
    with game_lock:
        game = create_initial_state()
    return jsonify({'ok': True, 'message': 'Game reset'})


# ═══════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    banner = f"""
{fg256(46)}╔══════════════════════════════════════════════════════════╗
║{fg256(226)}  🎮  ASCII TANKS — Python Edition                        {fg256(46)}║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║{fg256(51)}  WATCH GAME:{RESET}                                             {fg256(46)}║
║{fg256(255)}    curl -N localhost:{PORT}/stream{RESET}                         {fg256(46)}║
║                                                          ║
║{fg256(51)}  FIRE (unified action):{RESET}                                   {fg256(46)}║
║{fg256(240)}    curl -X POST localhost:{PORT}/api/fire \\{RESET}                {fg256(46)}║
║{fg256(240)}      -H 'Content-Type: application/json' \\{RESET}               {fg256(46)}║
║{fg256(240)}      -d '{{"move":3,"angle":60,"power":80}}'{RESET}               {fg256(46)}║
║                                                          ║
║{fg256(51)}  OTHER:{RESET}                                                   {fg256(46)}║
║{fg256(240)}    curl localhost:{PORT}/api/ascii/compact{RESET}                 {fg256(46)}║
║{fg256(240)}    curl -X POST localhost:{PORT}/api/reset{RESET}                 {fg256(46)}║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{RESET}
"""
    print(banner)
    app.run(host='0.0.0.0', port=PORT, threaded=True)
