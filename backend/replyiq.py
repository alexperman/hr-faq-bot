"""
ReplyIQ - AI HR FAQ Assistant
Flask backend with Groq LLM integration
"""

import os
import json
import uuid
import hashlib
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# NOTE: Groq is free for development. Get your API key at https://console.groq.com
# Set GROQ_API_KEY environment variable before running
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

app = Flask(__name__)
CORS(app)

# ─── Data Storage ────────────────────────────────────────────────────────────

# Use /tmp for Render compatibility (ephemeral filesystem)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_RENDER = os.environ.get("PORT", "") != ""
KB_FILE = "/tmp/knowledge_base.json" if IS_RENDER else os.path.join(BASE_DIR, "knowledge_base.json")
SESSIONS_FILE = "/tmp/sessions.json" if IS_RENDER else os.path.join(BASE_DIR, "sessions.json")

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

# ─── Knowledge Base ──────────────────────────────────────────────────────────

def get_kb():
    return load_json(KB_FILE, {"documents": [], "qna_pairs": []})

def add_document(text, title="Untitled", source="manual"):
    kb = get_kb()
    doc_id = hashlib.sha256(text[:200].encode()).hexdigest()[:12]
    # Check if already exists
    for d in kb["documents"]:
        if d["id"] == doc_id:
            return {"status": "exists", "id": doc_id, "doc_count": len(kb["documents"])}
    
    kb["documents"].append({
        "id": doc_id,
        "title": title,
        "source": source,
        "content": text,
        "added_at": datetime.utcnow().isoformat(),
        "chunk_count": max(1, len(text) // 500)
    })
    save_json(KB_FILE, kb)
    return {"status": "added", "id": doc_id, "doc_count": len(kb["documents"])}

def remove_document(doc_id):
    kb = get_kb()
    kb["documents"] = [d for d in kb["documents"] if d["id"] != doc_id]
    save_json(KB_FILE, kb)
    return {"status": "removed", "doc_count": len(kb["documents"])}

def get_kb_context():
    """Combine all KB docs into a single context string for the LLM"""
    kb = get_kb()
    if not kb["documents"]:
        return ""
    
    context = "## KNOWLEDGE BASE\n\n"
    for doc in kb["documents"]:
        context += f"### {doc['title']} (Source: {doc['source']})\n"
        context += doc["content"] + "\n\n"
    return context

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
            "model": "demo"
        }
    
    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 500
    }
    
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return {
                "answer": result["choices"][0]["message"]["content"],
                "source": "groq",
                "model": result.get("model", "unknown")
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
    return jsonify({"status": "ok", "app": "replyiq"})

@app.route("/api/kb", methods=["GET"])
def api_get_kb():
    kb = get_kb()
    return jsonify({
        "documents": [{"id": d["id"], "title": d["title"], "source": d["source"], 
                       "added_at": d["added_at"], "chars": len(d["content"])} 
                      for d in kb["documents"]],
        "total_docs": len(kb["documents"]),
        "total_chars": sum(len(d["content"]) for d in kb["documents"])
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
    result = remove_document(doc_id)
    return jsonify(result)

@app.route("/api/ask", methods=["POST"])
def api_ask():
    body = request.json
    question = body.get("question", "").strip()
    
    if not question:
        return jsonify({"error": "No question provided"}), 400
    
    context = get_kb_context()
    prompt = build_prompt(question, context)
    result = ask_groq(prompt)
    
    return jsonify({
        "question": question,
        "answer": result["answer"],
        "source": result.get("source"),
        "model": result.get("model"),
        "kb_doc_count": len(get_kb()["documents"])
    })

@app.route("/api/reset", methods=["DELETE"])
def api_reset():
    save_json(KB_FILE, {"documents": [], "qna_pairs": []})
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
    app.run(host="0.0.0.0", port=5000, debug=True)
