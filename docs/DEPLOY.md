# Deploying the Dashboard (Free) — Streamlit Community Cloud

The dashboard is built to deploy free on **Streamlit Community Cloud**. It is
self-contained: it reads small precomputed files from `app/data/` and uses a
numpy-only scheduler, so it needs no heavy ML libraries at runtime.

## One-time deploy (≈ 3 minutes)

1. Go to **https://share.streamlit.io**
2. Click **Sign in with GitHub** (use the `chetan200247` account)
3. Click **Create app** → **Deploy a public app from GitHub**
4. Fill in:
   | Field | Value |
   |-------|-------|
   | Repository | `chetan200247/HPC-Optimizer` |
   | Branch | `main` |
   | Main file path | `app/main.py` |
5. Click **Deploy**

Streamlit installs `requirements.txt` (the slim 4-package set) and launches the
app. First build takes ~2 minutes. You get a public URL like:

```
https://hpc-optimizer-<random>.streamlit.app
```

## Updating the live app

Any push to `main` auto-redeploys. To refresh the dashboard data after re-running
the pipeline:

```bash
python scripts/build_dashboard_data.py   # regenerates app/data/
git add app/data && git commit -m "refresh dashboard data" && git push
```

## Why it deploys reliably

- **Slim runtime deps** — `streamlit`, `pandas`, `numpy`, `plotly` only. No
  TensorFlow/XGBoost/Prophet at runtime (those are dev-only, in
  `requirements-dev.txt`).
- **Tiny data** — `app/data/` is ~50 KB of precomputed CSV/JSON.
- **No secrets needed** — the dashboard reads committed data; the EIA API key is
  only used by the offline pipeline.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app/main.py
```
