"""Tests for feedback submission available in user workspaces."""
from petship.extensions import db
from petship.models.platform import PlatformFeedback
from petship.models.user import User
from petship.seed import seed_data


def test_user_can_submit_named_star_feedback(client, app):
    seed_data()
    user = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"},
    )

    response = client.post(
        "/feedback",
        data={
            "name": user.full_name,
            "rating": "4",
            "body": "The adoption tracking is helpful.",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Thank you for sharing your feedback." in response.data
    feedback = db.session.scalar(db.select(PlatformFeedback))
    assert feedback is not None
    assert feedback.user_id == user.id
    assert feedback.name == user.full_name
    assert feedback.rating == 4
    assert feedback.body == "The adoption tracking is helpful."


def test_public_feedback_is_available_from_footer_and_accepts_guest(client, app):
    response = client.get("/")
    assert response.status_code == 200
    assert b'href="/feedback">Feedback</a>' in response.data

    feedback_page = client.get("/feedback")
    assert feedback_page.status_code == 200
    assert b"Share your feedback" in feedback_page.data

    response = client.post(
        "/feedback",
        data={"name": "Website visitor", "rating": "5", "body": "Great experience!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Thank you for sharing your feedback." in response.data
    feedback = db.session.scalar(db.select(PlatformFeedback))
    assert feedback is not None
    assert feedback.user_id is None
    assert feedback.name == "Website visitor"
    assert feedback.rating == 5


def test_feedback_requires_valid_rating_and_body(client, app):
    client.post("/feedback", data={"name": "Visitor", "rating": "6", "body": ""})
    assert db.session.scalar(db.select(PlatformFeedback)) is None
