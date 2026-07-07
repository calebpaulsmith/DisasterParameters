# Making the Operations Planner exportable — SharePoint & beyond

**Status:** plan + shipped v1. The owner's requirement: *"I need to be able to put this whole
planner — map, expectations, teams, everything — into a SharePoint site, copy-paste."*
This doc is the plan for that, what's built, and the honest constraints of each path.

---

## 1. The constraint landscape (why "just paste it" is hard)

SharePoint Online (modern pages) is a hostile target for interactive HTML:

| Fact | Consequence |
|---|---|
| Modern pages **strip `<script>`, `<style>`, `<iframe>` (unless whitelisted), forms, and event handlers** from anything pasted or typed into a Text web part. | The *live* planner can never run "inside" a pasted page. Anything pasted must be **static, script-free, inline-styled** HTML. |
| The Text web part **keeps** basic semantic HTML on paste: headings, paragraphs, `<table>`, bold/italic, links, and (usually) inline `style` attributes on those elements. | Tables of numbers survive a paste. This is the reliable channel. |
| Pasted `<img src="data:...">` behavior varies by tenant — some uploads inline images to the site's asset library automatically, some strip them. | The map image may or may not survive a paste; we also offer it as a **separate PNG download** to insert with an Image web part (always works). |
| Uploading an `.html` file to a document library: SharePoint serves it as a **download**, not a rendered page, unless the tenant admin allows custom script (classic `.aspx` pages / `AllowCustomScript`). | The self-contained HTML export is still the *complete* artifact (interactive `<details>` drill-downs, full data baked in) — but on default tenants it opens in the browser as a local file, is linked from a page, or is embedded via the **File viewer** web part rather than pasted. |
| The **Embed** web part only accepts URLs from domains the admin has whitelisted. | Embedding the live GitHub Pages planner is possible *if* the admin whitelists `calebpaulsmith.github.io` — zero-effort "live" option, worth requesting. |

So the export strategy is **three artifacts, one button each**, covering every tenant posture:

## 2. The three export paths (all shipped in planner.html)

1. **"Copy for SharePoint"** — the copy-paste ask, literally. Builds a **script-free,
   inline-styled HTML fragment** and puts it on the clipboard with the `text/html` flavor
   (`navigator.clipboard.write` + `ClipboardItem`), so pasting into a SharePoint **Text web
   part** (or Outlook, Word, OneNote, Teams) preserves the tables and colors. Contents:
   - plan title + the **PLAN / not-a-declaration disclaimer** (never separable from the data);
   - the **map as a PNG** (`<img>` with a data URI, rendered from the live SVG via canvas);
   - **top-level expectations** (PA applicants/projects/$ per disaster, IA registrations/IHP $
     per disaster — medians + means, with the included/excluded disaster counts);
   - **expected categories of work** table (share of historical PA $ by Category A–G/Z);
   - the **team divider** table (team color chip, members, counties, expected PA applicants,
     expected IA registrations, PDA applicants);
   - the **per-county expectations** table (programs, team, prior declarations, expected
     applicants/$/projects, expected registrations/IHP $, PDA figures);
   - a source/accounting-stage footer (PA = obligated, IHP = approved).
   If the Clipboard API is blocked (http, permissions), it **falls back to downloading the
   same fragment** as a file with instructions (open → select-all → copy → paste).
2. **"Export self-contained HTML"** — one downloadable file with geometry + every county's
   full history + expectations + teams **baked in as plain JSON** (no network). For a
   document library / Site Assets, the File viewer web part, email, or any static host.
   This is the *complete* record; the paste fragment is the *briefing* view.
3. **"Export data CSV" + applicant/expectation CSVs + "Download map PNG"** — for Lists,
   Excel, Power BI, Databricks, and an Image web part respectively.

### Recommended SharePoint recipe (put this in the page)
1. Planner → build the plan (program, exclusions, teams) → **Copy for SharePoint**.
2. SharePoint page → edit → **Text** web part → paste. Done for the briefing view.
3. If the map image was stripped by your tenant: **Download map PNG** → **Image** web part.
4. Upload the **self-contained HTML** export to the site's document library and link it
   ("full drill-down data") from the pasted section.
5. Optional, one-time: ask the tenant admin to whitelist `calebpaulsmith.github.io` for the
   **Embed** web part to get the *live* planner on the page.

## 3. Design rules that keep the exports honest

- **The disclaimer travels with every artifact** (fragment, HTML file, CSV headers keep
  labeled "hist"/"expected"/"PDA" columns; PNG is captioned by the surrounding fragment).
- **Expectations always state their base**: "N of M prior disasters included" — exclusions
  (user-removed outliers, and the seeded disaster itself) are listed by DR number in the
  fragment/file footer, so a reader can see what was left out of the math.
- **PA vs IHP accounting stages never blur**: obligated vs approved, labeled at point of use.
- No live fetches in any export — everything is resolved at export time (SharePoint pages
  must not depend on this repo staying up).

## 4. Deferred / later options

- **Live embed via Cloudflare** (plan-in-URL, iframe-friendly headers) — deferred (P-E in
  the planner plan); the Embed-web-part whitelist covers most of the value at zero cost.
- **SharePoint Framework (SPFx) web part** wrapping the planner — the "native" answer, but
  it needs tenant packaging/deployment rights; out of scope for a public-data side tool.
- **PNG/SVG snapshot of the whole expectations card** (not just the map) — nice-to-have if
  the paste path proves brittle on the owner's tenant.
- Revisit after the owner's first real paste: which tenant behaviors (image stripping,
  table style survival) actually bite, and tighten the fragment accordingly.
