# WebStudio Agent

Local-first website operations agent for Marius WebStudio / SMB client sites
(usemarius.com, TreeGuru-style, GradeMy/Shelf-style, and future clients).
Runs entirely on your machine — no dependency on hosted browser-agent
services. Lives under `src/warden/webstudio/`.

## What it does

- **Site registry** (`registry.py`): tracks each site's repo path, framework,
  package manager, host/DNS provider, and commands in
  `configs/webstudio.sites.yaml`.
- **Repo inspection** (`repo.py`): detects framework/package manager, git
  status, branch slugging, task-branch creation, and likely editable files.
- **Build/test workflow** (`workflow.py`): runs install → build → test with
  per-site commands, bounded timeouts, and graceful skips when a site has no
  tests configured.
- **Browser verification** (`browser.py`): Playwright desktop + mobile
  screenshots and console error capture. Skips gracefully (reports
  `available: false`) if Playwright isn't installed.
- **SEO/AEO checks** (`seo.py`): title, meta description, canonical, OpenGraph,
  JSON-LD/LocalBusiness schema, robots.txt/sitemap.xml/llms.txt presence.
- **Vercel operator layer** (`vercel.py`): safe argv-list command builders for
  `vercel pull` / `vercel build` / preview `vercel deploy` (never `--prod`),
  plus `vercel inspect` / `vercel logs` for read-only deployment inspection.
- **Namecheap DNS safety layer** (`dns_namecheap.py`): read-only `getHosts`
  fetch, JSON backups, and a merge-safe diff planner. Writes require calling
  `approve_plan()` explicitly; this module never issues `setHosts` itself.
- **Proof packs** (`proof.py`): every run produces a Markdown report under
  `_mctable/webstudio/proof/reports/` with commands run, build/test status,
  changed files, screenshots, SEO issues, Vercel preview URL, and DNS diff.
- **API** (`api.py`): mounted under `/api/mcharness/webstudio` in Warden.

## Configuring your first site

```bash
cp configs/webstudio.sites.example.yaml configs/webstudio.sites.yaml
```

Edit `configs/webstudio.sites.yaml` and point `repo_path` at your real local
checkout (e.g. `~/workspaces/marius-core/usemarius-site`). This file is
gitignored — it's local operational config, not committed source.

## Running an audit

Via the API (once Warden is running):

```bash
curl -s -X POST http://localhost:8000/api/mcharness/webstudio/audit \
  -H 'Content-Type: application/json' \
  -d '{"site_name": "usemarius", "run_build": true, "run_test": true}'
```

Or from Python directly:

```python
from pathlib import Path
from warden.webstudio.registry import get_site
from warden.webstudio.workflow import run_build_test_workflow
from warden.webstudio import seo

site = get_site("usemarius", "configs/webstudio.sites.yaml")
workflow = run_build_test_workflow(site, install=True, build=True, test=True)
print(workflow.to_dict())
```

## Generating a local proof pack

```bash
curl -s -X POST http://localhost:8000/api/mcharness/webstudio/proof-pack \
  -H 'Content-Type: application/json' \
  -d '{"site_name": "usemarius", "task": "Update homepage CTA copy"}'
```

Report is written to `_mctable/webstudio/proof/reports/<site>.<timestamp>.md`.

## Browser screenshots

```python
from pathlib import Path
from warden.webstudio.browser import capture_screenshots

result = capture_screenshots("http://localhost:3000", Path("_mctable/webstudio/screenshots/usemarius"))
print(result.to_dict())
```

Requires `pip install playwright && playwright install chromium` once.
Without it, `capture_screenshots` returns `available: false` with setup
instructions instead of raising.

## Vercel preview deploys

WebStudio only ever builds **preview** commands — production deploy flags
(`--prod`, `-p`) are rejected by `vercel.py` before a command is ever run.

```python
from pathlib import Path
from warden.webstudio import vercel

repo = Path("~/workspaces/marius-core/usemarius-site").expanduser()
vercel.run_pull(repo)
vercel.run_build(repo)
result = vercel.run_preview_deploy(repo)
print(vercel.extract_preview_url(result))
```

Production deploys are a manual, explicit operator action outside this
module (`vercel --prod`, run by you in your own terminal).

## Namecheap DNS safety

1. Set env vars (never printed by this module): `NAMECHEAP_API_USER`,
   `NAMECHEAP_API_KEY`, `NAMECHEAP_USERNAME`, `NAMECHEAP_CLIENT_IP`.
2. Fetch + back up current records:

```python
from pathlib import Path
from warden.webstudio import dns_namecheap as dns

records = dns.fetch_current_records("usemarius.com")
dns.save_backup("usemarius.com", records, backup_dir=Path("_mctable/webstudio/dns_backups"))
```

3. Build a merge-safe diff plan (existing records not mentioned are always
   preserved):

```python
proposed = [dns.DnsRecord(host="@", record_type="A", address="76.76.21.21")]
plan = dns.plan_dns_diff("usemarius.com", records, proposed)
print(plan.to_dict())
```

4. Writes are blocked until you call `dns.approve_plan(plan)` explicitly.
   `build_set_hosts_params()` then raises if the plan hasn't been approved.
   **This module never calls Namecheap's `setHosts` itself** — that's left
   to an explicit, reviewed operator action, because `setHosts` replaces
   the entire host record set if the merge is done incorrectly.

Without credentials, `dns.setup_instructions()` returns clear next steps and
every other function fails closed rather than guessing.

## Known limitations

- Vercel/Namecheap/Playwright integration paths that touch live services are
  not covered by automated tests (no live credentials in CI); they're
  exercised via safe command-builder/parsing tests only.
- SEO checks are heuristic/deterministic, not a full Lighthouse/axe audit.
- No production deploy path is implemented — by design.
