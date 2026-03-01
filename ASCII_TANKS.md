# 🚀 ASCII Tanks

A fully terminal-based, API-driven artillery game (inspired by Scorched Earth / Worms) where LLMs battle each other using purely ASCII visuals and JSON payloads!

## 🎮 What is it?

**ASCII Tanks** is a server-client game engine that lives entirely in your terminal. It features:
- **Destructible Terrain**: 80-column wide randomly generated hills. Missed shots create craters that permanently alter the landscape.
- **Physics Engine**: Trajectory simulation parsing angle, power, and gravity.
- **Terminal Streaming**: A live ANSI streaming endpoint (like `parrot.live`) that lets you watch the live game render directly in your shell.
- **LLM Native**: Built specifically to test and fine-tune the spatial reasoning of Large Language Models. LLMs "see" the game through a compact text endpoint and respond with JSON coordinate actions.

## 🛠️ Setup & Installation

**Prerequisites:** Python 3.8+

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   # or manually: pip install flask requests mistralai
   ```

2. **Start the Game Server:**
   ```bash
   python server.py
   ```
   The game server will launch locally on port `3001`.

3. **Watch the Game:**
   Open a separate, wide terminal window and run:
   ```bash
   curl -N localhost:3001/stream
   ```
   *Make sure your terminal is wide enough to see both the game box and the live match results leaderboard!*

4. **Start the LLM Battle:**
   Open a third terminal, set your API key, and launch the models into combat:
   ```bash
   export MISTRAL_API_KEY="your_api_key_here"
   python llm_battle.py --matches 3 --turns 20
   ```

---

## 🔌 API Reference

The entire game is controlled via a simple REST API running on `http://localhost:3001`.

### 1. View Live Stream
**`GET /stream`**
Continuously streams raw ANSI-encoded text frames to render the live game. Meant to be queried via `curl -N`.

### 2. Get Game State 
**`GET /api/stats`**
Returns the raw internal JSON state of the game, including player health, coordinates, whose turn it is, and game over status. Also includes the raw integer `terrain` array used for headless/RL dataset generation.

### 3. Get LLM-Friendly ASCII View
**`GET /api/ascii/compact`**
Returns a smaller, simplified visual text representation of the battlefield designed specifically to fit efficiently inside an LLM's context window.

### 4. Fire Weapon
**`POST /api/fire`**
Takes a JSON payload to execute a turn.
**Payload Format:**
```json
{
  "move": -1,   // Optional: Positive integer for right, negative for left (1 move = 1 fuel)
  "angle": 45,  // Firing angle in degrees (0 to 180). 90 is straight up.
  "power": 80   // Power / initial velocity of the shot (0 to 100)
}
```
**Response Format:** 
A human/LLM-readable text log detailing the shot trajectory, landing coordinates, if it hit the terrain or enemy, and damage dealt.

### 5. Reset Game
**`POST /api/reset`**
Resets the game state, randomly regenerates the terrain, and restores player health to start a brand new match.
