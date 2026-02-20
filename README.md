# Telegram Premium Bot

Private channel access bot with Stripe subscription payments.

## Files
- `main.py` — Bot entry point
- `bot/config.py` — Environment variables
- `bot/database.py` — SQLite database operations
- `bot/utils.py` — Helper functions
- `bot/email_service.py` — SendGrid email sender
- `bot/handlers/start.py` — /start and main menu
- `bot/handlers/subscribe.py` — Subscribe flow
- `bot/handlers/activation.py` — Activation code flow
- `bot/handlers/login.py` — Login + credential setup
- `bot/handlers/video_list.py` — Video list display
- `bot/handlers/help.py` — Help, cancel, resend, inquiry
- `webhook/stripe_webhook.py` — Stripe payment webhook (Flask)

## Deployment (Render.com)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "Initial bot"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Step 2 — Deploy on Render
1. Go to render.com → New → Blueprint
2. Connect your GitHub repo
3. Render reads render.yaml automatically
4. Add secret environment variables in Render dashboard:
   - BOT_TOKEN
   - STRIPE_SECRET_KEY
   - STRIPE_WEBHOOK_SECRET
   - SENDGRID_API_KEY
   - FROM_EMAIL
   - WEBHOOK_URL (your webhook service URL from Render)

### Step 3 — Add Stripe Webhook
1. Go to Stripe → Developers → Webhooks
2. Add endpoint: https://your-webhook-service.onrender.com/webhook/stripe
3. Select events:
   - checkout.session.completed
   - customer.subscription.deleted
   - invoice.payment_failed
4. Copy webhook secret → add to Render env vars as STRIPE_WEBHOOK_SECRET

### Step 4 — Update Video List
Edit `bot/handlers/video_list.py` → update the VIDEO_LIST array with your actual videos.
