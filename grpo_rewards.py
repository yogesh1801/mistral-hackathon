import math
import json
import re

# =====================================================================
# Reward Functions (Offline Physics Simulation)
# =====================================================================
# These functions are called by the GRPO trainer after the LLM generates
# a batch of possible actions (completions).

def extract_xml_answer(text: str) -> str:
    """Helper to extract an answer block if the model uses reasoning XML."""
    if "<answer>" in text and "</answer>" in text:
        answer = text.split("<answer>")[-1]
        answer = answer.split("</answer>")[0]
        return answer.strip()
    return text.strip()

def parse_model_json(completion_text):
    """Safely extracts the JSON block from the model's output"""
    try:
        # Check if wrapped in markdown code blocks
        match = re.search(r'\{.*\}', completion_text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(completion_text)
    except Exception:
        return None

def format_reward_func(completions, **kwargs):
    """
    Reward function that ensures the model outputs valid JSON
    with the required keys (`move`, `angle`, `power`).
    This provides a strong baseline reward for structural correctness.
    """
    rewards = []
    for completion in completions:
        # Handle different TRL completion formatting structures
        text = completion[0]['content'] if isinstance(completion, list) else completion
        content = extract_xml_answer(text)
        action = parse_model_json(content)
        
        if isinstance(action, dict) and 'angle' in action and 'power' in action and 'move' in action:
            rewards.append(1.0)
        elif isinstance(action, dict) and 'angle' in action and 'power' in action:
            rewards.append(0.5) # Minimum viable JSON
        else:
            rewards.append(0.0) # Failed format
    return rewards

def strategy_succeeds(prompts, completions, game_data, **kwargs):
    """
    Tests the generated action using an offline fast physics simulation!
    """
    rewards = []
    
    # Iterate through all generated responses in the batch
    for completion, state_json in zip(completions, game_data):
        text = completion[0]['content'] if isinstance(completion, list) else completion
        content = extract_xml_answer(text)
        action = parse_model_json(content)
        
        # If format failed or isn't a dict, assign negative reward so it learns quickly
        if not isinstance(action, dict) or 'angle' not in action or 'power' not in action:
            rewards.append(-2.0) 
            continue
            
        state = json.loads(state_json)
        
        # --- OFFLINE PHYSICS SIMULATION ---
        # 1. First, handle movement
        move_val = 0
        if 'move' in action and action['move'] is not None:
            raw_move = action['move']
            # If the model returns a list/tuple (e.g. [3] or ["-2"]), pick the first element
            if isinstance(raw_move, (list, tuple)):
                raw_move = raw_move[0] if raw_move else 0
            try:
                move_val = int(raw_move)
            except (ValueError, TypeError):
                # If it still can't be converted, leave move_val at 0 (no movement)
                pass
                
        my_x = int(state['my_x'])
        my_y = int(state['my_y'])
        # Use remaining fuel from state if available, otherwise assume full tank (20)
        fuel = int(state.get('fuel', 20))
        if fuel < 0:
            fuel = 0
        
        if move_val != 0:
            direction = 1 if move_val > 0 else -1
            steps = min(abs(move_val), fuel)
            for _ in range(steps):
                new_x = my_x + direction
                if new_x < 3 or new_x >= 80 - 3:
                    break # Hit boundary
                new_y = state['terrain'][new_x] - 1
                old_y = state['terrain'][my_x] - 1
                if old_y - new_y > 2:
                    break # Too steep
                my_x = new_x
                my_y = new_y

        # 2. Now calculate the shot from the NEW position
        raw_angle = action.get('angle', 0)
        raw_power = action.get('power', 0)

        # Handle list/tuple outputs like ["45"] or [60.0]
        if isinstance(raw_angle, (list, tuple)):
            raw_angle = raw_angle[0] if raw_angle else 0
        if isinstance(raw_power, (list, tuple)):
            raw_power = raw_power[0] if raw_power else 0

        try:
            angle_val = float(raw_angle)
        except (ValueError, TypeError):
            angle_val = 0.0
        try:
            power_val = float(raw_power)
        except (ValueError, TypeError):
            power_val = 0.0

        angle = max(0, min(180, angle_val))
        power = max(0, min(100, power_val))
        
        rad = angle * math.pi / 180
        vx = math.cos(rad) * (power / 4)
        vy = -math.sin(rad) * (power / 4)
        
        # Start coordinate (from nozzle at new position)
        px = my_x + math.cos(rad) * 2
        py = (my_y - 1) - math.sin(rad) * 2
        
        # Step through physics until collision
        hit_x, hit_y = px, py
        for _ in range(200):  # Maximum steps
            alive = True
            for _ in range(8): # SUB_STEPS
                px += vx * (0.5 / 8) # DT / SUB_STEPS
                py += vy * (0.5 / 8)
                vy += (9.8 * 0.5) * (0.5 / 8)
                
                # check_collision logic
                if px < 0 or px >= 80 or py >= 30:
                    hit_x, hit_y = px, py
                    alive = False; break
                if py >= 0 and 0 <= int(px) < 80 and py >= state['terrain'][int(px)]:
                    hit_x, hit_y = px, py
                    alive = False; break
            if not alive: break
            
        # Calculate how far the projectile landed from the enemy
        dist_to_enemy = math.sqrt((hit_x - state['enemy_x'])**2 + (hit_y - state['enemy_y'])**2)
        
        # --- Give Rewards! ---
        if dist_to_enemy < 6.0: 
            # Calculate actual damage! 
            # (1 - distance/radius) * max_damage
            damage = int((1 - (dist_to_enemy / 6.0)) * 60)
            # Give a reward based on damage, but scale it down so variance isn't crazy
            # Max possible reward is 5.0 + (60 * 0.1) = 11.0
            r = 5.0 + (float(damage) * 0.1)
        else:
            # We need a steeper gradient! If it lands 60 away, give it -4.0.
            # If it lands 10 away, give it +1.0.
            r = 2.0 - (dist_to_enemy / 10.0)
            
        rewards.append(r)
        
        # Log the result so the user can see what happened during training
        if dist_to_enemy < 6.0:
            print(f"\n[GRPO Eval] Angle: {angle} | Power: {power} | Dist: {dist_to_enemy:.1f} | 💥 HIT! Dmg: {damage} | Reward: {r:.2f}")
        else:
            print(f"\n[GRPO Eval] Angle: {angle} | Power: {power} | Dist: {dist_to_enemy:.1f} | Miss | Reward: {r:.2f}")
            
    return rewards
