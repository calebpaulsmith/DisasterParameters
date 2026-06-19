# Making the site private (Cloudflare Pages + Cloudflare Access)

This tool currently ships on **GitHub Pages from a public repo**, which has **no real
access control** — the page *and* the committed `data/*.json` are world-readable on
GitHub regardless of anything we put in `index.html`. To gate it for real, move hosting
to **Cloudflare Pages** (free, static, auto-deploys from this repo) and put **Cloudflare
Access** (free Zero Trust, up to 50 users) in front of it as an email login. Then flip
the GitHub repo to **private**.

> The data is all public FEMA/NOAA/USGS open data, so this is about controlling who can
> reach the *tool*, not protecting secrets. Keep the non-endorsement disclaimers in the UI.

## 1 · Host on Cloudflare Pages (free)

1. Create a free Cloudflare account → dashboard → **Workers & Pages → Create → Pages →
   Connect to Git**. Authorize GitHub and pick `calebpaulsmith/DisasterParameters`,
   production branch `main`.
2. Build settings:
   - **Framework preset:** None
   - **Build command:** *(optional — only to keep the footer build stamp working; see below)*
   - **Output directory:** `/`  (the repo root — `index.html` is the whole app)
3. Deploy. You get `https://disasterparameters.pages.dev` (add a custom domain later if
   you want). It redeploys automatically on every push to `main`, just like Pages did.

**Optional — keep the footer commit/date stamp.** GitHub Pages stamped the build via
`.github/workflows/pages.yml`. To reproduce it on Cloudflare, set the **Build command** to:

```sh
sed -i "s/__BUILD_SHA__/$(echo "$CF_PAGES_COMMIT_SHA" | cut -c1-7)/g; s/__BUILD_DATE__/$(date -u +'%Y-%m-%d %H:%MZ')/g" index.html
```

and keep **Output directory** = `/`. Without it the footer just falls back to a generic
label — harmless.

## 2 · Gate it with Cloudflare Access (the login)

1. In the Pages project → **Settings** → enable an **Access policy**. This provisions
   **Cloudflare Zero Trust** (choose a team name; the free plan covers 50 users) and
   protects both production and preview deployments.
2. Edit the generated policy:
   - **Action:** Allow
   - **Include:** *Emails* → list the addresses allowed in (yours + colleagues), or
     *Emails ending in* `@yourcompany.com`.
   - **Authentication:** **One-time PIN** (Cloudflare emails a code — no identity
     provider needed). Add Google/Microsoft SSO later if preferred.
3. Save. Visiting the site now prompts for an email, emails a 6-digit code, and only
   allowed addresses get through. Sessions last as long as you configure (default 24h).

## 3 · Make the GitHub repo private

- GitHub → repo **Settings → General → Danger Zone → Change visibility → Private**.
- This **disables the old `calebpaulsmith.github.io/DisasterParameters` site** (free
  GitHub Pages requires a public repo). Cloudflare Pages keeps deploying from the private
  repo via its GitHub app authorization — no change needed there.
- The footer's "commit" link will point to private-repo commits (visible only to repo
  collaborators). Fine.

## 4 · Cleanup (after Cloudflare is confirmed working)

- Delete `.github/workflows/pages.yml` (the GitHub Pages deploy is dead once private).
- Update the live-site URL in `README.md` and `CLAUDE.md` to the new Cloudflare/custom
  domain.

## What this does and doesn't protect

- ✅ Nobody reaches the tool without an allowed email + one-time code.
- ✅ Repo source/data no longer public (after step 3).
- ⚠️ Anyone you add to the Access policy can see everything; there are no per-user views.
- ⚠️ Runtime calls the page makes (OpenFEMA, NWS, USGS) are unaffected and remain public
  APIs — that's expected and fine.
