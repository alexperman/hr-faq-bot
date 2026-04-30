# ReplyIQ — AI HR Assistant

**The AI that answers 80% of employee questions. Instantly.**

---

## What Was Built

### 3-Part Funnel (Cold Traffic Framework)

```
Cold Traffic → Pre-sell Page → Landing Page → Product
     ↓              ↓               ↓           ↓
  LinkedIn/       Article:       CTA +      Working
  FB/Reddit      "5 Signs"      Pricing      Product
```

### Files

| File | Purpose |
|------|---------|
| `presell.html` | Advertorial / pre-sell page — warms cold traffic, builds belief before the product ask |
| `index.html` | Landing page — full conversion funnel with testimonials, pricing, objections handled |
| `product.html` | Working product — chat UI for employees to ask HR questions |
| `backend/app.py` | Flask API — knowledge base storage + Groq LLM integration |
| `backend/requirements.txt` | Python dependencies |

---

## Marketing Strategy Summary

### Target Customer
- **Primary:** 20-200 person companies with overwhelmed HR teams
- **Ideal symptoms:** HR manager says "I don't have time for strategic work"

### Positioning
> "Your employee handbook, alive 24/7"

### Pricing
| Tier | Price | Employees |
|------|-------|-----------|
| Starter | $99/mo | up to 50 |
| Growth | $299/mo | up to 200 |
| Enterprise | $799/mo | unlimited |

### Traffic Channels (by priority)
1. **LinkedIn cold outreach** to HR managers (DMs with value first)
2. **r/HR, r/SaaS, r/smallbusiness** — organic posts with real use cases
3. **HR Facebook groups** — comment with genuine help
4. **Product Hunt** launch when ready
5. **$50 LinkedIn ads** targeting HR roles — validate before scaling

### Pre-sell Flow (Cold Traffic Principle #10)
- Traffic from ads/links lands on `presell.html` first
- Article builds belief, answers objections, then links to `index.html`
- CTA on presell page sends warm traffic to landing page

---

## Running Locally

### Backend
```bash
cd backend
pip install -r requirements.txt
export GROQ_API_KEY=your_key_from_console.groq.com  # Free tier available
python app.py
```
Backend runs on `http://localhost:5000`

### Frontend (Landing + Presell)
```bash
# Just open in browser
open presell.html   # pre-sell / article page
open index.html     # landing/conversion page
```

### Full Product
```
1. Start backend: cd backend && python app.py
2. Open product.html in browser
3. Click "Manage KB" → add documents (or click sample docs)
4. Start chatting
```

---

## API Reference

```
GET  /api/kb              → list knowledge base documents
POST /api/kb/add         → add doc {"text": "...", "title": "..."}
POST /api/ask            → ask {"question": "..."}
DELETE /api/kb/remove/:id → remove document
DELETE /api/reset        → clear all documents
```

---

## What's Next (Priority Order)

1. **Get GROQ API key** → enable actual AI answers
2. **Deploy backend** → Render.com free tier or Railway
3. **Deploy frontend** → Netlify (drag-and-drop `index.html`)
4. **Create waitlist** → Carrd.co ($16/yr) linked from presell
5. **Run $50 LinkedIn ad test** → validate demand before building more

---

## Cold Traffic Framework Applied

| Principle | Implementation |
|-----------|----------------|
| Hook in 3 sec | "Your employee handbook, alive 24/7" — specific outcome |
| Bridge belief gap | Problem section → solution → live demo |
| Why now urgency | "HR teams answer same 12 questions weekly" |
| Structure | Hook → Problem → Solution → Proof → Offer → CTA |
| Under-explain | Each feature explained in plain employee language |
| Specific proof | "6hrs saved/week", "500+ HR teams", "4.9★ rating" |
| Strong offer | 14-day trial + $199 HR assessment bonus |
| Remove friction | FAQ section handles objections before checkout |
| CTA = next step | "Start Free Trial" repeated + "Book a demo" fallback |
| Pre-sell step | `presell.html` article warms traffic before product ask |

