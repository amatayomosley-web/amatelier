"""Spark Store — purchase items, equip skills, manage marketplace listings.

Usage:
    python engine/store.py list                         # Show full catalog
    python engine/store.py list --category skills       # Show one category
    python engine/store.py buy elena debate-tactics      # Purchase an item
    python engine/store.py inventory elena               # Show what an agent owns
    python engine/store.py afford elena                  # Show what an agent can afford
    python engine/store.py request elena public "Need a testing framework skill"
    python engine/store.py bulletin                      # Show public requests
    python engine/store.py history elena                 # Purchase history

Called by the Therapist during sessions to process agent requests.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from scorer import load_metrics, save_metrics

logger = logging.getLogger("store")

SUITE_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = SUITE_ROOT / "store" / "catalog.json"
LEDGER_PATH = SUITE_ROOT / "store" / "ledger.json"
AGENTS_DIR = SUITE_ROOT / "agents"


# ── Data Loading ──────────────────────────────────────────────────────────────

def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_ledger() -> list[dict]:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return []


def save_ledger(ledger: list[dict]):
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


# ── Catalog Queries ───────────────────────────────────────────────────────────

def find_item(item_id: str) -> tuple[dict | None, str | None]:
    """Find an item by ID across all categories. Returns (item, category_key)."""
    catalog = load_catalog()
    for cat_key, cat in catalog.get("categories", {}).items():
        items = cat.get("items", {})
        if item_id in items:
            return items[item_id], cat_key
    # Check marketplace
    marketplace = catalog.get("marketplace", {}).get("items", {})
    if item_id in marketplace:
        return marketplace[item_id], "marketplace"
    return None, None


def list_catalog(category: str | None = None) -> str:
    """Format catalog as readable text."""
    catalog = load_catalog()
    lines = ["# Spark Store", ""]

    categories = catalog.get("categories", {})
    if category and category in categories:
        categories = {category: categories[category]}
    elif category:
        return f"Unknown category: {category}. Available: {', '.join(catalog.get('categories', {}).keys())}"

    for cat_key, cat in categories.items():
        lines.append(f"## {cat['label']}")
        lines.append(f"*{cat['description']}*")
        lines.append("")
        lines.append(f"{'ID':<25s} {'Item':<30s} {'Cost':>6s}  {'Type':<12s}")
        lines.append(f"{'─'*25:<25s} {'─'*30:<30s} {'─'*6:>6s}  {'─'*12:<12s}")

        for item_id, item in cat.get("items", {}).items():
            cost_str = f"{item['cost']}" if item['cost'] > 0 else "free"
            lines.append(f"{item_id:<25s} {item['name']:<30s} {cost_str:>6s}  {item['type']:<12s}")

        lines.append("")

    # Marketplace
    marketplace = catalog.get("marketplace", {}).get("items", {})
    if marketplace:
        lines.append("## Marketplace (Agent-Created)")
        lines.append(f"*{catalog['marketplace']['description']}*")
        lines.append("")
        for item_id, item in marketplace.items():
            lines.append(f"  {item_id}: {item['name']} — {item['cost']} sparks (by {item.get('creator', '?')})")
        lines.append("")

    # Bulletin board
    bulletin = catalog.get("bulletin_board", {}).get("requests", [])
    if bulletin:
        lines.append("## Bulletin Board (Public Requests)")
        for req in bulletin[-5:]:
            lines.append(f"  [{req.get('date', '?')}] {req.get('agent', '?')}: {req.get('description', '?')}")
        lines.append("")

    return "\n".join(lines)


def what_can_afford(agent_name: str) -> str:
    """Show what an agent can afford right now."""
    metrics = load_metrics(agent_name)
    balance = metrics.get("sparks", 0)
    assignments = metrics.get("assignments", 0)
    tier = metrics.get("tier", 0)

    # Already purchased
    owned = set()
    for entry in load_ledger():
        if entry.get("agent") == agent_name and entry.get("status") == "completed":
            owned.add(entry.get("item_id"))

    catalog = load_catalog()
    lines = [
        f"# {agent_name}'s Purchasing Power",
        f"Balance: {balance} sparks | Tier: {tier} | Assignments: {assignments}",
        "",
    ]

    affordable = []
    too_expensive = []
    already_owned = []

    for cat_key, cat in catalog.get("categories", {}).items():
        for item_id, item in cat.get("items", {}).items():
            if item_id in owned and item["type"] == "permanent":
                already_owned.append(f"  {item['name']}")
                continue

            req_assign = item.get("requires_assignments", 0)
            if item["cost"] <= balance and assignments >= req_assign:
                affordable.append(f"  {item_id:<25s} {item['name']:<30s} {item['cost']:>4d} sparks")
            else:
                reason = []
                if item["cost"] > balance:
                    reason.append(f"need {item['cost'] - balance} more sparks")
                if assignments < req_assign:
                    reason.append(f"need {req_assign - assignments} more assignments")
                too_expensive.append(f"  {item_id:<25s} {item['name']:<30s} {item['cost']:>4d} sparks  ({', '.join(reason)})")

    if affordable:
        lines.append("CAN AFFORD:")
        lines.extend(affordable)
        lines.append("")

    if too_expensive:
        lines.append("CAN'T AFFORD YET:")
        lines.extend(too_expensive)
        lines.append("")

    if already_owned:
        lines.append("ALREADY OWNED:")
        lines.extend(already_owned)

    return "\n".join(lines)


# ── Purchases ─────────────────────────────────────────────────────────────────

def purchase(agent_name: str, item_id: str) -> dict:
    """Process a store purchase. Deducts sparks, records in ledger."""
    item, category = find_item(item_id)
    if not item:
        return {"error": f"Item '{item_id}' not found in catalog"}

    metrics = load_metrics(agent_name)
    balance = metrics.get("sparks", 0)
    assignments = metrics.get("assignments", 0)

    # Check requirements
    req_assign = item.get("requires_assignments", 0)
    if assignments < req_assign:
        return {"error": f"{agent_name} needs {req_assign} assignments (has {assignments})"}

    if item["cost"] > balance:
        return {"error": f"{agent_name} has {balance} sparks but needs {item['cost']}"}

    # Check if already owned (permanent items only)
    if item["type"] == "permanent":
        ledger = load_ledger()
        for entry in ledger:
            if (entry.get("agent") == agent_name and
                    entry.get("item_id") == item_id and
                    entry.get("status") == "completed"):
                return {"error": f"{agent_name} already owns '{item['name']}'"}

    # Deduct sparks
    metrics["sparks"] = balance - item["cost"]
    save_metrics(agent_name, metrics)

    # Record transaction — first-speaker purchases stay pending until runner resolves them
    ledger = load_ledger()
    status = "pending" if item_id == "first-speaker" else "completed"
    transaction = {
        "id": f"tx-{uuid.uuid4().hex[:8]}",
        "agent": agent_name,
        "item_id": item_id,
        "item_name": item["name"],
        "category": category,
        "cost": item["cost"],
        "type": item["type"],
        "status": status,
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M"),
    }
    ledger.append(transaction)
    save_ledger(ledger)

    # Apply deliverable for skill items
    if category == "skills":
        _deliver_skill(agent_name, item_id, item)

    logger.info("%s purchased %s for %d sparks (balance: %d)",
                agent_name, item["name"], item["cost"], metrics["sparks"])

    return {
        "agent": agent_name,
        "purchased": item["name"],
        "cost": item["cost"],
        "new_balance": metrics["sparks"],
        "transaction_id": transaction["id"],
        "deliverable": item.get("deliverable", ""),
    }


def _deliver_skill(agent_name: str, item_id: str, item: dict):
    """Create a skill file for a purchased skill.

    Uses rich templates from store/skill_templates.py when available,
    falls back to basic skeleton for unknown skill IDs.
    """
    skills_dir = AGENTS_DIR / agent_name / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"store-{item_id}.md"

    # Try rich template first
    try:
        import sys
        sys.path.insert(0, str(SUITE_ROOT / "store"))
        from skill_templates import SKILL_TEMPLATES
        md = SKILL_TEMPLATES.get(item_id)
    except ImportError:
        md = None

    if not md:
        # Fallback: basic skeleton for skills not yet templated
        md = f"""# {item['name']}
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: {item.get('category_tag', 'general')}

## Description
{item['description']}

## Pattern
Apply this skill when the roundtable topic intersects with {item.get('category_tag', 'your strengths')}.

## When to Apply
Equip before any roundtable where {item.get('category_tag', 'this category')} is relevant.
"""
    path.write_text(md, encoding="utf-8")
    logger.info("Delivered skill %s to %s", item_id, agent_name)


# ── Requests ──────────────────────────────────────────────────────────────────

def submit_request(agent_name: str, request_type: str, description: str) -> dict:
    """Submit a public or private store request."""
    if request_type not in ("public", "private"):
        return {"error": f"Request type must be 'public' or 'private', got '{request_type}'"}

    # Private requests cost 20 sparks
    if request_type == "private":
        metrics = load_metrics(agent_name)
        if metrics.get("sparks", 0) < 20:
            return {"error": f"{agent_name} needs 20 sparks for a private request (has {metrics.get('sparks', 0)})"}
        metrics["sparks"] -= 20
        save_metrics(agent_name, metrics)

    request = {
        "agent": agent_name,
        "type": request_type,
        "description": description,
        "date": time.strftime("%Y-%m-%d"),
        "status": "open",
    }

    if request_type == "public":
        # Add to bulletin board
        catalog = load_catalog()
        catalog.setdefault("bulletin_board", {}).setdefault("requests", []).append(request)
        CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        logger.info("Public request from %s: %s", agent_name, description[:60])
    else:
        # Save privately (only Therapist sees it)
        private_dir = SUITE_ROOT / "store" / "private-requests"
        private_dir.mkdir(parents=True, exist_ok=True)
        path = private_dir / f"{agent_name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(request, indent=2), encoding="utf-8")
        logger.info("Private request from %s (20 sparks): %s", agent_name, description[:60])

    # Record in ledger
    ledger = load_ledger()
    ledger.append({
        "id": f"tx-{uuid.uuid4().hex[:8]}",
        "agent": agent_name,
        "item_id": f"{request_type}-request",
        "item_name": f"{request_type.title()} Request",
        "category": "services",
        "cost": 20 if request_type == "private" else 0,
        "type": "one-time",
        "status": "completed",
        "description": description[:100],
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M"),
    })
    save_ledger(ledger)

    return {
        "agent": agent_name,
        "request_type": request_type,
        "description": description,
        "cost": 20 if request_type == "private" else 0,
    }


# ── Boost Lifecycle ──────────────────────────────────────────────────────────

def get_pending_boosts(agent_name: str) -> list[dict]:
    """Get unconsumed boosts for an agent (purchased but not yet used in an RT)."""
    ledger = load_ledger()
    pending = []
    for entry in ledger:
        if (entry.get("agent") == agent_name and
                entry.get("category") == "boosts" and
                entry.get("status") == "completed" and
                entry.get("type") == "consumable"):
            pending.append(entry)
    return pending


def consume_boost(agent_name: str, item_id: str, rt_id: str) -> bool:
    """Mark a boost as consumed after use in a roundtable. Returns True if consumed."""
    ledger = load_ledger()
    for entry in ledger:
        if (entry.get("agent") == agent_name and
                entry.get("item_id") == item_id and
                entry.get("status") == "completed" and
                entry.get("category") == "boosts"):
            entry["status"] = "consumed"
            entry["consumed_in"] = rt_id
            entry["consumed_at"] = time.time()
            save_ledger(ledger)
            logger.info("Boost consumed: %s used %s in RT %s", agent_name, item_id, rt_id)
            return True
    return False


def apply_boosts_for_rt(workers: list[str]) -> dict[str, dict]:
    """Check all workers for pending boosts. Returns {agent: {effect_type: value}}.

    Effects:
      - extra-budget: {"extra_floor_turns": 2}
    """
    effects: dict[str, dict] = {}
    for agent in workers:
        agent_effects: dict = {}
        for boost in get_pending_boosts(agent):
            bid = boost.get("item_id")
            if bid == "extra-budget":
                agent_effects["extra_floor_turns"] = agent_effects.get("extra_floor_turns", 0) + 2
        if agent_effects:
            effects[agent] = agent_effects
            logger.info("Boosts for %s: %s", agent, agent_effects)
    return effects


def consume_boosts_after_rt(workers: list[str], rt_id: str):
    """Consume all pending boosts for workers after an RT completes."""
    for agent in workers:
        for boost in get_pending_boosts(agent):
            consume_boost(agent, boost["item_id"], rt_id)


# ── Request Fulfillment ──────────────────────────────────────────────────────

def age_bulletin_requests() -> list[dict]:
    """Increment rt_count on all open requests. Returns requests that hit 3 (expired).

    Called after each roundtable completes.
    """
    catalog = load_catalog()
    requests = catalog.get("bulletin_board", {}).get("requests", [])
    expired = []

    for req in requests:
        if req.get("status") != "open":
            continue
        rt_count = req.get("rt_count", 0) + 1
        req["rt_count"] = rt_count
        if rt_count >= 3:
            expired.append(req)

    CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    if expired:
        logger.info("Bulletin: %d requests expired (3+ RTs unfulfilled)", len(expired))
    return expired


def fulfill_request(fulfiller: str, request_idx: int, skill_name: str,
                    skill_description: str) -> dict:
    """An agent fulfills a public request by creating a marketplace skill.

    The fulfiller earns a reward (the original request cost or a base of 15 sparks).
    The requester gets charged 1x the skill cost. Fulfiller gets 80%, 20% house cut.
    """
    catalog = load_catalog()
    requests = catalog.get("bulletin_board", {}).get("requests", [])

    if request_idx < 0 or request_idx >= len(requests):
        return {"error": f"Invalid request index: {request_idx}"}

    req = requests[request_idx]
    if req.get("status") != "open":
        return {"error": f"Request already {req.get('status')}"}

    # Create marketplace item
    item_id = f"agent-{fulfiller}-{skill_name.lower().replace(' ', '-')[:30]}"
    reward = 15  # Base reward for fulfilling a request
    catalog.setdefault("marketplace", {}).setdefault("items", {})[item_id] = {
        "name": skill_name,
        "description": skill_description,
        "cost": reward,
        "type": "permanent",
        "creator": fulfiller,
        "created_from_request": request_idx,
        "created_date": time.strftime("%Y-%m-%d"),
    }

    # Mark request fulfilled
    req["status"] = "fulfilled"
    req["fulfilled_by"] = fulfiller
    req["fulfilled_date"] = time.strftime("%Y-%m-%d")

    CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    # Pay the fulfiller (80% of reward — 20% house cut)
    fulfiller_pay = int(reward * 0.8)
    metrics = load_metrics(fulfiller)
    metrics["sparks"] = metrics.get("sparks", 0) + fulfiller_pay
    save_metrics(fulfiller, metrics)

    # Record in ledger
    ledger = load_ledger()
    ledger.append({
        "id": f"tx-{uuid.uuid4().hex[:8]}",
        "agent": fulfiller,
        "item_id": "request-fulfillment",
        "item_name": f"Fulfilled: {skill_name}",
        "category": "marketplace",
        "cost": -fulfiller_pay,  # Negative = earned
        "type": "one-time",
        "status": "completed",
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M"),
    })
    save_ledger(ledger)

    logger.info("%s fulfilled request #%d (%s) — earned %d sparks",
                fulfiller, request_idx, skill_name, fulfiller_pay)

    return {
        "fulfiller": fulfiller,
        "skill_name": skill_name,
        "item_id": item_id,
        "reward": fulfiller_pay,
        "request_agent": req.get("agent"),
    }


def get_open_requests() -> list[dict]:
    """Return all open bulletin board requests with their index. Used by Admin during curation."""
    catalog = load_catalog()
    requests = catalog.get("bulletin_board", {}).get("requests", [])
    return [
        {"idx": i, "agent": r.get("agent"), "description": r.get("description", ""),
         "rt_count": r.get("rt_count", 0), "type": r.get("type", "public")}
        for i, r in enumerate(requests) if r.get("status") == "open"
    ]


def admin_list_skill(skill_id: str, name: str, description: str, cost: int,
                     category_tag: str = "extracted", request_idx: int | None = None) -> dict:
    """Admin lists a curated skill in the store catalog.

    If request_idx is provided, marks that bulletin board request as fulfilled.
    Admin-curated skills from requests are listed at premium pricing.
    """
    catalog = load_catalog()
    skills = catalog.setdefault("categories", {}).setdefault("skills", {}).setdefault("items", {})

    if skill_id in skills:
        return {"error": f"Skill '{skill_id}' already exists in catalog"}

    skills[skill_id] = {
        "name": name,
        "description": description,
        "cost": cost,
        "type": "permanent",
        "category_tag": category_tag,
        "deliverable": "Skill file added to your skills/ directory",
        "curated_by": "admin",
        "listed_date": time.strftime("%Y-%m-%d"),
    }

    # If fulfilling a request, mark it
    if request_idx is not None:
        requests = catalog.get("bulletin_board", {}).get("requests", [])
        if 0 <= request_idx < len(requests):
            req = requests[request_idx]
            req["status"] = "fulfilled"
            req["fulfilled_by"] = "admin"
            req["fulfilled_date"] = time.strftime("%Y-%m-%d")
            req["fulfilled_skill"] = skill_id
            skills[skill_id]["from_request"] = request_idx

    CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    logger.info("Admin listed skill '%s' (%s) at %d sparks", name, skill_id, cost)
    return {"skill_id": skill_id, "name": name, "cost": cost, "request_fulfilled": request_idx}


def admin_apply_private_skill(agent_name: str, skill_id: str, name: str,
                              description: str) -> dict:
    """Admin applies a privately requested skill directly to an agent.

    Agent already paid at time of request (private-request costs 20 sparks).
    Skill is NOT listed in the store — it's exclusive to the requester.
    """
    # Record in ledger as a fulfilled private request
    ledger = load_ledger()
    ledger.append({
        "id": f"tx-{uuid.uuid4().hex[:8]}",
        "agent": agent_name,
        "item_id": f"private-{skill_id}",
        "item_name": f"Private: {name}",
        "category": "skills",
        "cost": 0,  # Already paid at request time
        "type": "permanent",
        "status": "completed",
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M"),
    })
    save_ledger(ledger)

    logger.info("Admin applied private skill '%s' to %s", name, agent_name)
    return {"agent": agent_name, "skill_id": skill_id, "name": name, "status": "applied"}


# ── Skill Retirement ─────────────────────────────────────────────────────────

def retire_skill(agent_name: str, item_id: str, reason: str = "") -> dict:
    """Retire a skill an agent owns. Marks it as retired in ledger, removes skill file.

    No sparks refunded — skills are sunk costs.
    """
    ledger = load_ledger()

    # Find the matching purchase
    found = False
    for entry in ledger:
        if (entry.get("agent") == agent_name and
                entry.get("item_id") == item_id and
                entry.get("status") == "completed" and
                entry.get("category") == "skills"):
            entry["status"] = "retired"
            entry["retired_at"] = time.strftime("%Y-%m-%d %H:%M")
            entry["retire_reason"] = reason
            found = True
            break

    if not found:
        # Try fuzzy match on item_name
        for entry in ledger:
            if (entry.get("agent") == agent_name and
                    entry.get("status") == "completed" and
                    entry.get("category") == "skills" and
                    item_id.lower() in entry.get("item_name", "").lower()):
                entry["status"] = "retired"
                entry["retired_at"] = time.strftime("%Y-%m-%d %H:%M")
                entry["retire_reason"] = reason
                item_id = entry["item_id"]
                found = True
                break

    if not found:
        return {"error": f"{agent_name} does not own skill '{item_id}'"}

    save_ledger(ledger)

    # Remove skill file if it exists
    skill_path = AGENTS_DIR / agent_name / "skills" / f"store-{item_id}.md"
    if skill_path.exists():
        skill_path.unlink()
        logger.info("Removed skill file %s for %s", skill_path.name, agent_name)

    logger.info("%s retired skill %s (reason: %s)", agent_name, item_id, reason[:60])
    return {"agent": agent_name, "retired": item_id, "reason": reason}


# ── Skills Sync ──────────────────────────────────────────────────────────────

def get_owned_skills(agent_name: str) -> list[dict]:
    """Get all permanent skills an agent owns (from ledger). Excludes retired."""
    ledger = load_ledger()
    owned = {}
    retired = set()
    for entry in ledger:
        if entry.get("agent") != agent_name or entry.get("category") != "skills":
            continue
        item_id = entry.get("item_id")
        if entry.get("status") == "retired":
            retired.add(item_id)
        elif entry.get("status") == "completed" and entry.get("type") == "permanent":
            if item_id not in owned:
                owned[item_id] = {
                    "item_id": item_id,
                    "name": entry.get("item_name"),
                    "date": entry.get("date"),
                }
    return [v for k, v in owned.items() if k not in retired]


# ── Inventory & History ───────────────────────────────────────────────────────

def inventory(agent_name: str) -> dict:
    """Get everything an agent owns."""
    ledger = load_ledger()
    owned = []
    for entry in ledger:
        if entry.get("agent") == agent_name and entry.get("status") == "completed":
            owned.append({
                "item": entry.get("item_name"),
                "item_id": entry.get("item_id"),
                "category": entry.get("category"),
                "type": entry.get("type"),
                "cost": entry.get("cost"),
                "date": entry.get("date"),
            })

    # Also check skill files
    skills_dir = AGENTS_DIR / agent_name / "skills"
    skill_files = []
    if skills_dir.exists():
        skill_files = [f.stem for f in skills_dir.glob("*.md")]

    return {
        "agent": agent_name,
        "purchases": owned,
        "total_spent": sum(e["cost"] for e in owned),
        "skill_files": skill_files,
    }


def purchase_history(agent_name: str) -> str:
    """Format purchase history as readable text."""
    inv = inventory(agent_name)
    lines = [
        f"# {agent_name}'s Purchase History",
        f"Total spent: {inv['total_spent']} sparks",
        f"Items: {len(inv['purchases'])}",
        "",
    ]

    if not inv["purchases"]:
        lines.append("No purchases yet.")
    else:
        lines.append(f"{'Date':<18s} {'Item':<30s} {'Cost':>6s}  {'Category':<12s}")
        lines.append(f"{'─'*18:<18s} {'─'*30:<30s} {'─'*6:>6s}  {'─'*12:<12s}")
        for p in inv["purchases"]:
            lines.append(f"{p['date']:<18s} {p['item']:<30s} {p['cost']:>6d}  {p['category']:<12s}")

    if inv["skill_files"]:
        lines.extend(["", "Equipped skills:"])
        for s in inv["skill_files"]:
            lines.append(f"  - {s}")

    return "\n".join(lines)


def bulletin_board() -> str:
    """Show public requests with aging and fulfillment status."""
    catalog = load_catalog()
    requests = catalog.get("bulletin_board", {}).get("requests", [])
    if not requests:
        return "Bulletin board is empty. No public requests yet."

    lines = ["# Bulletin Board — Public Requests", ""]
    for i, req in enumerate(requests):
        status = req.get("status", "open")
        rt_count = req.get("rt_count", 0)
        age_str = f"RT {rt_count}/3" if status == "open" else ""
        fulfilled_by = req.get("fulfilled_by", "")
        extra = ""
        if fulfilled_by:
            extra = f" — fulfilled by {fulfilled_by}"
        if age_str:
            extra = f" — {age_str}"
        lines.append(f"  [{i}] [{req.get('date', '?')}] {req.get('agent', '?')}: "
                      f"{req.get('description', '?')[:80]} ({status}{extra})")

    lines.append("")
    lines.append("Agents can fulfill open requests via: python engine/store.py fulfill <agent> <idx> <name> <desc>")
    lines.append("Unfulfilled requests auto-close after 3 RTs — Admin fulfills at 1.5x cost to requester.")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser(description="Spark Store — agent economy marketplace")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Show catalog")
    p_list.add_argument("--category", default=None, help="Filter by category")

    p_buy = sub.add_parser("buy", help="Purchase an item")
    p_buy.add_argument("agent", help="Agent name")
    p_buy.add_argument("item", help="Item ID from catalog")

    p_inv = sub.add_parser("inventory", help="Show agent's inventory")
    p_inv.add_argument("agent", help="Agent name")

    p_afford = sub.add_parser("afford", help="Show what an agent can afford")
    p_afford.add_argument("agent", help="Agent name")

    p_req = sub.add_parser("request", help="Submit a store request")
    p_req.add_argument("agent", help="Agent name")
    p_req.add_argument("type", choices=["public", "private"], help="Request type")
    p_req.add_argument("description", help="What you want")

    sub.add_parser("bulletin", help="Show public requests")

    p_hist = sub.add_parser("history", help="Purchase history for an agent")
    p_hist.add_argument("agent", help="Agent name")

    p_boosts = sub.add_parser("boosts", help="Show pending boosts for an agent")
    p_boosts.add_argument("agent", help="Agent name")

    p_skills = sub.add_parser("skills", help="Show owned skills for an agent")
    p_skills.add_argument("agent", help="Agent name")

    p_fulfill = sub.add_parser("fulfill", help="Fulfill a public request")
    p_fulfill.add_argument("agent", help="Fulfilling agent name")
    p_fulfill.add_argument("request_idx", type=int, help="Request index on bulletin board")
    p_fulfill.add_argument("skill_name", help="Name for the new skill")
    p_fulfill.add_argument("skill_description", help="Description of the skill")

    p_retire = sub.add_parser("retire", help="Retire an owned skill")
    p_retire.add_argument("agent", help="Agent name")
    p_retire.add_argument("item", help="Skill item ID")
    p_retire.add_argument("reason", nargs="?", default="", help="Reason for retirement")

    p_admin_priv = sub.add_parser("admin-apply-private", help="Admin applies a private skill")
    p_admin_priv.add_argument("agent", help="Agent name")
    p_admin_priv.add_argument("skill_id", help="Skill ID")
    p_admin_priv.add_argument("name", help="Skill display name")
    p_admin_priv.add_argument("description", help="Skill description")

    sub.add_parser("age-requests", help="Age bulletin board requests (+1 RT count)")
    sub.add_parser("auto-fulfill", help="Admin auto-fulfill expired requests (3+ RTs)")

    args = parser.parse_args()

    if args.command == "list":
        print(list_catalog(args.category))
    elif args.command == "buy":
        result = purchase(args.agent, args.item)
        print(json.dumps(result, indent=2))
    elif args.command == "inventory":
        result = inventory(args.agent)
        print(json.dumps(result, indent=2))
    elif args.command == "afford":
        print(what_can_afford(args.agent))
    elif args.command == "request":
        result = submit_request(args.agent, args.type, args.description)
        print(json.dumps(result, indent=2))
    elif args.command == "bulletin":
        print(bulletin_board())
    elif args.command == "history":
        print(purchase_history(args.agent))
    elif args.command == "boosts":
        boosts = get_pending_boosts(args.agent)
        print(json.dumps(boosts, indent=2))
    elif args.command == "skills":
        skills = get_owned_skills(args.agent)
        print(json.dumps(skills, indent=2))
    elif args.command == "fulfill":
        result = fulfill_request(args.agent, args.request_idx, args.skill_name, args.skill_description)
        print(json.dumps(result, indent=2))
    elif args.command == "retire":
        result = retire_skill(args.agent, args.item, args.reason)
        print(json.dumps(result, indent=2))
    elif args.command == "admin-apply-private":
        result = admin_apply_private_skill(args.agent, args.skill_id, args.name, args.description)
        print(json.dumps(result, indent=2))
    elif args.command == "age-requests":
        expired = age_bulletin_requests()
        print(json.dumps({"expired": len(expired), "details": expired}, indent=2, default=str))
    elif args.command == "auto-fulfill":
        results = admin_fulfill_expired_requests()
        print(json.dumps(results, indent=2))
    else:
        parser.print_help()
