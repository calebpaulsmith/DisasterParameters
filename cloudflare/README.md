# Cloudflare Worker — daily "recent obligations" refresh

`recent-worker.js` keeps the Geography **Recent activity** sub-filter fresh without
a repo redeploy. It rebuilds the same payload as `data/recent.json`
(`scripts/build_county_recent.py`) on a daily cron and serves it CORS-open, so the
browser can read either the committed file or this always-current endpoint.

## What the browser uses it for

- **1-year window** — a single live national OpenFEMA pull truncates at the
  10,000-row cap, so the year window reads this feed (or the committed
  `data/recent.json` fallback).
- **Fallback** for any window if a live fetch to OpenFEMA fails.

Short windows (7/30/60/90 days) are fetched **live** straight from OpenFEMA in the
browser (national date-windowed query, filtered to Region 5 client-side), so the
worker is not on the hot path for those.

## Wire it up in the app (optional)

In `index.html`, set the worker URL (empty by default = use committed file only):

```js
const RECENT_WORKER_URL = "https://recent.<your-subdomain>.workers.dev";
```

When set, the app prefers the worker for the 1-year window and for fallbacks.
When empty, it falls back to the committed `data/recent.json`.

## Deploy (KV + daily cron)

1. Create a KV namespace and note its id:
   ```sh
   npx wrangler kv namespace create RECENT_KV
   ```
2. `cloudflare/wrangler.toml`:
   ```toml
   name = "disasterparameters-recent"
   main = "recent-worker.js"
   compatibility_date = "2024-11-01"

   kv_namespaces = [
     { binding = "RECENT_KV", id = "<paste-kv-id>" }
   ]

   [triggers]
   crons = ["0 9 * * *"]   # daily 09:00 UTC — OpenFEMA updates overnight
   ```
3. Deploy and warm the cache:
   ```sh
   npx wrangler deploy
   curl -s https://disasterparameters-recent.<subdomain>.workers.dev | head -c 200
   ```

The cron handler rebuilds and writes KV; the fetch handler serves KV (and builds
on demand the first time so it never 404s). The payload is Region 5 only and small
(~100 KB), well within Worker limits.

## Alternative: commit the file back to the repo

If you'd rather keep GitHub Pages as the only origin, point a daily GitHub Action
(or this worker via the GitHub contents API) at
`python3 scripts/build_county_recent.py` and commit the refreshed
`data/recent.json`. The committed file is the zero-config fallback either way.
