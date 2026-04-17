import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("roundtable.db")

def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def watch():
    print("\n\n======== CLAUDE SUITE WATCHER ========\nListening to active roundtable...\nDo not close this terminal if you want to keep watching.\nPress Ctrl+C to exit.\n======================================\n")
    
    last_id = 0
    rt_id = None
    
    # First, find the active roundtable
    conn = get_db()
    row = conn.execute("SELECT id, topic FROM roundtables WHERE status='open' ORDER BY created_at DESC LIMIT 1").fetchone()
    if row:
        rt_id = row['id']
        print(f"Joined active roundtable: '{row['topic']}'\n")
    else:
        print("No active roundtable found. Exiting.")
        return
        
    conn.close()

    while True:
        conn = get_db()
        
        # Check if still open
        status_row = conn.execute("SELECT status, cut_reason FROM roundtables WHERE id=?", (rt_id,)).fetchone()
        if not status_row or status_row['status'] != 'open':
            print(f"\n======== ROUNDTABLE CLOSED ========\nStatus: {status_row['status'] if status_row else 'unknown'}")
            if status_row and status_row['cut_reason']:
                print(f"Reason: {status_row['cut_reason']}")
            break
            
        # Get new messages
        rows = conn.execute(
            "SELECT id, agent_name, message, timestamp FROM messages WHERE roundtable_id=? AND id>? ORDER BY id",
            (rt_id, last_id)
        ).fetchall()
        
        if rows:
            for r in rows:
                print(f"[{r['agent_name'].upper()}] (Message ID: {r['id']})\n{r['message']}\n" + "-"*50 + "\n")
                last_id = max(last_id, r['id'])
                
        conn.close()
        time.sleep(2)

if __name__ == "__main__":
    watch()
