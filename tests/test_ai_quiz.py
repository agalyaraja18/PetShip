"""Task 27 tests: compatibility quiz scoring, archetype, and flow."""
from __future__ import annotations

from petship.services.compatibility import (
    QUIZ_QUESTIONS,
    archetype,
    axis_label,
    score_axes,
)


# ---- Scoring ----
def test_score_axes_maps_answers():
    axes = score_axes({"activity": "relaxed", "space": "apartment",
                       "time": "high", "experience": "first_time"})
    assert axes["activity"] == 20
    assert axes["space"] == 30
    assert axes["time"] == 100
    assert axes["experience"] == 25


def test_score_axes_defaults_missing():
    axes = score_axes({})
    assert all(v == 50 for v in axes.values())


def test_scoring_is_deterministic():
    a = {"activity": "active", "space": "house", "time": "medium", "experience": "some"}
    assert score_axes(a) == score_axes(a)


# ---- Archetypes ----
def test_cosy_companion_archetype():
    axes = score_axes({"activity": "relaxed", "space": "apartment",
                       "time": "medium", "experience": "first_time"})
    result = archetype(axes)
    assert result["name"] == "Cosy Companion"
    assert len(result["best"]) == 3
    assert 0 <= result["readiness"] <= 100


def test_adventure_buddy_archetype():
    axes = score_axes({"activity": "very_active", "space": "house",
                       "time": "high", "experience": "experienced"})
    result = archetype(axes)
    assert result["name"] == "Adventure Buddy"


def test_family_pack_leader_archetype():
    axes = score_axes({"activity": "active", "space": "villa",
                       "time": "high", "experience": "some"})
    result = archetype(axes)
    assert result["name"] == "Family Pack Leader"


def test_axis_label_nearest():
    assert axis_label("activity", 20) == "Relaxed"
    assert axis_label("space", 100) == "Villa"
    assert axis_label("experience", 25) == "First-time"


# ---- Flow ----
def test_quiz_first_question_renders(client, app):
    resp = client.get("/ai/quiz/1")
    assert resp.status_code == 200
    assert b"typical day" in resp.data
    # Illustrated options present.
    assert b"Relaxed" in resp.data


def test_quiz_full_flow_to_result(client, app):
    # Answer every question, choosing options that yield a Cosy Companion.
    preferred = {"activity": "relaxed", "space": "apartment",
                 "time": "medium", "experience": "first_time"}
    total = len(QUIZ_QUESTIONS)
    for i, q in enumerate(QUIZ_QUESTIONS, start=1):
        qid = q["id"]
        # Preferred answer where it matters, else the first option.
        value = preferred.get(qid, q["options"][0][0])
        resp = client.post(f"/ai/quiz/{i}", data={qid: value, "action": "next"},
                           follow_redirects=False)
        assert resp.status_code == 302
    # The final step redirects to results.
    assert "/ai/quiz/results" in resp.headers["Location"]

    result = client.get("/ai/quiz/results")
    assert result.status_code == 200
    assert b"Cosy Companion" in result.data
    assert b"ready to adopt" in result.data
    assert b"Best pet types for you" in result.data
    assert b"img/pets/mochi.jpg" in result.data
    assert b"img/pets/pixie.jpg" in result.data
    assert b"img/pets/snow.jpg" in result.data
    assert b'<div class="best-type-art"></div>' not in result.data


def test_quiz_back_navigation(client, app):
    client.post("/ai/quiz/1", data={"activity": "active", "action": "next"})
    resp = client.post("/ai/quiz/2", data={"space": "house", "action": "back"},
                       follow_redirects=False)
    assert "/ai/quiz/1" in resp.headers["Location"]


def test_quiz_results_with_no_answers(client, app):
    # Defaults to a mid-profile archetype without errors.
    resp = client.get("/ai/quiz/results")
    assert resp.status_code == 200


def test_quiz_has_ten_questions():
    assert len(QUIZ_QUESTIONS) == 10
    ids = {q["id"] for q in QUIZ_QUESTIONS}
    # The four scoring axes are still present among the ten questions.
    assert {"activity", "space", "time", "experience"} <= ids
