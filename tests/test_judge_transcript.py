"""The scorer sees the whole debate, blinded, and the whole briefing.

The old caps (1,200 characters per message, 20,000 in total, 3,000 of the
briefing) dropped the later phases of a debate. Agents are now scored under
reviewer labels with their names scrubbed, and research-window debate is not
scored.
"""

from __future__ import annotations

import json
import re

from amatelier.engine import judge_scorer as js

WORKERS = ["elena", "marcus", "clare"]


def _transcript():
    long_post = "Marcus is right about the ledger. " + ("detail " * 1500)  # ~10,500 chars
    return [
        {"agent": "runner", "message": "--- RESEARCH WINDOW ---"},
        {"agent": "elena", "message": "My findings before the debate: the ledger is wrong, says elena."},
        {"agent": "marcus", "message": "[[request: read the ledger file]]"},
        {"agent": "runner", "message": "ROUND 1: begin\nBUDGET STATUS: elena=3"},
        {"agent": "elena", "message": long_post},
        {"agent": "judge", "message": "Note to Elena and Clare: cite the file."},
        {"agent": "runner", "message": "--- FLOOR PHASE (Round 1) ---"},
        {"agent": "clare", "message": "FLOOR-MARKER: I side with Elena, not marcus."},
    ]


def test_whole_debate_blinded_and_research_debate_dropped():
    text, anon = js._format_transcript(_transcript())
    assert sorted(anon.values()) == sorted(WORKERS)
    assert "FLOOR-MARKER" in text                       # a floor-phase post is scored
    assert "My findings before the debate" not in text  # research-window debate is not
    assert "[[request: read the ledger file]]" in text  # a research-window lookup is
    assert "[Moderator]:" in text
    assert not re.search(r"\b(elena|marcus|clare)\b", text, re.IGNORECASE)
    longest = max(len(block) for block in text.split("\n\n["))
    assert longest > 8000                                # no longer cut at 1,200


def test_labels_map_back_to_real_names():
    _, anon = js._format_transcript(_transcript())
    raw = json.dumps({"scores": {
        label: {"novelty": 1, "accuracy": 1, "impact": 1, "challenge": 1,
                "reasoning": "r", "grand_insight": None}
        for label in anon
    }})
    parsed = js._parse_scores(raw, WORKERS, anon)
    assert sorted(parsed["scores"]) == sorted(WORKERS)
    assert all(parsed["scores"][w]["reasoning"] == "r" for w in WORKERS)


def test_scorer_gets_the_whole_briefing_and_a_blind_retry(monkeypatch, tmp_path):
    briefing = "Intro. " + ("canon line " * 400) + "\n## Moderator Priorities\nPRIORITY-MARKER for elena"
    assert briefing.index("PRIORITY-MARKER") > 3000
    prompts = []
    monkeypatch.setattr(js, "WRITE_ROOT", tmp_path)
    monkeypatch.setattr(js, "_call_sonnet", lambda p: prompts.append(p) or None)
    result = js.judge_score(briefing, _transcript(), WORKERS, "test-rt")
    assert result["status"] == "failed" and len(prompts) == 2
    first, retry = prompts
    assert "PRIORITY-MARKER" in first
    assert not re.search(r"\b(elena|marcus|clare)\b", first, re.IGNORECASE)
    assert not re.search(r"\b(elena|marcus|clare)\b", retry, re.IGNORECASE)
    assert "Reviewer A" in retry
