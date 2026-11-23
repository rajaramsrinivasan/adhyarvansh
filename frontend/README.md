# ⚠️ This folder is NOT the live frontend

The live site (https://adhyarvansh.com) serves the frontend that is **embedded
as base64 in `/worker.js`** (the `const _HTML = "..."` string), not the
`index.html` in this folder.

- **Live frontend:** `_HTML` inside `/worker.js` (~814 KB decoded)
- **`frontend/index.html` here:** a stale/partial copy (~69 KB). Do **not** edit
  it expecting the live site to change.

To change the live UI, edit the `_HTML` blob in `/worker.js`:
decode → edit → re-encode → `node --check` → deploy with `wrangler deploy worker.js`.

This folder is kept only for reference/history. Treat `/worker.js` as the single
source of truth for both backend and frontend.
