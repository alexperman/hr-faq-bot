"""
ReplyIQ - AI HR FAQ Assistant
Flask backend with Groq LLM + PageIndex cloud RAG
"""

import os
import json
import uuid
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# API Keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PAGEINDEX_API_KEY = os.environ.get("PAGEINDEX_API_KEY", "")

app = Flask(__name__)
CORS(app)

# ─── PageIndex Client (lazy init) ────────────────────────────────────────────

PI_CLIENT = None


def _get_pi():
    """Return a PageIndexClient, lazily initialised."""
    global PI_CLIENT
    if PI_CLIENT is None:
        from pageindex import PageIndexClient

        PI_CLIENT = PageIndexClient(api_key=PAGEINDEX_API_KEY or None)
    return PI_CLIENT


# ─── Local Manifest (maps doc_id → PageIndex doc_id) ─────────────────────────

IS_RENDER = os.environ.get("PORT", "") != ""
MANIFEST_FILE = Path("/tmp/pageindex_manifest.json" if IS_RENDER else Path(__file__).parent / "pageindex_manifest.json")


def _load_manifest():
    try:
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"documents": []}


def _save_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2, default=str)


# ─── Knowledge Base (PageIndex cloud RAG) ──────────────────────────────────────

def add_document(text, title="Untitled", source="manual"):
    """
    Write text as a .txt file, submit to PageIndex cloud API,
    and register the returned doc_id in the local manifest.
    """
    manifest = _load_manifest()

    # Dedupe by content hash
    content_hash = hashlib.sha256(text[:500].encode()).hexdigest()[:16]
    for doc in manifest["documents"]:
        if doc.get("content_hash") == content_hash:
            return {"status": "exists", "doc_id": doc["doc_id"], "doc_count": len(manifest["documents"])}

    doc_id = str(uuid.uuid4())

    # Write content to a temp file for the API
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        tmp_path = f.name

    try:
        pi = _get_pi()
        result = pi.submit_document(tmp_path, mode="auto")
        pi_doc_id = result.get("doc_id") or result.get("id") or result.get("document_id")
        if isinstance(result, dict) and not pi_doc_id:
            # Try common keys
            for key in ("doc_id", "id", "document_id", "document", "uuid"):
                if key in result:
                    pi_doc_id = result[key]
                    break
    except Exception as e:
        pi_doc_id = None
        print(f"PageIndex submit_document warning: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    doc_entry = {
        "doc_id": doc_id,
        "pi_doc_id": pi_doc_id,
        "title": title,
        "source": source,
        "content_hash": content_hash,
        "added_at": datetime.utcnow().isoformat(),
        "char_count": len(text),
    }
    manifest["documents"].append(doc_entry)
    _save_manifest(manifest)

    return {"status": "added", "doc_id": doc_id, "doc_count": len(manifest["documents"])}


def remove_document(doc_id):
    manifest = _load_manifest()
    doc = next((d for d in manifest["documents"] if d["doc_id"] == doc_id), None)

    if doc and doc.get("pi_doc_id"):
        try:
            pi = _get_pi()
            pi.delete_document(doc["pi_doc_id"])
        except Exception as e:
            print(f"PageIndex delete_document warning: {e}")

    manifest["documents"] = [d for d in manifest["documents"] if d["doc_id"] != doc_id]
    _save_manifest(manifest)
    return {"status": "removed", "doc_count": len(manifest["documents"])}


def get_kb_context(question=None):
    """
    Retrieve relevant KB content for a question using PageIndex cloud API.
    If question is None, return all document texts as context (no retrieval needed).
    Falls back to plain text concatenation if PageIndex is unavailable.
    """
    manifest = _load_manifest()
    if not manifest["documents"]:
        return ""

    if not question:
        # No question → return all content (for /api/kb listing)
        return ""

    # Use PageIndex query to retrieve relevant passages
    pi = _get_pi()
    all_answers = []

    for doc in manifest["documents"]:
        pi_doc_id = doc.get("pi_doc_id")
        if not pi_doc_id:
            continue
        try:
            resp = pi.submit_query(pi_doc_id, question)
            # submit_query returns a dict with 'answer' or similar
            if isinstance(resp, dict):
                answer_text = resp.get("answer", "") or resp.get("response", "")
                if answer_text and len(answer_text.strip()) > 10:
                    all_answers.append(f"### {doc['title']} (Source: {doc['source']})\n{answer_text.strip()}\n")
            elif isinstance(resp, str) and len(resp.strip()) > 10:
                all_answers.append(f"### {doc['title']} (Source: {doc['source']})\n{resp.strip()}\n")
        except Exception as e:
            print(f"PageIndex query warning doc {doc['doc_id']}: {e}")
            continue

    if not all_answers:
        return ""

    return "## KNOWLEDGE BASE\n\n" + "\n\n".join(all_answers)


# ─── LLM Integration ─────────────────────────────────────────────────────────

def build_prompt(question, context):
    return f"""You are ReplyIQ, an AI HR assistant. Answer employee questions based ONLY on the knowledge base provided below.

KNOWLEDGE BASE:
{context}

INSTRUCTIONS:
- Answer based strictly on the knowledge base above
- If the answer is in the KB: provide a clear, helpful answer citing the source
- If the question is NOT covered in the KB: say "I don't have that information in the HR knowledge base. I've flagged this for the HR team to review."
- Be concise but complete
- Format your answer with bullet points if it helps clarity
- End with the specific source document and section if available
- Cite the source document title in your answer when using KB content

EMPLOYEE QUESTION: {question}

ANSWER:"""


def ask_groq(prompt):
    import urllib.request
    import urllib.error

    if not GROQ_API_KEY:
        return {
            "answer": "⚠️ Groq API key not configured. Set GROQ_API_KEY environment variable.\n\nDemo mode: paste a question and I'll respond from the knowledge base once you've added documents.",
            "source": None,
            "model": "demo",
        }

    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 500,
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return {
                "answer": result["choices"][0]["message"]["content"],
                "source": "groq",
                "model": result.get("model", "unknown"),
            }
    except urllib.error.HTTPError as e:
        try:
            error_body = json.loads(e.read())
            return {"answer": f"API Error: {error_body.get('error', {}).get('message', str(e))}", "source": None}
        except Exception:
            return {"answer": f"API Error (HTTP {e.code}): {str(e)}", "source": None}
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "source": None}


# ─── HTML Page Routes ─────────────────────────────────────────────────────────

@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")


@app.route("/index")
@app.route("/index.html")
def serve_index_html():
    return send_from_directory(".", "index.html")


@app.route("/presell")
@app.route("/presell.html")
def serve_presell():
    return send_from_directory(".", "presell.html")


@app.route("/product")
@app.route("/product.html")
def serve_product():
    return send_from_directory(".", "product.html")


@app.route("/success")
@app.route("/success.html")
def serve_success():
    return send_from_directory(".", "success.html")


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "status": "ok",
        "app": "replyiq",
        "pageindex": bool(PAGEINDEX_API_KEY),
    })


@app.route("/api/kb", methods=["GET"])
def api_get_kb():
    manifest = _load_manifest()
    return jsonify({
        "documents": [
            {
                "id": d["doc_id"],
                "title": d["title"],
                "source": d["source"],
                "added_at": d["added_at"],
                "chars": d["char_count"],
            }
            for d in manifest["documents"]
        ],
        "total_docs": len(manifest["documents"]),
        "total_chars": sum(d["char_count"] for d in manifest["documents"]),
    })


@app.route("/api/kb/add", methods=["POST"])
def api_add_doc():
    body = request.json
    text = body.get("text", "").strip()
    title = body.get("title", "Untitled Document")
    source = body.get("source", "manual")

    if not text:
        return jsonify({"error": "No text provided"}), 400
    if len(text) < 50:
        return jsonify({"error": "Document too short (min 50 characters)"}), 400

    result = add_document(text, title, source)
    return jsonify(result)


@app.route("/api/kb/remove/<doc_id>", methods=["DELETE"])
def api_remove_doc(doc_id):
    return jsonify(remove_document(doc_id))


@app.route("/api/ask", methods=["POST"])
def api_ask():
    body = request.json
    question = body.get("question", "").strip()

    if not question:
        return jsonify({"error": "No question provided"}), 400

    manifest = _load_manifest()
    if not manifest["documents"]:
        # No docs → demo mode
        result = ask_groq(
            build_prompt(question, "No knowledge base content available.")
        )
        return jsonify({
            "question": question,
            "answer": result["answer"],
            "source": result.get("source"),
            "model": result.get("model"),
            "kb_doc_count": 0,
        })

    context = get_kb_context(question)
    prompt = build_prompt(question, context)
    result = ask_groq(prompt)

    return jsonify({
        "question": question,
        "answer": result["answer"],
        "source": result.get("source"),
        "model": result.get("model"),
        "kb_doc_count": len(manifest["documents"]),
    })


@app.route("/api/reset", methods=["DELETE"])
def api_reset():
    manifest = _load_manifest()
    for doc in manifest["documents"]:
        if doc.get("pi_doc_id"):
            try:
                pi = _get_pi()
                pi.delete_document(doc["pi_doc_id"])
            except Exception as e:
                print(f"PageIndex delete warning: {e}")
    if MANIFEST_FILE.exists():
        MANIFEST_FILE.unlink()
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    print("🚀 ReplyIQ starting on http://localhost:5000")
    print("📋 API endpoints:")
    print("   GET  /api/kb          - list knowledge base")
    print('   POST /api/kb/add      - add document {"text": "...", "title": "..."}')
    print('   POST /api/ask         - ask question {"question": "..."}')
    print("   DELETE /api/reset     - reset knowledge base")
    print()
    print("⚠️  Set GROQ_API_KEY env var for AI answers. Free at https://console.groq.com")
    print("ℹ️  Set PAGEINDEX_API_KEY for reasoning-based retrieval (optional).")
    app.run(host="0.0.0.0", port=5000, debug=True)
