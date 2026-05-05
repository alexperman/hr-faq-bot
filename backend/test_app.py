"""
ReplyIQ - Test Suite
Run: cd backend && python -m pytest test_app.py -v
"""

import pytest
import sys
import os
import json
import tempfile
import shutil

# Ensure app module is importable
sys.path.insert(0, os.path.dirname(__file__))


# ─── Shared Temp KB Setup ─────────────────────────────────────────────────────
# We create ONE temp directory shared by all tests (class-level setup).
# Individual tests share state so full KB lifecycle tests work.

_TEMP_DIR = None

def _setup_temp_env():
    global _TEMP_DIR
    if _TEMP_DIR is None:
        _TEMP_DIR = tempfile.mkdtemp(prefix="replyiq_test_")
        kb_file = os.path.join(_TEMP_DIR, "knowledge_base.json")
        sessions_file = os.path.join(_TEMP_DIR, "sessions.json")
        with open(kb_file, "w") as f:
            json.dump({"documents": [], "qna_pairs": []}, f)
        with open(sessions_file, "w") as f:
            json.dump({}, f)
    return _TEMP_DIR


def _reset_kb():
    """Clear KB contents without destroying the file."""
    global _TEMP_DIR
    if _TEMP_DIR:
        kb_file = os.path.join(_TEMP_DIR, "knowledge_base.json")
        with open(kb_file, "w") as f:
            json.dump({"documents": [], "qna_pairs": []}, f)


@pytest.fixture(scope="module")
def app_with_temp_kb():
    """Patch app KB paths to use temp files, import once, reuse for all tests."""
    temp_dir = _setup_temp_env()
    kb_path = os.path.join(temp_dir, "knowledge_base.json")
    sessions_path = os.path.join(temp_dir, "sessions.json")

    # Import and patch
    import app as replyiq
    replyiq.KB_FILE = kb_path
    replyiq.SESSIONS_FILE = sessions_path
    replyiq.IS_RENDER = False  # prevent PORT env var from redirecting KB_FILE

    # Ensure clean state
    _reset_kb()

    replyiq.app.config["TESTING"] = True
    yield replyiq.app

    # Teardown
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass
    global _TEMP_DIR
    _TEMP_DIR = None


@pytest.fixture
def client(app_with_temp_kb):
    """Flask test client — each test gets a request-scoped context."""
    with app_with_temp_kb.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_between_tests():
    """Clear KB before each test so they don't leak state into each other."""
    _reset_kb()
    yield


# ─── HTML Page Routes ──────────────────────────────────────────────────────────

class TestHTMLPages:
    def test_index_serves(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"<!DOCTYPE" in r.data

    def test_index_alias_serves(self, client):
        r = client.get("/index")
        assert r.status_code == 200

    def test_presell_serves(self, client):
        r = client.get("/presell")
        assert r.status_code == 200

    def test_product_serves(self, client):
        r = client.get("/product")
        assert r.status_code == 200

    def test_success_serves(self, client):
        r = client.get("/success")
        assert r.status_code == 200

    def test_404_unknown_page(self, client):
        r = client.get("/nonexistent")
        assert r.status_code == 404


# ─── Knowledge Base API ────────────────────────────────────────────────────────

class TestKBAPI:

    def test_get_empty_kb(self, client):
        r = client.get("/api/kb")
        assert r.status_code == 200
        data = r.get_json()
        assert data["documents"] == []
        assert data["total_docs"] == 0
        assert data["total_chars"] == 0

    def test_get_kb_after_add(self, client):
        client.post("/api/kb/add",
                    json={"text": "A" * 100, "title": "Test Doc", "source": "test"})
        r = client.get("/api/kb")
        data = r.get_json()
        assert data["total_docs"] == 1
        assert data["total_chars"] == 100
        assert data["documents"][0]["title"] == "Test Doc"

    def test_add_valid_doc(self, client):
        r = client.post("/api/kb/add",
                        json={"text": "This is a valid HR policy document." * 5,
                              "title": "HR Policy",
                              "source": "manual"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "added"
        assert data["doc_count"] == 1
        assert "id" in data

    def test_add_doc_too_short(self, client):
        r = client.post("/api/kb/add",
                        json={"text": "Too short", "title": "Short"})
        assert r.status_code == 400
        assert b"too short" in r.data.lower()

    def test_add_doc_no_text(self, client):
        r = client.post("/api/kb/add", json={"title": "No content"})
        assert r.status_code == 400

    def test_add_duplicate_doc(self, client):
        payload = {"text": "Same content." * 20, "title": "Dup"}
        r1 = client.post("/api/kb/add", json=payload)
        r2 = client.post("/api/kb/add", json=payload)
        assert r2.get_json()["status"] == "exists"

    def test_remove_doc(self, client):
        r = client.post("/api/kb/add",
                        json={"text": "Content." * 20, "title": "To Remove"})
        doc_id = r.get_json()["id"]
        r = client.delete(f"/api/kb/remove/{doc_id}")
        assert r.get_json()["status"] == "removed"
        assert r.get_json()["doc_count"] == 0

    def test_remove_nonexistent_doc(self, client):
        r = client.delete("/api/kb/remove/fakeid123")
        assert r.status_code == 200
        assert r.get_json()["status"] == "removed"

    def test_remove_all_docs(self, client):
        for i in range(3):
            client.post("/api/kb/add",
                        json={"text": f"Doc {i} content." * 20,
                              "title": f"Doc {i}"})
        r = client.get("/api/kb")
        doc_id = r.get_json()["documents"][0]["id"]
        client.delete(f"/api/kb/remove/{doc_id}")
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 2


# ─── Ask API ───────────────────────────────────────────────────────────────────

class TestAskAPI:

    def test_ask_no_question(self, client):
        r = client.post("/api/ask", json={})
        assert r.status_code == 400

    def test_ask_empty_question(self, client):
        r = client.post("/api/ask", json={"question": "   "})
        assert r.status_code == 400

    def test_ask_no_groq_key_returns_demo(self, client):
        """When GROQ_API_KEY is not set, should return demo response."""
        r = client.post("/api/ask", json={"question": "What is HR policy?"})
        assert r.status_code == 200
        data = r.get_json()
        # No API key → demo mode
        assert data["source"] is None
        assert "answer" in data

    def test_ask_with_kb_context(self, client):
        """When KB has content, ask endpoint should use it."""
        client.post("/api/kb/add", json={
            "text": "Employees get 20 days of vacation per year. " * 5,
            "title": "Vacation Policy"
        })
        r = client.post("/api/ask", json={"question": "How much vacation do I get?"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["kb_doc_count"] == 1

    def test_ask_response_structure(self, client):
        r = client.post("/api/ask", json={"question": "Test question?"})
        assert r.status_code == 200
        data = r.get_json()
        for field in ["question", "answer", "kb_doc_count"]:
            assert field in data, f"Missing field: {field}"


class TestResetAPI:

    def test_reset_clears_kb(self, client):
        client.post("/api/kb/add",
                    json={"text": "Some content." * 20, "title": "Temp"})
        r = client.delete("/api/reset")
        assert r.get_json()["status"] == "reset"
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 0

    def test_reset_when_empty(self, client):
        r = client.delete("/api/reset")
        assert r.status_code == 200
        assert r.get_json()["status"] == "reset"


# ─── End-to-End Flows ─────────────────────────────────────────────────────────

class TestFlows:

    def test_full_kb_lifecycle(self, client):
        # 1. Start empty
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 0

        # 2. Add 3 docs
        for i in range(3):
            r = client.post("/api/kb/add", json={
                "text": f"Document {i} body content." * 10,
                "title": f"Doc {i}",
                "source": "test"
            })
            assert r.status_code == 200

        # 3. Verify 3 docs present
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 3

        # 4. Remove first doc
        first_id = r.get_json()["documents"][0]["id"]
        client.delete(f"/api/kb/remove/{first_id}")

        # 5. Verify 2 remain
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 2

        # 6. Reset all
        client.delete("/api/reset")
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 0

    def test_ask_before_and_after_adding_docs(self, client):
        # Ask with empty KB
        r1 = client.post("/api/ask", json={"question": "What is the PTO policy?"})
        assert r1.status_code == 200
        count_before = r1.get_json()["kb_doc_count"]

        # Add doc
        client.post("/api/kb/add", json={
            "text": "PTO policy: employees receive 15 days paid time off per year.",
            "title": "PTO Policy"
        })

        # Ask again
        r2 = client.post("/api/ask", json={"question": "What is the PTO policy?"})
        assert r2.status_code == 200
        count_after = r2.get_json()["kb_doc_count"]

        assert count_after == count_before + 1

    def test_page_load_then_api_work_together(self, client):
        # Load product page
        r = client.get("/product")
        assert r.status_code == 200

        # Interact with API
        client.post("/api/kb/add", json={
            "text": "Company holiday schedule for 2025. " * 5,
            "title": "Holidays"
        })
        r = client.get("/api/kb")
        assert r.get_json()["total_docs"] == 1

        # Load success page
        r = client.get("/success")
        assert r.status_code == 200
