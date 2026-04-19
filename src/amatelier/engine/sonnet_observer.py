"""Sonnet Per-RT Observer (consolidated: observations + skills + taxonomy).

Writes grounded observation notes for each worker after every roundtable, AND
extracts CAPTURE/FIX/DERIVE skills with pre-tagged taxonomy in the same pass.
Observations are descriptive (cognitive moves, rhetorical moves, evidence
practice, engagement pattern, peer references, judge feedback) — NEVER
assigning trait labels. Traits are evaluated by the therapist on a 10-RT
cadence using accumulated obs files.

Outputs:
  - agents/{worker}/observations/obs-{rt_id}.json      (per agent)
  - summary["skills_observed"]: list of skill dicts    (runner dedupes & persists)

Contract:
  - Sonnet reads each agent's posts + peer refs + judge lines + a compact
    RT-context preamble (judge summary, GATEs, score leaderboard) and emits
    per-agent observations + a skills_observed list for the batch.
  - Every skill has full taxonomy fields already populated (structural_category,
    trigger_phase, primary_actor, problem_nature, agent_dynamic, tags, one_liner).
  - Missing fields default to empty lists/strings.

Usage (from roundtable_runner):
    from sonnet_observer import observe_rt
    summary = observe_rt(rt_id, transcript, workers, scores_by_agent, digest)
    # summary["skills_observed"] is a deduped flat list ready for persistence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("sonnet_observer")

# Import amatelier's path utilities
try:
    from amatelier import paths
except ImportError:
    # Fallback for direct execution: assume we're in engine/
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from amatelier import paths

# Observation budget per agent. Sonnet call kept short: transcript slices
# are per-agent + peer context, plus a compact RT-context preamble.
MAX_TRANSCRIPT_CHARS = 18000
# Extended when the observer also extracts skills (longer prompt + response).
SONNET_TIMEOUT_SEC = 180
MAX_BUDGET_USD = "1.00"
# Cap for the RT-context preamble (judge summary, GATEs, score leaderboard, key moves).
MAX_RT_CONTEXT_CHARS = 6000

# Imperative verbs allowed to start a skill title. Applied to raw observer
# output before the runner's distiller.JUDGE gate runs; mirrors distiller._judge_gate.
_IMPERATIVE_VERBS = {
    "use", "apply", "check", "add", "avoid", "ensure", "validate", "prefer",
    "replace", "scan", "flag", "track", "detect", "call", "run", "test",
    "skip", "merge", "split", "wrap", "inject",
}


# ── Public API ──────────────────────────────────────────────────────────────

def observe_rt(
    rt_id: str,
    transcript: list[dict],
    workers: list[str],
    scores_by_agent: dict | None = None,
    digest: dict | None = None,
    batch_size: int = 3,
) -> dict:
    """Run per-worker observation for this RT. Returns a summary dict.

    Writes one file per worker to agents/{worker}/observations/obs-{rt_id}.json.

    batch_size controls how many agents share a single Sonnet call:
      1 = one call per agent (highest isolation, most expensive)
      3 = max-effort ceiling (default; for 5 agents this yields 2 calls: 3+2)
      5 = whole-RT in one call (cheapest, quality drops)

    Errors per-batch are logged and skipped; successful agents in a failed
    batch are retried one-by-one via the single-agent path.
    """
    scores_by_agent = scores_by_agent or {}
    summary = {
        "rt_id": rt_id,
        "observed": [],
        "skipped": [],
        "errors": [],
        "batch_size": batch_size,
        "skills_observed": [],
    }

    # Filter to workers who actually posted.
    present_workers = []
    for w in workers:
        if any(m.get("agent") == w and (m.get("message") or "").strip() for m in transcript):
            present_workers.append(w)
        else:
            summary["skipped"].append(w)

    # Compute a shared RT context block (judge summary, GATEs, score leaderboard)
    # included in every batch/single prompt so the model can spot DERIVE skills
    # that span agents without seeing unbounded raw transcript.
    rt_context = _build_rt_context(transcript, scores_by_agent, digest)

    if batch_size <= 1:
        for worker in present_workers:
            _observe_one_and_write(worker, rt_id, transcript, scores_by_agent, digest,
                                   summary, rt_context)
        summary["skills_observed"] = _dedup_skills(summary["skills_observed"])
        return summary

    # Batched path
    for chunk_start in range(0, len(present_workers), batch_size):
        chunk = present_workers[chunk_start:chunk_start + batch_size]
        try:
            batch_result = _observe_batch(rt_id, chunk, transcript, scores_by_agent,
                                          digest, rt_context)
        except Exception as e:  # noqa: BLE001
            logger.warning("observer: batch failed for %s (rt %s): %s — falling back to singles",
                           ",".join(chunk), rt_id[:12], e)
            for worker in chunk:
                _observe_one_and_write(worker, rt_id, transcript, scores_by_agent, digest,
                                       summary, rt_context)
            continue

        obs_by_agent = batch_result.get("obs", {})
        batch_skills = batch_result.get("skills", [])
        if batch_skills:
            summary["skills_observed"].extend(batch_skills)

        for worker in chunk:
            obs = obs_by_agent.get(worker)
            if obs is None:
                # Batch returned nothing for this agent — try single-agent fallback.
                logger.info("observer: batch had no entry for %s — single retry", worker)
                _observe_one_and_write(worker, rt_id, transcript, scores_by_agent, digest,
                                       summary, rt_context)
                continue
            try:
                _write_obs(worker, rt_id, obs)
                summary["observed"].append(worker)
                logger.info("observer: wrote obs-%s.json for %s (batched)", rt_id[:12], worker)
            except Exception as e:  # noqa: BLE001
                summary["errors"].append({"agent": worker, "error": f"write: {e}"[:200]})

    summary["skills_observed"] = _dedup_skills(summary["skills_observed"])
    logger.info("observer: skills_observed=%d (after dedup) for RT %s",
                len(summary["skills_observed"]), rt_id[:12])
    return summary


def _observe_one_and_write(
    worker: str,
    rt_id: str,
    transcript: list[dict],
    scores_by_agent: dict,
    digest: dict | None,
    summary: dict,
    rt_context: str,
) -> None:
    try:
        result = _observe_agent(rt_id, worker, transcript, scores_by_agent, digest, rt_context)
        if result is None:
            if worker not in summary["skipped"]:
                summary["skipped"].append(worker)
            return
        obs = result.get("obs")
        skills = result.get("skills") or []
        if skills:
            summary["skills_observed"].extend(skills)
        if obs is None:
            return
        _write_obs(worker, rt_id, obs)
        summary["observed"].append(worker)
        logger.info("observer: wrote obs-%s.json for %s", rt_id[:12], worker)
    except Exception as e:  # noqa: BLE001
        summary["errors"].append({"agent": worker, "error": str(e)[:200]})
        logger.warning("observer: failed for %s (rt %s): %s", worker, rt_id[:12], e)


# ── Internals ───────────────────────────────────────────────────────────────

def _observe_agent(
    rt_id: str,
    agent: str,
    transcript: list[dict],
    scores_by_agent: dict,
    digest: dict | None,
    rt_context: str,
) -> dict | None:
    """Build the Sonnet prompt for one agent, call Sonnet, parse JSON.

    Returns None if the agent produced no substantive posts in this RT.
    Returns {"obs": <obs_dict>, "skills": [<skill_dict>, ...]} on success.
    """
    agent_posts = [
        m for m in transcript
        if m.get("agent") == agent and m.get("message", "").strip()
    ]
    if not agent_posts:
        return None

    post_count = len(agent_posts)
    agent_text = _render_posts(agent_posts, who=agent)

    # Peer references: what other workers said that mentions this agent.
    peer_lines = _peer_references(agent, transcript)

    # Judge feedback: anything the judge wrote that references this agent.
    judge_lines = _judge_lines_about(agent, transcript)

    scores = _normalize_scores(scores_by_agent.get(agent) or _score_from_digest(agent, digest))

    prompt = _build_prompt(
        agent=agent,
        post_count=post_count,
        scores=scores,
        agent_text=agent_text,
        peer_lines=peer_lines,
        judge_lines=judge_lines,
        rt_context=rt_context,
    )

    raw = _call_sonnet(prompt)
    parsed = _parse_observation_json(raw)
    if parsed is None:
        # Preserve whatever we can — write a minimal skeleton so the review
        # loop has a record, but flag it as unparsed.
        logger.warning("observer: could not parse JSON for %s (rt %s); writing skeleton",
                       agent, rt_id[:12])
        parsed = {
            "observations": {
                "cognitive_moves": [],
                "rhetorical_moves": [],
                "evidence_practice": [],
                "engagement_pattern": "",
                "peer_references": _structure_peer_refs(peer_lines),
                "judge_feedback": judge_lines[:10],
            },
            "parse_error": True,
            "raw_snippet": (raw or "")[:600],
        }

    # Always normalize the envelope.
    obs = {
        "rt_id": rt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "scores": scores,
        "post_count": post_count,
        "observations": _ensure_obs_shape(parsed.get("observations", parsed)),
    }
    if parsed.get("parse_error"):
        obs["parse_error"] = True
        obs["raw_snippet"] = parsed.get("raw_snippet", "")

    # Skills for single-agent path — stamp source_rt so the runner can trace.
    raw_skills = parsed.get("skills_observed") or []
    skills = _normalize_skills(raw_skills, rt_id)
    return {"obs": obs, "skills": skills}


def _observe_batch(
    rt_id: str,
    agents: list[str],
    transcript: list[dict],
    scores_by_agent: dict,
    digest: dict | None,
    rt_context: str,
) -> dict:
    """Observe multiple agents in a single Sonnet call (up to 3 recommended).

    Returns {"obs": {agent_name: obs_dict}, "skills": [...]}. Missing agents
    (no posts, or not in Sonnet's response) are absent from obs — caller falls
    back to single-agent observation for those. Skills come from the whole
    batch (DERIVE synthesis is cross-agent).
    """
    if not agents:
        return {"obs": {}, "skills": []}

    agent_blocks: list[str] = []
    per_agent_meta: dict[str, dict] = {}
    for agent in agents:
        agent_posts = [
            m for m in transcript
            if m.get("agent") == agent and (m.get("message") or "").strip()
        ]
        if not agent_posts:
            continue
        agent_text = _render_posts(agent_posts, who=agent)
        peer_lines = _peer_references(agent, transcript)
        judge_lines = _judge_lines_about(agent, transcript)
        scores = _normalize_scores(scores_by_agent.get(agent) or _score_from_digest(agent, digest))

        per_agent_meta[agent] = {
            "post_count": len(agent_posts),
            "scores": scores,
            "peer_lines": peer_lines,
            "judge_lines": judge_lines,
        }

        peer_block = "\n".join(f"- [{r['by']}] {r['text']}" for r in peer_lines) or "(none)"
        judge_block = "\n".join(f"- {line}" for line in judge_lines) or "(none)"
        score_line = (
            f"novelty={scores.get('novelty')}, accuracy={scores.get('accuracy')}, "
            f"impact={scores.get('impact')}, challenge={scores.get('challenge')}, "
            f"total={scores.get('total')}"
        )
        agent_blocks.append(
            f"=====\nAGENT: {agent}\nPOSTS THIS RT: {len(agent_posts)}\nSCORES: {score_line}\n"
            f"\nAGENT'S POSTS:\n{agent_text}\n"
            f"\nPEER REFERENCES:\n{peer_block}\n"
            f"\nJUDGE LINES MENTIONING THE AGENT:\n{judge_block}\n"
        )

    if not per_agent_meta:
        return {"obs": {}, "skills": []}

    prompt = _build_batch_prompt(list(per_agent_meta.keys()), agent_blocks, rt_context)
    raw = _call_sonnet(prompt)
    parsed = _parse_observation_json(raw)

    if parsed is None or not isinstance(parsed, dict):
        logger.warning("observer: batch JSON parse failed (rt %s); caller will retry singles",
                       rt_id[:12])
        return {"obs": {}, "skills": []}

    # Expect either {"agents": {name: {observations: ...}}, "skills_observed": [...]}
    # or {name: {observations: ...}}.
    agent_map = parsed.get("agents") if isinstance(parsed.get("agents"), dict) else parsed
    if not isinstance(agent_map, dict):
        return {"obs": {}, "skills": []}

    out: dict = {}
    now = datetime.now(timezone.utc).isoformat()
    for agent, meta in per_agent_meta.items():
        entry = agent_map.get(agent)
        if not isinstance(entry, dict):
            continue
        observations = entry.get("observations", entry)
        out[agent] = {
            "rt_id": rt_id,
            "timestamp": now,
            "agent": agent,
            "scores": meta["scores"],
            "post_count": meta["post_count"],
            "observations": _ensure_obs_shape(observations),
            "batched": True,
        }

    # Batch-level skills — top-level key, not per-agent (DERIVE is cross-agent).
    raw_skills = parsed.get("skills_observed") or []
    # Back-compat: some model outputs place skills under a top-level "skills" key.
    if not raw_skills and isinstance(parsed.get("skills"), list):
        raw_skills = parsed["skills"]
    skills = _normalize_skills(raw_skills, rt_id)
    return {"obs": out, "skills": skills}


def _render_posts(posts: list[dict], who: str) -> str:
    lines = []
    for m in posts:
        text = (m.get("message") or "").strip()
        if not text:
            continue
        round_num = m.get("round", "?")
        lines.append(f"[{who.upper()} round {round_num}]\n{text}")
    out = "\n\n".join(lines)
    if len(out) > MAX_TRANSCRIPT_CHARS:
        out = out[:MAX_TRANSCRIPT_CHARS] + "\n\n[TRUNCATED]"
    return out


def _peer_references(agent: str, transcript: list[dict]) -> list[dict]:
    """Return messages from OTHER agents that mention this agent by name."""
    name_re = re.compile(rf"\b{re.escape(agent)}\b", re.IGNORECASE)
    refs: list[dict] = []
    for m in transcript:
        other = m.get("agent")
        if not other or other == agent or other in ("runner", "judge"):
            continue
        text = m.get("message") or ""
        if not name_re.search(text):
            continue
        # Extract at most the sentence containing the name.
        snippet = _sentence_around(text, name_re)
        refs.append({"by": other, "text": snippet[:280], "round": m.get("round")})
        if len(refs) >= 15:
            break
    return refs


def _sentence_around(text: str, name_re: re.Pattern) -> str:
    # Split into rough sentences and return the first containing the name.
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if name_re.search(sent):
            return sent.strip()
    return text.strip()[:280]


def _judge_lines_about(agent: str, transcript: list[dict]) -> list[str]:
    """Return judge messages mentioning the agent or GATE awards to them."""
    name_re = re.compile(rf"\b{re.escape(agent)}\b", re.IGNORECASE)
    lines: list[str] = []
    for m in transcript:
        if m.get("agent") != "judge":
            continue
        text = m.get("message") or ""
        if not text.strip():
            continue
        if not name_re.search(text):
            continue
        # Pull just the relevant sentence or bullet.
        snippet = _sentence_around(text, name_re)
        lines.append(snippet[:280])
        if len(lines) >= 10:
            break
    return lines


def _normalize_scores(raw) -> dict:
    default = {"novelty": None, "accuracy": None, "impact": None, "challenge": None, "total": None}
    if not isinstance(raw, dict):
        return default
    out = dict(default)
    # Accept common variants.
    for k in ("novelty", "accuracy", "impact", "challenge"):
        if k in raw and isinstance(raw[k], (int, float)):
            out[k] = raw[k]
    if "net_impact" in raw and out["impact"] is None and isinstance(raw["net_impact"], (int, float)):
        out["impact"] = raw["net_impact"]
    if "total" in raw and isinstance(raw["total"], (int, float)):
        out["total"] = raw["total"]
    elif "score" in raw and isinstance(raw["score"], (int, float)):
        out["total"] = raw["score"]
    else:
        vals = [out[k] for k in ("novelty", "accuracy", "impact", "challenge") if isinstance(out[k], (int, float))]
        if vals:
            out["total"] = sum(vals)
    return out


def _score_from_digest(agent: str, digest: dict | None) -> dict:
    if not digest:
        return {}
    scoring = digest.get("scoring") or []
    if isinstance(scoring, dict):
        scoring = scoring.get("scores", [])
    for s in scoring or []:
        if isinstance(s, dict) and s.get("agent") == agent:
            return s
    return {}


def _structure_peer_refs(raw_refs: list[dict]) -> list[dict]:
    return [{"by": r.get("by", ""), "text": r.get("text", "")} for r in raw_refs][:10]


def _ensure_obs_shape(obs: dict) -> dict:
    """Guarantee all expected observation keys exist even if Sonnet omitted some."""
    obs = obs if isinstance(obs, dict) else {}
    out = {
        "cognitive_moves": _as_str_list(obs.get("cognitive_moves")),
        "rhetorical_moves": _as_str_list(obs.get("rhetorical_moves")),
        "evidence_practice": _as_str_list(obs.get("evidence_practice")),
        "engagement_pattern": str(obs.get("engagement_pattern") or "").strip(),
        "peer_references": _as_peer_list(obs.get("peer_references")),
        "judge_feedback": _as_str_list(obs.get("judge_feedback")),
    }
    return out


def _as_str_list(val) -> list[str]:
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str) and val.strip():
        return [val.strip()]
    return []


def _as_peer_list(val) -> list[dict]:
    if not isinstance(val, list):
        return []
    out = []
    for item in val:
        if isinstance(item, dict):
            by = str(item.get("by") or item.get("agent") or "").strip()
            text = str(item.get("text") or item.get("quote") or "").strip()
            if by or text:
                out.append({"by": by, "text": text[:280]})
        elif isinstance(item, str) and item.strip():
            out.append({"by": "", "text": item.strip()[:280]})
    return out[:10]


# ── RT context (shared preamble for skill-extraction visibility) ────────────

def _build_rt_context(
    transcript: list[dict],
    scores_by_agent: dict,
    digest: dict | None,
) -> str:
    """Build a compact RT-wide preamble for DERIVE-skill visibility.

    Contains: topic (if in digest), score leaderboard, judge GATE lines,
    judge summary / final verdict lines, and the most-cited rounds. Capped
    at MAX_RT_CONTEXT_CHARS so the per-agent budget stays bounded.
    """
    parts: list[str] = []

    topic = (digest or {}).get("topic") or (digest or {}).get("directive") or ""
    if topic:
        parts.append(f"TOPIC: {str(topic)[:400]}")

    # Score leaderboard — cheap cross-agent signal.
    score_rows = []
    for agent, s in (scores_by_agent or {}).items():
        total = s.get("total", s.get("score", "?"))
        nov = s.get("novelty", "?")
        acc = s.get("accuracy", "?")
        imp = s.get("impact", s.get("net_impact", "?"))
        cha = s.get("challenge", "?")
        score_rows.append(f"  {agent:8s}  total={total}  nov={nov} acc={acc} imp={imp} cha={cha}")
    if score_rows:
        parts.append("SCORE LEADERBOARD:\n" + "\n".join(score_rows))

    # Judge lines containing GATE:, HALT:, SUMMARY:, VERDICT: — the cross-cutting signals.
    judge_signals: list[str] = []
    for m in transcript:
        if m.get("agent") != "judge":
            continue
        text = (m.get("message") or "").strip()
        if not text:
            continue
        for keyword in ("GATE:", "HALT:", "SUMMARY:", "VERDICT:", "FINAL:"):
            if keyword in text:
                # Take the sentence containing the keyword, not the whole judge post.
                sentences = re.split(r"(?<=[.!?])\s+", text)
                for sent in sentences:
                    if keyword in sent:
                        judge_signals.append(sent.strip()[:300])
                        break
                break
    if judge_signals:
        parts.append("JUDGE SIGNALS:\n" + "\n".join(f"- {s}" for s in judge_signals[:12]))

    # Cross-agent rebuttal pointers — lines where one worker names another by
    # name and includes a verb hint ("challenge", "counter", "disagree", "build on").
    cross_refs: list[str] = []
    hint_re = re.compile(r"\b(challenge|counter|disagree|build on|steelman|rebut|push back|concede)",
                         re.IGNORECASE)
    workers = {a for a in (scores_by_agent or {}).keys()}
    for m in transcript:
        agent = m.get("agent")
        if agent in (None, "runner", "judge", "assistant"):
            continue
        text = (m.get("message") or "").strip()
        if not text or not hint_re.search(text):
            continue
        for other in workers:
            if other == agent:
                continue
            if re.search(rf"\b{re.escape(other)}\b", text, re.IGNORECASE):
                snippet = text[:200].replace("\n", " ")
                cross_refs.append(f"- [{agent} → {other}] {snippet}")
                break
        if len(cross_refs) >= 10:
            break
    if cross_refs:
        parts.append("CROSS-AGENT REBUTTALS (sample):\n" + "\n".join(cross_refs))

    out = "\n\n".join(parts)
    if len(out) > MAX_RT_CONTEXT_CHARS:
        out = out[:MAX_RT_CONTEXT_CHARS] + "\n[TRUNCATED]"
    return out or "(no RT context available)"


# ── Skill normalization + dedup ─────────────────────────────────────────────

def _normalize_skills(raw: list, rt_id: str) -> list[dict]:
    """Coerce observer skill output to the canonical schema, drop malformed entries."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        skill_type = str(item.get("type") or "").strip().upper()
        if not title or not pattern or skill_type not in ("CAPTURE", "FIX", "DERIVE"):
            continue
        agent_field = item.get("agent")
        if isinstance(agent_field, list):
            agent_str = ",".join(str(a).strip() for a in agent_field if str(a).strip())
        else:
            agent_str = str(agent_field or "").strip()
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            tags = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tags = []
        out.append({
            "title": title[:160],
            "type": skill_type,
            "agent": agent_str[:200],
            "pattern": pattern[:1200],
            "when_to_apply": str(item.get("when_to_apply") or "").strip()[:500],
            "structural_category": str(item.get("structural_category") or "").strip(),
            "trigger_phase": str(item.get("trigger_phase") or "").strip(),
            "primary_actor": str(item.get("primary_actor") or "").strip(),
            "problem_nature": str(item.get("problem_nature") or "").strip(),
            "agent_dynamic": str(item.get("agent_dynamic") or "").strip(),
            "tags": tags[:8],
            "one_liner": str(item.get("one_liner") or "").strip()[:240],
            "source_rt": rt_id,
        })
    return out


def _dedup_skills(skills: list[dict]) -> list[dict]:
    """Merge near-duplicate skills by title token-Jaccard ≥ 0.6.

    When two skills match, keep the one with the longer pattern+when_to_apply
    (richer description) and mark the merged one via recurrence_count.
    """
    if not skills:
        return []
    kept: list[dict] = []
    for s in skills:
        s_tokens = {w.lower().strip(".,;:!?") for w in s["title"].split() if w}
        merged = False
        for k in kept:
            k_tokens = {w.lower().strip(".,;:!?") for w in k["title"].split() if w}
            if not s_tokens or not k_tokens:
                continue
            overlap = len(s_tokens & k_tokens) / len(s_tokens | k_tokens)
            if overlap >= 0.6:
                merged = True
                # Keep the richer entry — replace in place if the new one has more body.
                s_body = len(s.get("pattern", "")) + len(s.get("when_to_apply", ""))
                k_body = len(k.get("pattern", "")) + len(k.get("when_to_apply", ""))
                if s_body > k_body:
                    recurrence = k.get("recurrence_count", 0) + 1
                    s["recurrence_count"] = recurrence
                    kept[kept.index(k)] = s
                else:
                    k["recurrence_count"] = k.get("recurrence_count", 0) + 1
                break
        if not merged:
            kept.append(s)
    return kept


# ── Sonnet call ─────────────────────────────────────────────────────────────

_SKILL_SCHEMA_DOC = """SKILLS SCHEMA (one array entry per extracted skill):
  "title":               <short descriptive name>
  "type":                "CAPTURE" | "FIX" | "DERIVE"
                           CAPTURE = observed technique worth reusing
                           FIX     = anti-pattern + correction
                           DERIVE  = synthesis that emerged across multiple agents
  "agent":               <originating agent, or comma-joined list for DERIVE>
  "pattern":             <the technique, with file:line or function() refs if present in transcript>
  "when_to_apply":       <concrete future conditions — NOT this-RT-specific>
  "structural_category": state-boundary | signal-integrity | compound-failure | mechanism-policy |
                         affordance-capacity | process-workflow | data-pipeline | testing-verification
  "trigger_phase":       system-design | code-review | debugging | policy-governance | implementation
  "primary_actor":       individual-contributor | reviewer | architect | system-prompter
  "problem_nature":      state-lifecycle | calibration-metric | dependency-sequencing |
                         cognitive-framing | interface-contract | data-integrity
  "agent_dynamic":       convergence | synthesis | reframing    (required when type=DERIVE)
  "tags":                <array of 3-5 searchable keywords>
  "one_liner":           <one plain-English sentence summarizing the concept>

Rules for skills_observed:
- Target 8-15 total skills for the batch — quality over quantity.
- Every field populated — no empty strings, no nulls.
- Titles must start with an imperative verb (Use, Apply, Check, Add, Avoid, Ensure, Validate,
  Prefer, Replace, Scan, Flag, Track, Detect, Call, Run, Test, Skip, Merge, Split, Wrap, Inject).
- Include at least one concrete code reference in title or pattern (backtick-quoted name,
  function(), file:line, or CamelCase identifier).
- DERIVE must name ≥2 contributing agents in the "agent" field."""


def _build_prompt(
    agent: str,
    post_count: int,
    scores: dict,
    agent_text: str,
    peer_lines: list[dict],
    judge_lines: list[str],
    rt_context: str,
) -> str:
    peer_block = "\n".join(
        f"- [{r['by']}] {r['text']}" for r in peer_lines
    ) or "(none)"
    judge_block = "\n".join(f"- {line}" for line in judge_lines) or "(none)"

    score_line = (
        f"novelty={scores.get('novelty')}, accuracy={scores.get('accuracy')}, "
        f"impact={scores.get('impact')}, challenge={scores.get('challenge')}, "
        f"total={scores.get('total')}"
    )

    return f"""You are a per-RT observer. Two duties in one pass:
  (1) record what THIS agent did (observations)
  (2) extract CAPTURE/FIX/DERIVE skills from the RT (skills_observed)

Do NOT assign trait labels. Do NOT guess motivation. Describe observed moves
with specifics from the transcript.

RT CONTEXT (shared across all agents this RT):
{rt_context}

=====
AGENT: {agent}
POSTS THIS RT: {post_count}
SCORES: {score_line}

AGENT'S POSTS (this RT only):
{agent_text}

PEER REFERENCES (what others said about the agent):
{peer_block}

JUDGE LINES MENTIONING THE AGENT:
{judge_block}

=====

Return a SINGLE JSON object with this exact shape (no prose before or after):

{{
  "observations": {{
    "cognitive_moves": [ "<verb-led description with quote or file:line if present>", ... ],
    "rhetorical_moves": [ "<verb-led description>", ... ],
    "evidence_practice": [ "<what data/citation/derivation the agent used>", ... ],
    "engagement_pattern": "<one sentence: how they posted across rounds — held / escalated / retreated / PASSed>",
    "peer_references": [ {{"by": "<other agent>", "text": "<short direct quote>"}}, ... ],
    "judge_feedback": [ "<short direct judge quote>", ... ]
  }},
  "skills_observed": [
    {{ "title": "...", "type": "CAPTURE|FIX|DERIVE", "agent": "...", "pattern": "...",
       "when_to_apply": "...", "structural_category": "...", "trigger_phase": "...",
       "primary_actor": "...", "problem_nature": "...", "agent_dynamic": "...",
       "tags": ["...","..."], "one_liner": "..." }},
    ...
  ]
}}

Observation rules:
- Each list item 10-200 chars. Use verbs (inverted, anchored, deferred, named, cited, challenged, conceded, pivoted).
- Quote exactly when you say "quote" — copy 3-10 words from the transcript, in quotation marks.
- Empty categories are fine; return [] rather than inventing items.
- NO trait labels. NO "this shows X pattern". Describe the act, not the identity.
- engagement_pattern is one sentence describing post-by-post arc, not a judgment.

{_SKILL_SCHEMA_DOC}
"""


def _build_batch_prompt(agents: list[str], agent_blocks: list[str], rt_context: str) -> str:
    """Build a prompt covering multiple agents + shared skills extraction in one call."""
    joined = "\n\n".join(agent_blocks)
    agent_keys = ", ".join(f'"{a}"' for a in agents)

    return f"""You are a per-RT observer. Two duties in one pass:
  (1) record what EACH agent in this batch did (observations, per-agent)
  (2) extract CAPTURE/FIX/DERIVE skills from the RT (skills_observed, one flat list)

Do NOT assign trait labels. Do NOT guess motivation. Describe observed moves
with specifics from the transcript. Each agent is independent — do not reuse
phrasing or quotes between them in observations.

RT CONTEXT (shared across all agents this RT):
{rt_context}

=====

{joined}

=====

Return a SINGLE JSON object with this exact shape (no prose before or after):

{{
  "agents": {{
    {agent_keys}: {{
      "observations": {{
        "cognitive_moves": [ "<verb-led description, quote 3-10 words when possible>", ... ],
        "rhetorical_moves": [ "<verb-led description>", ... ],
        "evidence_practice": [ "<what data/citation the agent used>", ... ],
        "engagement_pattern": "<one sentence — how they posted across rounds>",
        "peer_references": [ {{"by": "<other agent>", "text": "<short direct quote>"}}, ... ],
        "judge_feedback": [ "<short direct judge quote>", ... ]
      }}
    }}
  }},
  "skills_observed": [
    {{ "title": "...", "type": "CAPTURE|FIX|DERIVE", "agent": "...", "pattern": "...",
       "when_to_apply": "...", "structural_category": "...", "trigger_phase": "...",
       "primary_actor": "...", "problem_nature": "...", "agent_dynamic": "...",
       "tags": ["...","..."], "one_liner": "..." }},
    ...
  ]
}}

Observation rules:
- List items 10-200 chars; lead with a verb (inverted, anchored, deferred, named, cited, challenged, conceded, pivoted).
- Quote exactly when you say "quote" — copy 3-10 words from the transcript, in quotation marks.
- Empty categories are fine; return [] rather than inventing.
- Each agent's observations MUST be distinct — no verb or phrase reused across agents.
- NO trait labels. NO "this shows X pattern". Describe the act, not the identity.
- engagement_pattern is one sentence describing the post-by-post arc, not a judgment.
- No prose before or after the JSON object.

{_SKILL_SCHEMA_DOC}
"""


def _call_sonnet(prompt: str) -> str:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet",
             "--no-session-persistence", "--output-format", "text",
             "--disable-slash-commands", "--dangerously-skip-permissions",
             "--max-budget-usd", MAX_BUDGET_USD],
            input=prompt, capture_output=True, text=True, timeout=SONNET_TIMEOUT_SEC,
            cwd=str(Path(__file__).parent.parent.parent), encoding="utf-8", errors="replace", env=env,
        )
    except subprocess.TimeoutExpired:
        logger.error("observer: sonnet call timed out (%ds)", SONNET_TIMEOUT_SEC)
        return ""
    if result.returncode != 0:
        logger.warning("observer: sonnet exit %d: %s", result.returncode, (result.stderr or "")[:200])
        return ""
    return (result.stdout or "").strip()


def _parse_observation_json(raw: str) -> dict | None:
    if not raw:
        return None
    # Try direct parse.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try extracting the first {...} block.
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None


# ── Write ───────────────────────────────────────────────────────────────────

def _bump_trait_counter(agent: str) -> None:
    """Increment ``obs_since_last_trait_review`` in the agent's case_notes.

    Called after a successful obs file write so the therapist's trait-review
    branch fires once TRAIT_REVIEW_THRESHOLD observations have accumulated.
    Guarded: a case_notes write failure never breaks observation persistence.
    """
    try:
        from amatelier.engine.therapist import _load_case_notes, _save_case_notes
        notes = _load_case_notes(agent)
        notes["obs_since_last_trait_review"] = int(
            notes.get("obs_since_last_trait_review", 0)
        ) + 1
        _save_case_notes(agent, notes)
    except Exception as e:  # noqa: BLE001
        logger.warning("observer: trait counter bump failed for %s: %s", agent, e)


def _write_obs(agent: str, rt_id: str, obs: dict) -> Path:
    """Write observation file to agent's observations directory (amatelier user_data).

    Side effect: on successful write, bumps the agent's trait-review counter
    so the therapist can eventually fire its trait-review branch.
    """
    obs_dir = paths.user_agent_dir(agent) / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    path = obs_dir / f"obs-{rt_id}.json"
    path.write_text(json.dumps(obs, indent=2, ensure_ascii=False), encoding="utf-8")
    _bump_trait_counter(agent)
    return path


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
