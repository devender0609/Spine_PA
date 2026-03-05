# SpinePA Agent (Vercel + GitHub)

This repo deploys the SpinePA Agent UI + Flask backend as a single Vercel Function.

## 1) Local run (recommended for testing)

```bash
python -m venv .venv
source .venv/bin/activate  # (Windows) .venv\\Scripts\\activate
pip install -r requirements.txt

# Create local config
cp config.example.json config.json
# Edit config.json and add your Anthropic API key

python -m flask --app api.index run --port 5000
```

Open: http://localhost:5000

## 2) Deploy on Vercel

1. Push this repo to GitHub.
2. In Vercel, import the GitHub repo.
3. Set Environment Variables in Vercel:

- `ANTHROPIC_API_KEY` (required)
- `PRACTICE_NAME` (optional)
- `PROVIDER_NAME` (optional)
- `PROVIDER_NPI` (optional)
- `ANTHROPIC_MODEL` (optional, defaults to `claude-sonnet-4-5-20250929`)

Then deploy.

## Notes
- The `/settings` endpoint is **disabled on Vercel** (serverless filesystem is not a reliable place to store secrets). Use Vercel env vars instead.
- Do **not** commit real API keys to GitHub.
