# SpinePA Agent (Vercel)

This deploys a Flask API + static UI to Vercel.

## Required Vercel Environment Variables

- `ANTHROPIC_API_KEY` (required for AI features)
- `ANTHROPIC_MODEL` (optional) — default: `claude-3-5-sonnet-20240620`
- `PRACTICE_NAME` (optional)
- `PROVIDER_NAME` (optional)
- `PROVIDER_NPI` (optional)

> If you use provider-specific NPIs (e.g., `PROVIDER_NPI_TRUUMEES`), the backend will try to match it to `PROVIDER_NAME`
> when `PROVIDER_NPI` is not set.

After editing env vars, trigger a redeploy (or push a new commit).

## Local run

```bash
pip install -r requirements.txt
python api/index.py
```

Open http://127.0.0.1:5000
