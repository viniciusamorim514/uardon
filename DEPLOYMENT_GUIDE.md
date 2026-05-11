# Uardon Deployment Guide - Railway + Domain Setup

## Status

✅ **Git Repository**: Initialized and ready  
✅ **Initial Commit**: Source code committed (commit: 6ee904f)  
✅ **Railway Config**: Dockerfile, Procfile, and environment setup added (commit: 4cea480)  
⏭️ **Next**: GitHub push → Railway deployment → Domain configuration

---

## Step 1: Create GitHub Repository

### Option A: Create via GitHub Web UI (Recommended)

1. Go to https://github.com/new
2. Repository name: **`uardon`**
3. Description: "Poder em Jogo Studio - OpusClip-style local automation tool"
4. Visibility: **Public** (required for Railway free tier)
5. Skip initialization (don't create README/gitignore - we already have them)
6. Click "Create repository"

### Option B: Via GitHub CLI (if installed)

```powershell
gh repo create uardon --public --source=. --remote=origin --push
```

---

## Step 2: Push Code to GitHub

### Setup Remote and Push

```powershell
cd "C:\Users\Vinicius\Documents\New project\Uardon"

# Add remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/uardon.git

# Verify remote
git remote -v

# Push to GitHub
git branch -M main
git push -u origin main
```

### Expected Output
```
Enumerating objects: 47, done.
Counting objects: 100% (47/47), done.
...
 * [new branch]      main -> main
Branch 'main' set up to track remote branch 'main' from 'origin'.
```

---

## Step 3: Deploy to Railway

### Prerequisites
- GitHub account ✅
- Repository pushed to GitHub ✅
- Railway account (create at https://railway.app)

### Railway Setup Process

1. **Create Railway Account**
   - Visit https://railway.app
   - Sign up with GitHub (recommended)
   - Accept authorization

2. **Create New Project**
   - Click "Create a New Project"
   - Select "Deploy from GitHub repo"
   - Authorize Railway to access your GitHub

3. **Select Repository**
   - Find and select: `YOUR_USERNAME/uardon`
   - Click "Deploy"

4. **Configure Environment Variables**

   In Railway dashboard, go to Variables tab and add:

   ```
   OPENAI_API_KEY = [leave blank for heuristic-only mode, or add key for AI editorial]
   STUDIO_HOST = 0.0.0.0
   PYTHONUNBUFFERED = 1
   ```

   Optional (for advanced features):
   ```
   TIKTOK_USERNAME = your_tiktok_username
   TIKTOK_PASSWORD = your_tiktok_app_password
   ```

5. **Wait for Deploy**
   - Railway will automatically build and deploy
   - Check the Deployments tab for status
   - Expected build time: 3-5 minutes

6. **Get Railway URL**
   - Once deployed, Railway generates a URL like: `uardon-production.railway.app`
   - Click "Settings" → "Domains" to see your public URL
   - Test it: https://your-url.railway.app (should see Uardon UI)

---

## Step 4: Register Domain and Point DNS

### Domain Registration

**Domain**: `uardon.com` (or your preferred name)  
**Registrar options**: Namecheap, GoDaddy, Google Domains (~$12-15/year)

#### Register with Namecheap (recommended, cheapest):
1. Go to https://www.namecheap.com
2. Search for `uardon.com`
3. Add to cart → Checkout → Complete purchase (~$10.69/year)
4. Verify email
5. Go to "Manage Domain"

### Point Domain to Railway

#### Via Namecheap Dashboard:

1. **Access Domain Settings**
   - Go to your Namecheap account
   - Click "Manage" on your `uardon.com` domain
   - Go to "Advanced DNS" tab

2. **Add Railway CNAME Record**
   - Find the CNAME section
   - Add new record:
     - **Host**: `www`  
     - **Type**: `CNAME Record`  
     - **Value**: Your Railway URL (e.g., `uardon-production.railway.app`)
     - **TTL**: 30 min

   Also add an A record for root domain:
     - **Host**: `@`  
     - **Type**: `A Record`  
     - **Value**: Get this from Railway (ask Railway team for Anycast IP or use their DNS setup guide)

3. **In Railway Dashboard**
   - Go to your project → Settings → Domains
   - Add custom domain: `uardon.com` and `www.uardon.com`
   - Railway provides SSL certificate automatically ✅

4. **Wait for DNS Propagation**
   - DNS changes take 24-48 hours to propagate globally
   - Check status: https://dnschecker.org (search for `uardon.com`)

---

## Step 5: Test Production Deployment

Once DNS propagates (or earlier with Railway's testing URL):

### Via Railway URL
```bash
curl https://uardon-production.railway.app
```

### Via Custom Domain (after DNS propagates)
```bash
curl https://uardon.com
```

### Test Features
1. **UI Load**: https://uardon.com (should see clip generation interface)
2. **API Health**: https://uardon.com/api/state (should return JSON)
3. **Generate Clip**:
   ```bash
   curl -X POST https://uardon.com/api/run \
     -H "Content-Type: application/json" \
     -d '{"url": "https://www.youtube.com/watch?v=oNlSvbTFUnM", "quality": "alta"}'
   ```

---

## Environment Variables (Railway)

### Required
- None (all have sensible defaults)

### Recommended (for full features)
```
OPENAI_API_KEY=sk-...          # For AI-powered hook generation
```

### Optional (for TikTok integration)
```
TIKTOK_USERNAME=your_username
TIKTOK_PASSWORD=your_app_password  # Not your main password!
```

---

## Troubleshooting

### Build Fails
- Check Railway logs: Dashboard → Deployments → click build
- Common issues:
  - `pip install` fails → Check FFmpeg availability in Dockerfile
  - Missing dependencies → Check `requirements.txt`

### Domain Not Resolving
- Wait 24-48 hours for DNS propagation
- Check DNS records: https://dnschecker.org
- Verify Railway domain settings point to correct URL

### SSL Certificate Issues
- Railway provides free SSL automatically
- Verify domain is added in Railway → Settings → Domains
- Wait up to 5 minutes for cert generation

### Application Crashes on Railway
- Check logs: Railway dashboard → Deployments → Logs
- Common issues:
  - Port binding (Railway sets `PORT` env var automatically)
  - Missing environment variables
  - FFmpeg not available (check Dockerfile includes `apt-get install ffmpeg`)

---

## Cost Estimates

| Item | Cost | Notes |
|------|------|-------|
| Domain (uardon.com) | ~$12/year | Namecheap, GoDaddy, Google Domains |
| Railway Hosting | $5/month | Free tier or $5/month for paid dyno equivalent |
| OpenAI API (optional) | Pay as you go | Only if using AI editorial features |
| **Total (minimum)** | **~$1/month** | Free tier works for testing |

---

## Next Steps After Deployment

1. ✅ **Monitor Dashboard**
   - Railway: https://railway.app (check logs, metrics)
   - Create alerts for deployment failures

2. **Set Up Analytics**
   - Monitor clip generation success rate
   - Track API response times
   - Log to analytics dashboard

3. **TikTok Integration**
   - Get TikTok API credentials (separate process)
   - Add environment variables to Railway
   - Enable auto-posting feature

4. **Custom Domain Email** (Optional)
   - Set up email forwarding via Namecheap
   - Example: `hello@uardon.com` → your email

5. **SSL/HTTPS**
   - ✅ Automatic via Railway/Namecheap
   - Renews automatically

---

## Quick Reference Commands

```powershell
# Local testing before push
cd "C:\Users\Vinicius\Documents\New project\Uardon"
python src/web_app.py

# Verify commits ready for push
git log --oneline -5

# Push to GitHub
git push -u origin main

# Check Railway deployment status
# (via https://railway.app dashboard)

# Test production API
curl https://uardon.com/api/state
```

---

## Support

- **Railway Docs**: https://docs.railway.app
- **Namecheap DNS**: https://www.namecheap.com/support/
- **Git/GitHub**: https://github.com/git-tips/tips

---

**Status**: Ready for GitHub push and Railway deployment  
**Estimated Time**: 30 minutes (GitHub) + 5 minutes (Railway) + 24-48 hours (DNS)  
**Next Action**: Create GitHub repository and push code
