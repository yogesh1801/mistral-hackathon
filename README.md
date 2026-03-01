# 🚀 ASCII Tanks — Teaching LLMs Physics Through Combat

> **Can a 3B parameter model learn to aim?** We used GRPO reinforcement learning with an offline physics simulator to teach Ministral 3B spatial reasoning — no labeled data, no human feedback, just raw trajectory math.

[![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)](https://python.org)
[![Mistral AI](https://img.shields.io/badge/Mistral_AI-Powered-orange?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PC9zdmc+)](https://mistral.ai)
[![HuggingFace](https://img.shields.io/badge/🤗_Model-yogesh1801/ministral--3b--grpo--ascii--tanks-yellow)](https://huggingface.co/yogesh1801/ministral-3b-grpo-ascii-tanks-merged)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🌟 Overview

**ASCII Tanks** is a terminal-based artillery game where two Mistral LLMs battle each other on a destructible ASCII battlefield. One model fires projectiles at the other by reasoning about angle, power, and distance — all from a text-only view of the game state.

The real innovation isn't the game — it's the **training pipeline**. We fine-tuned **Ministral 3B** using **GRPO (Group Relative Policy Optimization)** with a custom offline physics simulator as the reward function. The model learns to aim not from human demonstrations, but by simulating thousands of trajectories and receiving reward signals based on how close its shots land to the enemy.

**The result:** A tiny 3B model that develops genuine spatial intuition — understanding angles, parabolic trajectories, and distance estimation — purely through reinforcement learning.

---

## ❗ Problem

Large Language Models are powerful reasoners, but they notoriously struggle with **spatial and physics-based reasoning**. Ask an LLM to estimate a projectile trajectory or calculate the right angle to hit a target, and it will often hallucinate plausible-sounding but physically incorrect answers.

Current approaches to improving spatial reasoning rely on:
- Expensive human-labeled datasets
- Supervised fine-tuning on curated examples (which caps performance at human-level)
- Large models (70B+) that are impractical for edge deployment

**The core question:** Can we teach a small model to reason about physics — without any labeled data at all?

---

## 💡 Solution

We built an end-to-end pipeline that turns a game into a training environment:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Game Engine    │────▶│  Dataset Generator───▶│  GRPO Trainer       │
│  (server.py)    │     │  1000+ random    │     │  Unsloth + LoRA     │
│  Physics + API  │     │  game states     │     │  on Ministral 3B    │
└─────────────────┘     └──────────────────┘     └──────────┬──────────┘
                                                            │
                         ┌──────────────────┐               │
                         │  Reward Functions│◀─────────────┘
                         │  • Format check  │  Model generates actions
                         │  • Offline physics  Reward = f(trajectory)
                         │    simulation    │
                         └──────────────────┘
```

1. **Game Engine** — A fully functional ASCII artillery game with destructible terrain, projectile physics, and a REST API
2. **Dataset Generator** — Produces thousands of randomized game states (varied terrain, positions, distances)
3. **Offline Physics Reward** — Instead of playing the game live, we simulate the projectile trajectory offline and compute reward based on proximity to the enemy
4. **GRPO Training** — The model generates multiple candidate actions per state; the reward function scores them; the model learns from the relative ranking — no labels needed

After training, we pit the fine-tuned Ministral 3B against the much larger **Mistral Small** in live head-to-head matches.

---

## 🧠 Key Features

- **🎮 Full Game Engine** — 80-column ASCII battlefield with rolling hills, destructible terrain via crater physics, tank movement with fuel economy, and ANSI-colored live streaming (`curl -N localhost:3001/stream`)

- **🧪 Offline Physics Reward Function** — The GRPO reward function doesn't call the game server. It runs a complete offline trajectory simulation (gravity, sub-steps, collision detection) to evaluate each candidate action in milliseconds — enabling large-batch RL training

- **📊 Dual Reward Signal** — Combines structural reward (valid JSON output → +1.0) with a continuous physics reward (distance-to-enemy gradient from −5.0 to +11.0), giving the model both format and strategy learning signals

- **🔄 Zero-Shot Transfer** — The model is trained on random isolated states but deployed in multi-turn live battles with conversation history, hit/miss feedback, and adaptive opponents — and it generalizes

- **📡 LLM-Native API Design** — The game exposes a compact ASCII endpoint specifically optimized for LLM context windows, with column rulers for spatial reference and minimal token overhead

- **⚔️ Live Battle Framework** — Automated multi-match orchestration with conversation history management, shot feedback loops (hit/miss + direction), and CSV result tracking with a live ANSI leaderboard

---

## 🏗️ Architecture

```
                        ┌──────────────────────────────────┐
                        │         ASCII Tanks Server       │
                        │          (server.py)             │
                        │                                  │
                        │  • Terrain generation (sin wave) │
                        │  • Projectile physics engine     │
                        │  • ANSI frame renderer           │
                        │  • Flask REST API                │
                        └──────┬───────────┬───────────────┘
                               │           │
              ┌────────────────▼──┐   ┌────▼────────────────┐
              │  /api/ascii/compact   │  /api/fire          │
              │  /api/stats       │   │  /api/reset         │
              │  (Game State)     │   │  (Actions)          │
              └────────┬──────────┘   └────┬────────────────┘
                       │                   │
           ┌───────────▼───────────────────▼──────────────┐
           │           LLM Battle Orchestrator            │
           │         (llm_battle.py)                      │
           │                                              │
           │  Turn loop:                                  │
           │  1. Fetch game state + ASCII view            │
           │  2. Build prompt with feedback               │
           │  3. Call LLM → get {move, angle, power}      │
           │  4. POST /api/fire → get result              │
           │  5. Build feedback for next turn             │
           └──────────┬──────────────┬────────────────────┘
                      │              │
            ┌─────────▼────┐  ┌──────▼──────────┐
            │ Ministral 3B │  │  Mistral Small  │
            │  (Fine-tuned)│  │  (Baseline API) │
            └──────────────┘  └─────────────────┘

  ═══════════════ TRAINING PIPELINE ═══════════════

  generate_dataset.py  ──▶  ascii_tanks_grpo_dataset.jsonl
         │                         │
         │ Random game states      │ 1000+ scenarios
         │ with terrain/positions  │ with hidden physics data
         ▼                         ▼
  mistral_finetuning.ipynb (Unsloth + GRPO)
         │
         │ grpo_rewards.py
         │  ├─ format_reward_func()    → Valid JSON?
         │  └─ strategy_succeeds()     → Offline physics sim → reward
         ▼
  yogesh1801/ministral-3b-grpo-ascii-tanks (HuggingFace)
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Game Engine** | Python, Flask, ANSI escape codes, threading |
| **AI / ML** | Mistral AI API (`mistral-small-latest`, `ministral-3b-latest`) |
| **RL Training** | GRPO via TRL, Unsloth (2× faster LoRA fine-tuning), 16-bit LoRA (rank 32) |
| **Model Hosting** | HuggingFace Hub, vLLM (OpenAI-compatible serving) |
| **Dataset** | HuggingFace Datasets, custom offline physics simulator |
| **Monitoring** | Weights & Biases (training metrics), Loguru (battle logs) |
| **Infrastructure** | NVIDIA A100 80GB (training), Python REST API (game server) |

---

## 🔥 Unique Innovation

### GRPO + Offline Physics Simulator = RL Without an Environment

Traditional game-playing RL requires running the environment thousands of times. We bypass this entirely:

1. **Offline reward computation** — Our reward function contains a complete physics engine replica. When the model proposes `{angle: 45, power: 80}`, we simulate the full parabolic trajectory in pure Python — gravity, sub-steps, collision detection — and return a reward proportional to proximity-to-enemy. No server calls, no game ticks.

2. **GRPO over PPO** — By generating multiple candidate actions per state and using relative ranking (not absolute value estimation), GRPO provides stable training signal even with noisy physics rewards.

3. **Continuous reward shaping** — Instead of binary hit/miss, our reward function provides a smooth gradient:
   - Direct hit: **+5.0 to +11.0** (scaled by damage dealt)
   - Near miss (<6 units): **+5.0** base
   - Far miss: **−5.0 to +2.0** (linear distance penalty)

   This gives the model a clear learning signal at every distance.

4. **Tiny model, real reasoning** — Ministral 3B (1.72% trainable parameters via LoRA) learns to estimate distances from ASCII art, calculate appropriate angles, and adjust power — skills that typically require models 10× its size.

---

## ⚔️ Challenges & Learnings

| Challenge | How We Solved It |
|-----------|-----------------|
| **LLMs can't parse ASCII spatially** | Designed a compact renderer with column rulers and stripped formatting to minimize noise |
| **Reward signal too sparse** | Replaced binary hit/miss with continuous distance-based reward shaping (gradient from −5 to +11) |
| **Training instability with physics rewards** | Used GRPO's relative ranking instead of absolute value estimation; added format reward as a stabilizer |
| **Model outputting invalid JSON** | Added a structural reward (+1.0 for valid format) that the model learns before strategy — curriculum-style |
| **Terrain randomization causing reward variance** | Generated 1000+ diverse scenarios with random terrain phases, ensuring the model generalizes rather than memorizes |
| **Sub-step collision detection** | Implemented 8 sub-steps per physics tick to prevent projectiles from tunneling through terrain |

---

## 📊 Impact & Use Cases

### Who Benefits?

- **AI Researchers** — A reproducible benchmark for evaluating spatial reasoning in small language models
- **Game AI Developers** — Demonstrates that RL can train LLM-based game agents without environment interaction during training
- **Mistral Ecosystem** — Showcases fine-tuning Ministral 3B with GRPO for non-trivial reasoning tasks beyond text

### Broader Implications

This approach generalizes beyond games. Any domain where:
- A **physics simulator** can evaluate actions offline
- The task requires **spatial/numerical reasoning**
- **Small models** need to match large model performance

...can use this pattern. Think: robotics pre-training, autonomous navigation planning, engineering design optimization.

---

## 🚀 Future Scope

- **🏆 ELO Rating System** — Track model improvement across training checkpoints with proper statistical ranking
- **🌊 Wind & Weather** — Add environmental variables (wind speed, wind direction) to increase reasoning complexity
- **🤖 Multi-Agent GRPO** — Train both tanks simultaneously with self-play, creating an arms race of improving strategies
- **📈 Curriculum Learning** — Start with easy scenarios (close range, flat terrain) and progressively increase difficulty
- **🔬 Ablation Studies** — Measure contribution of each reward component, LoRA rank, and dataset size
- **🌐 Web UI** — Browser-based game viewer with WebSocket streaming for demo accessibility
- **📱 Edge Deployment** — Quantize the fine-tuned model to INT4 and deploy on consumer GPUs / mobile devices

---

## 🎥 Demo

| Resource | Link |
|----------|------|
| **GitHub Repository** | [github.com/yogesh1801/mistral-hackathon](https://github.com/yogesh1801/mistral-hackathon) |
| **Fine-tuned Model** | [🤗 yogesh1801/ministral-3b-grpo-ascii-tanks](https://huggingface.co/yogesh1801/ministral-3b-grpo-ascii-tanks-merged) |
| **Training Dataset** | Included in repo (`ascii_tanks_grpo_dataset.jsonl`) |

### Quick Start

```bash
# 1. Clone & install
git clone https://github.com/yogesh1801/mistral-hackathon.git
cd mistral-hackathon
pip install -r requirements.txt

# 2. Start the game server
python server.py

# 3. Watch the live battle (in a wide terminal)
curl -N localhost:3001/stream

# 4. Launch LLM vs LLM combat
export MISTRAL_API_KEY="your_key_here"
python llm_battle.py --matches 5 --turns 20
```

---

## 👥 Team

### Team Pivot

| Member | Role |
|--------|------|
| **Yogesh Singla** | Game engine, GRPO training pipeline, reward function design |
| **Simran Srivastava** | LLM battle orchestration, prompt engineering, evaluation |

---

<p align="center">
  <i>Built with 🎯 at the Mistral AI Hackathon — proving that small models can learn big physics.</i>
</p>

