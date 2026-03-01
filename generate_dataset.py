#!/usr/bin/env python3
"""
Generate an offline dataset of ASCII Tanks scenarios for GRPO training.
This creates random game states, extracts the text prompt, and saves the 
hidden physics state for the offline reward function to evaluate.
"""

import os
import json
import argparse
from datasets import Dataset

# Import the existing game logic
import server
import prompt

def generate_ascii_tanks_dataset(num_samples: int, train_for_symbol="A"):
    """
    Generates a dataset of random ASCII Tanks game states.
    For each state, we save the text prompt and the hidden "game_data"
    which contains the exact variables needed to simulate physics offline.
    """
    data = []
    system_rules = prompt.build_rules(train_for_symbol)
    
    for i in range(num_samples):
        # Generate a brand new random terrain and game state
        game_state = server.create_initial_state()
        
        pid = 0 if train_for_symbol == "A" else 1
        enemy_pid = 1 - pid
        
        me = game_state['players'][pid]
        enemy = game_state['players'][enemy_pid]
        
        # Create the text representation of the state for the LLM
        compact_ascii = server.render_compact_game(game_state)
        
        # Format stats EXACTLY as prompt.py expects them from the server
        stats = {
            'players': [
                {
                    'name': p.name, 'symbol': p.symbol, 'health': p.health,
                    'x': int(p.x), 'y': int(p.y),
                    'angle': p.angle, 'power': p.power, 'fuel': p.fuel,
                }
                for p in game_state['players']
            ],
            'currentPlayer': pid
        }
        
        user_message = prompt.build_state_prompt(
            stats=stats, 
            compact_ascii=compact_ascii, 
            player_symbol=train_for_symbol
        )
        # For fine-tuning models that don't have a special "system" channel,
        # also provide a single flat text prompt with the rules prepended.
        flat_prompt = system_rules + "\n\n" + user_message
        
        # Save the exact internal data needed for the offline physics simulation!
        physics_data = {
            "terrain": game_state['terrain'],
            "my_x": me.x,
            "my_y": me.y,
            "enemy_x": enemy.x,
            "enemy_y": enemy.y,
            "fuel": me.fuel,
        }
        
        data.append({
            # The "prompt" column is what GRPO sends to the LLM (chat format)
            "prompt": [
                {"role": "system", "content": system_rules},
                {"role": "user", "content": user_message}
            ],
            # The "prompt_text" column is a single string with rules
            # prepended, suitable for plain-text fine-tuning.
            "prompt_text": flat_prompt,
            # This extra column will be sent silently to the reward functions!
            "game_data": json.dumps(physics_data)
        })
        
        if (i + 1) % 100 == 0:
            print(f"Generated {i + 1}/{num_samples} samples...")
            
    # Convert to a HuggingFace Dataset
    return Dataset.from_list(data)


def main():
    parser = argparse.ArgumentParser(description="Generate ASCII Tanks Offline Dataset")
    parser.add_argument("--samples", type=int, default=1000, help="Number of random scenarios to generate")
    parser.add_argument("--symbol", type=str, default="A", choices=["A", "B"], help="Tank symbol to train for")
    parser.add_argument("--output", type=str, default="ascii_tanks_grpo_dataset.jsonl", help="Output JSONL file path")
    args = parser.parse_args()

    print(f"Generating {args.samples} offline game states for tank [{args.symbol}]...")
    dataset = generate_ascii_tanks_dataset(num_samples=args.samples, train_for_symbol=args.symbol)
    
    print(f"Saving dataset to {args.output}...")
    dataset.to_json(args.output, orient="records", lines=True)
    print("Done!")

if __name__ == "__main__":
    main()
