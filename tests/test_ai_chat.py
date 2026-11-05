"""Task 28 tests: Pawly chatbot, fallback responses, and chat history."""
from __future__ import annotations

from petship.extensions import db
from petship.models.chat import ChatMessage, Conversation
from petship.seed import seed_data
from petship.services.ai import ai_enabled, care_chat


def login_agalya(client):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})


# ---- Fallback behaviour (no Gemini key) ----
def test_ai_disabled_by_default(app):
    with app.app_context():
        assert ai_enabled() is False


def test_care_chat_fallback_is_relevant(app):
    with app.app_context():
        # Ear question -> ear-specific guidance that points to a vet.
        reply = care_chat("My cat is scratching her ears", "Mochi (cat)")
    assert "ear" in reply.lower()
    assert "vet" in reply.lower()  # safety guidance present


def test_care_chat_fallback_default_is_safe(app):
    with app.app_context():
        # An off-topic message falls through to the safe default.
        reply = care_chat("hello there", "Mochi (cat)")
    assert "Pawly" in reply
    assert "vet" in reply.lower()


# ---- Chat page ----
def test_chat_requires_login(client, app):
    seed_data()
    resp = client.get("/ai/chat", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_chat_page_does_not_render_pet_or_topic_sidebar(client, app):
    login_agalya(client)
    resp = client.get("/ai/chat")
    assert resp.status_code == 200
    assert b"Pawly" in resp.data
    assert b"Mochi" not in resp.data
    assert b"Popular topics" not in resp.data
    assert b"Your pets" not in resp.data


# ---- Sending messages ----
def test_send_creates_conversation_and_reply(client, app):
    login_agalya(client)
    resp = client.post("/ai/chat/send",
                       data={"message": "What should I feed my cat?"},
                       headers={"HX-Request": "true"})
    assert resp.status_code == 200
    # Both the question and an assistant answer are in the returned fragment.
    assert b"What should I feed my cat?" in resp.data
    assert b"chat-bubble assistant" in resp.data

    convo = db.session.scalar(db.select(Conversation))
    assert convo is not None
    assert len(convo.messages) == 2
    assert convo.messages[0].role == "user"
    assert convo.messages[1].role == "assistant"


def test_send_appends_to_existing_conversation(client, app):
    login_agalya(client)
    client.post("/ai/chat/send", data={"message": "First"}, headers={"HX-Request": "true"})
    convo = db.session.scalar(db.select(Conversation))
    client.post("/ai/chat/send",
                data={"message": "Second", "conversation_id": convo.id},
                headers={"HX-Request": "true"})
    db.session.refresh(convo)
    assert len(convo.messages) == 4  # 2 exchanges


def test_empty_message_ignored(client, app):
    login_agalya(client)
    resp = client.post("/ai/chat/send", data={"message": "  "},
                       headers={"HX-Request": "true"})
    assert resp.status_code == 204
    assert db.session.scalar(db.select(Conversation)) is None


def test_send_requires_login(client, app):
    seed_data()
    resp = client.post("/ai/chat/send", data={"message": "Hi"})
    assert resp.status_code == 403


# ---- History ----
def test_chat_history_lists_conversations(client, app):
    login_agalya(client)
    client.post("/ai/chat/send", data={"message": "Diet advice for Mochi"},
                headers={"HX-Request": "true"})
    resp = client.get("/ai/chat/history")
    assert resp.status_code == 200
    assert b"chat history" in resp.data.lower()
    assert b"Diet advice for Mochi" in resp.data


def test_open_existing_conversation(client, app):
    login_agalya(client)
    client.post("/ai/chat/send", data={"message": "Ear mites?"},
                headers={"HX-Request": "true"})
    convo = db.session.scalar(db.select(Conversation))
    resp = client.get(f"/ai/chat/{convo.id}")
    assert resp.status_code == 200
    assert b"Ear mites?" in resp.data


def test_cannot_open_others_conversation(client, app):
    login_agalya(client)
    client.post("/ai/chat/send", data={"message": "Mine"}, headers={"HX-Request": "true"})
    convo = db.session.scalar(db.select(Conversation))
    # Log in as a different seeded user.
    client.get("/auth/logout")
    client.post("/auth/login", data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})
    assert client.get(f"/ai/chat/{convo.id}").status_code == 404
