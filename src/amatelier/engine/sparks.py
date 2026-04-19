"""Spark ledger audit helper.

Single choke point for every mutation of an agent's spark balance. Callers
update ``metrics["sparks"]`` as they always have; this module's job is to
persist an immutable audit row per transaction to the ``spark_ledger``
table (see migrations/003_spark_ledger.sql) so the economy is queryable
and drift is detectable.

Design contract
---------------
Every spark delta that lands on ``metrics.json`` must also land here. The
write order inside callers is:

1. ``log_spark_delta(agent, amount, reason, category, roundtable_id)`` —
   commit the audit row first. This is the source of truth.
2. ``metrics["sparks"] = metrics.get("sparks", 0) + amount`` — update the
   in-memory balance.
3. ``save_metrics(agent, metrics)`` — persist the balance.

If step 1 succeeds and steps 2–3 fail, the ledger row is still correct and
a recovery job can rebuild ``metrics["sparks"]`` from
``SELECT SUM(amount) FROM spark_ledger WHERE agent_name=?``. If step 1
fails, the whole transaction aborts and the caller never touches the
balance.
"""

from __future__ import annotations

import logging
import time

from db import get_db

logger = logging.getLogger(__name__)


def log_spark_delta(
    agent_name: str,
    amount: int,
    reason: str,
    category: str,
    roundtable_id: str | None = None,
) -> None:
    """Append an audit row to ``spark_ledger`` for one spark delta.

    Args:
        agent_name: Worker whose balance is moving.
        amount: Signed delta. +N for credits, −N for debits.
        reason: Human-readable description. Include enough context that
            the row is self-explanatory without cross-referencing.
        category: Short machine tag. See CATEGORIES for the canonical set.
        roundtable_id: The RT this delta belongs to, if any. ``None`` for
            admin or marketplace actions that don't tie to an RT.

    A zero-amount call is a no-op; the helper does not pollute the ledger
    with meaningless rows.
    """
    if amount == 0:
        return

    try:
        conn = get_db()
    except Exception:
        logger.exception(
            "spark_ledger write failed for %s (amount=%+d, category=%s) — "
            "DB unreachable; balance will update without audit row.",
            agent_name, amount, category,
        )
        return

    try:
        conn.execute(
            "INSERT INTO spark_ledger "
            "(agent_name, amount, reason, category, roundtable_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent_name, int(amount), reason, category, roundtable_id, time.time()),
        )
        conn.commit()
    except Exception:
        logger.exception(
            "spark_ledger insert failed for %s (amount=%+d, category=%s)",
            agent_name, amount, category,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Canonical category tags. Readers filter and group by these.
CATEGORIES = frozenset({
    "opening_balance",     # one-time per-agent carry-over from pre-ledger era
    "score_award",         # gross sparks earned from judge scoring
    "entry_fee",           # flat RT entry fee (charged AFTER digest save; see runner)
    "gate_bonus",          # +3 per GATE signal
    "outcome_bonus",       # RT outcome implemented by user
    "tier_promotion",      # tier upgrade purchase
    "venture_stake",       # sparks staked on a venture pitch
    "venture_payout",      # successful venture payout
    "store_purchase",      # item bought from the skill/boost store
    "store_refund",        # unused store purchase refunded (e.g. first-speaker)
    "request_fee",         # private marketplace request fee
    "marketplace_payout",  # fulfiller payout for a marketplace request
    "refund_aborted_rt",   # legacy: fees refunded for pre-deferral aborted RTs
    "admin_grant",         # explicit grant from Admin
    "admin_penalty",       # explicit debit from Admin
})
