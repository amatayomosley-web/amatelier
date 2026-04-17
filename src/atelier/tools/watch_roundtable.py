import sqlite3
import time
import os
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / 'roundtable-server' / 'roundtable.db'

def watch_chat():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    print("====================================")
    print(" LIVE ROUNDTABLE VIEWER (Zero API)  ")
    print("====================================\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Find the current active roundtable
    row = conn.execute("SELECT id, topic FROM roundtables WHERE status='open' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        print("No active roundtable running right now.")
        return

    rt_id = row['id']
    topic = row['topic']
    print(f"🟢 Connected to Active Roundtable: {rt_id}\nTopic: {topic}\n")
    print("Waiting for new messages... (Press Ctrl+C to exit)\n")
    print("-" * 50)

    last_id = 0

    try:
        while True:
            # Poll for messages we haven't seen yet in this round
            messages = conn.execute(
                "SELECT id, agent_name, message FROM messages WHERE roundtable_id=? AND id > ? ORDER BY id", 
                (rt_id, last_id)
            ).fetchall()

            for msg in messages:
                agent = msg['agent_name'].upper()
                text = msg['message'].strip()
                
                # Assign some terminal colors based on the agent
                color = "\033[0m"
                if agent == "JUDGE":
                    color = "\033[93m"  # Yellow
                elif agent == "RUNNER":
                    color = "\033[90m"  # Grey
                elif agent.lower() == "naomi":
                    color = "\033[96m"  # Cyan
                else:
                    color = "\033[92m"  # Green
                
                reset = "\033[0m"
                
                print(f"{color}[{agent}]{reset}\n{text}\n")
                print("-" * 50)
                
                last_id = msg['id']

            time.sleep(2)  # Wait 2 seconds before checking the database again
    except KeyboardInterrupt:
        print("\nViewer closed.")

if __name__ == '__main__':
    watch_chat()
