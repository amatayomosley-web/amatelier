"""The therapist prices a seat the way the runner charges it, and keeps its reports
out of the bundled package, one file per partial run."""

from __future__ import annotations

from amatelier.engine import therapist

CONFIG = {
    "competition": {"entry_fees": {"haiku": 5, "flash": 5, "sonnet": 8, "opus": 15}},
    "gemini": {"model": "gemini-3-flash-preview"},
    "team": {"workers": {
        "elena": {"model": "claude-sonnet-4-20250514", "backend": "claude"},
        "clare": {"model": "claude-haiku-4-5-20251001", "backend": "claude"},
    }},
}


def test_seat_fee_matches_the_runner(monkeypatch):
    monkeypatch.setattr(therapist, "_load_active_config", lambda: CONFIG)
    assert therapist._seat_fee("elena") == ("sonnet", 8)
    assert therapist._seat_fee("clare") == ("haiku", 5)
    assert therapist._seat_fee("naomi") == ("sonnet", 8)  # a Gemini 3 Flash seat is charged the sonnet fee


def test_brief_shows_the_real_fee(monkeypatch):
    monkeypatch.setattr(therapist, "_load_active_config", lambda: CONFIG)
    brief = therapist._build_agent_brief("elena", {"claude": "", "memory": "", "metrics": {"avg_score": 6}})
    assert "entry fee: -8 sparks per RT" in brief
    assert "Net per RT: -2.0" in brief


def test_reports_go_to_user_data_one_file_per_partial_run(monkeypatch, tmp_path):
    monkeypatch.setattr(therapist, "WRITE_ROOT", tmp_path)
    digest = {"contributions": {"runner": 3, "judge": 2, "elena": 4, "simon": 4, "naomi": 3}}
    one = therapist._report_path("rt1", digest, ["simon"])
    full = therapist._report_path("rt1", digest, ["naomi", "elena", "simon"])
    assert one == tmp_path / "reports" / "therapist-rt1-simon.md"
    assert full == tmp_path / "reports" / "therapist-rt1.md"
    assert therapist.SUITE_ROOT not in one.parents
