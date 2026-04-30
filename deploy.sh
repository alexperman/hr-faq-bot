#!/bin/bash
# ReplyIQ Deployment Script
# Deploys frontend to Netlify (drag-and-drop) and backend to Render

echo "=== ReplyIQ Deployment ==="
echo ""

# ── FRONTEND: Netlify ──────────────────────────────────────────────────────────
echo "📄 FRONTEND DEPLOYMENT (Netlify)"
echo "1. Go to https://app.netlify.com/drop"
echo "2. Drag and drop the /root/hr-faq-bot folder"
echo "3. Your site will be live at a *.netlify.app URL"
echo "4. Add custom domain in Site Settings → Domain Management"
echo ""

# Alternative: Netlify CLI (if logged in)
echo "Or via CLI (requires netlify login):"
echo "  cd /root/hr-faq-bot"
echo "  netlify deploy --prod --dir=."
echo ""

# ── BACKEND: Render ────────────────────────────────────────────────────────────
echo "🖥️ BACKEND DEPLOYMENT (Render - Free Tier)"
echo ""
echo "1. Push backend/ to GitHub:"
echo "   cd /root/hr-faq-bot"
echo "   git init"
echo "   git add backend/"
echo "   git commit -m 'ReplyIQ backend v1'"
echo "   git remote add origin https://github.com/YOUR_USERNAME/replyiq-backend.git"
echo "   git push -u origin main"
echo ""
echo "2. Go to https://render.com → New → Web Service"
echo "3. Connect your GitHub repo"
echo "4. Settings:"
echo "   - Root Directory: backend"
echo "   - Build Command: pip install -r requirements.txt"
echo "   - Start Command: python app.py"
echo "   - Plan: Free"
echo ""
echo "5. Add Environment Variable:"
echo "   GROQ_API_KEY=your_key_from_console.groq.com"
echo ""
echo "6. Your API will be live at: https://your-service.onrender.com"
echo ""

# ── UPDATE FRONTEND API URL ────────────────────────────────────────────────────
echo "🔗 AFTER DEPLOYMENT"
echo "Update the API base URL in product.html:"
echo "   const API = 'https://your-render-url.onrender.com/api';"
echo ""

# ── DOMAIN / EMAIL ─────────────────────────────────────────────────────────────
echo "🌐 RECOMMENDED STACK"
echo "Frontend:  Netlify (free) - netlify.com/drop"
echo "Backend:  Render (free) - render.com"
echo "Email:    ConvertKit ($9/mo) or Mailchimp (free tier)"
echo "Forms:    Netlify Forms (built-in, free)"
echo "Domain:   Namecheap ($10/yr)"
echo "Analytics: Plausible ($9/mo) or Google Analytics (free)"
echo ""
echo "=== DEPLOYMENT COMPLETE ==="
