import json

print("Reading the first sample from ascii_tanks_grpo_dataset.jsonl...\n")
with open("ascii_tanks_grpo_dataset.jsonl", "r") as f:
    sample = json.loads(f.readline())

prompt_messages = sample["prompt"]

system_msg = next((m for m in prompt_messages if m.get("role") == "system"), None)
user_msg = next((m for m in prompt_messages if m.get("role") == "user"), None)

if system_msg:
    print("=== SYSTEM RULES (prepended during training) ===")
    print("-" * 60)
    print(system_msg["content"])
    print("-" * 60)
    print()

if user_msg:
    print("=== USER PROMPT (state + battlefield) ===")
    print("-" * 60)
    print(user_msg["content"])
    print("-" * 60)
    print("\nNotice how it looks exactly like battle.log! The JSON format just uses \\n and \\u2588 to store it safely on one line.")

if "prompt_text" in sample:
    print("\n=== FLAT TEXT PROMPT (for plain-text fine-tuning) ===")
    print("-" * 60)
    print(sample["prompt_text"])
    print("-" * 60)
