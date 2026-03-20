# DevPulse Deployment Checklist

## Streamlit Cloud

1. Push project to GitHub.
2. Go to https://share.streamlit.io and create app from this repo.
3. App entry point: `ui/app.py`.
4. Set secrets in Streamlit Cloud using keys from `.streamlit/secrets.example.toml`.
5. Redeploy app.

## Required Secrets

- `GITHUB_TOKEN` (recommended)
- `GROQ_API_KEY` (recommended)
- `GEMINI_API_KEY` (optional fallback)

## Verification After Deploy

1. Launch app and run audit on a small public repo.
2. Confirm report is generated.
3. Confirm JSON and Markdown downloads work.
4. Ask follow-up question and confirm answer returns.
5. Confirm runtime profile and scan coverage sections are visible.

## Troubleshooting

- If report generation is slow: reduce scan depth.
- If dependency warnings appear: check manifest support and repo lockfiles.
- If LLM calls fail: verify secrets are set correctly in Streamlit Cloud.
- If GitHub rate limit occurs: ensure `GITHUB_TOKEN` is set.

## Operational Notes

- Local deterministic cache is stored in `.cache/devpulse` to reduce repeat API calls.
- CI gates are defined in `.github/workflows/ci.yml` and include `pytest` + `python smoke_ci.py`.
