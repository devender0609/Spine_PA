# SpinePA Agent — Vercel Deployment

## Repository Structure

```
spinepa_vercel/           ← push this entire folder to GitHub
├── api/
│   └── index.py          ← Flask backend (Vercel serverless function)
├── public/
│   └── index.html        ← SpinePA Agent UI
├── vercel.json           ← Vercel routing
├── requirements.txt      ← Python dependencies
└── .gitignore
```

## Step-by-Step Deployment

### 1. Push to GitHub
- Create a new GitHub repository (public or private)
- Push the contents of this folder (not the folder itself — push what's *inside*)

### 2. Connect to Vercel
- Go to https://vercel.com → New Project → Import Git Repository
- Select your new GitHub repo
- **Root Directory**: leave blank (use repo root)
- **Framework Preset**: Other
- Click Deploy

### 3. Set Environment Variables
In Vercel → Project → Settings → Environment Variables, add:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your key from console.anthropic.com |
| `PRACTICE_NAME` | e.g. Ascension Texas Spine and Scoliosis |
| `PROVIDER_NAME` | e.g. Dr. Jane Smith |
| `PROVIDER_NPI` | Your 10-digit NPI number |

After adding env vars, **Redeploy** the project (Deployments tab → ⋯ → Redeploy).

## Local Development

```bash
pip install flask flask-cors anthropic

# Create a local config (gitignored)
echo '{"api_key":"sk-ant-...","practice_name":"My Clinic"}' > config.json

python api/index.py
```

Then open http://localhost:5000 in your browser.
