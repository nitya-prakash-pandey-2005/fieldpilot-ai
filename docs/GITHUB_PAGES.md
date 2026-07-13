# GitHub Pages deployment

The engineer dashboard is configured as a static Next.js export. Its production files are generated in `frontend/engineer-dashboard/out` and deployed automatically by `.github/workflows/deploy-dashboard.yml` whenever `main` is pushed.

## One-time repository setup

In the GitHub repository, open **Settings → Pages**, set **Source** to **GitHub Actions**, and push this project to the `main` branch. The workflow publishes the dashboard at the URL reported in the workflow run.

## Build locally

```bash
cd frontend/engineer-dashboard
npm ci --legacy-peer-deps
npm run build
```

Open `out/index.html` in a static-file server. The deployed dashboard uses its built-in demo data unless `NEXT_PUBLIC_API_URL` is set at build time to a publicly reachable API.
