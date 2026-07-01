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

## DNS strategy: registrar vs. DNS host

Registrar and DNS host are modeled as **separate** fields on `SiteConfig` —
never assume "Namecheap" means Namecheap answers DNS queries:

- `registrar_provider` — who the domain is bought through (e.g. `namecheap`)
- `dns_provider` — who answers DNS queries: `vercel` | `namecheap` | `cloudflare` | `other`
- `host_provider` — who serves the site (e.g. `vercel`)
- `dns_strategy` — `vercel_nameservers` | `external_dns_records` | `namecheap_basicdns`
- `nameserver_target` — set to `vercel` automatically when `dns_strategy` is `vercel_nameservers`

**Policy: for Vercel-hosted sites, prefer Vercel nameserver delegation.**
Namecheap remains the registrar; Vercel's nameservers (`ns1.vercel-dns.com`,
`ns2.vercel-dns.com`) answer DNS. Only fall back to `namecheap_basicdns`
(editing Namecheap host records directly) when the domain needs a
Namecheap-specific service — email forwarding, URL forwarding, Dynamic DNS —
or non-Vercel routing.

`warden/webstudio/dns_strategy.py` builds the recommendation and, for the
`vercel_nameservers` strategy, the concrete delegation plan:

```python
from warden.webstudio.registry import get_site
from warden.webstudio import dns_strategy

site = get_site("unlck", "configs/webstudio.sites.yaml")
plan = dns_strategy.plan_for_site(site)
print(plan)  # recommended_strategy: "vercel_nameservers", requires_manual_approval: True
```

### unlck.shop sandbox setup

`unlck.shop` is the first sandbox domain proving this policy end to end:

- `registrar_provider: namecheap`, `dns_provider: vercel`, `host_provider: vercel`
- `dns_strategy: vercel_nameservers`, `nameserver_target: vercel`
- `migration_status: sandbox` — the only domain currently cleared for a
  direct Vercel nameserver cutover
- Production domain: `unlck.shop`; aliases: `www.unlck.shop`, `test.unlck.shop`, `demo.unlck.shop`

Nameserver delegation is a **registrar-level** change (made at Namecheap) and
is never applied automatically — `plan_vercel_nameserver_delegation()` only
describes the target state. Back up current Namecheap DNS records first
(see below) in case you need to fall back to Namecheap DNS later. Applying
the delegation is a manual, explicitly approved operator action.

## Production DNS migration policy

Matt already has production sites hosted on Vercel with domains bought at
Namecheap. Some may use Namecheap BasicDNS today; some may already point at
Vercel or another DNS host. **Production uptime matters, so migrating a
domain's DNS is a safety workflow, not a one-step switch.**

Policy:

1. **Existing production domains stay as-is until audited.** Every site
   defaults to `migration_status: existing`, and
   `dns_strategy.recommend_migration_action(site)` returns
   `"no_automatic_migration"` for both `existing` and `planned` status —
   regardless of what `dns_strategy`/`dns_provider` is configured. Nothing
   ever auto-recommends a cutover for these domains.
2. **New/sandbox Vercel-only domains can use Vercel DNS directly.** Only
   `migration_status: sandbox` domains (currently just `unlck.shop`) get a
   ready-to-apply `vercel_nameservers` delegation plan from
   `dns_strategy.plan_for_site()`.
3. **Production migration requires, in order:** a DNS inventory
   (`dns_migration.build_inventory`), a Vercel zone parity checklist
   (`parity_checklist`), missing-record warnings
   (`missing_record_warnings`), and an explicit approval step before any
   nameserver or record change (`cutover_checklist`, `rollback_checklist`).
4. **Email records must be preserved.** Vercel does not provide email
   hosting — MX and TXT (SPF/DKIM/verification) records are always flagged
   `present_must_preserve` in the parity checklist and called out in
   `missing_record_warnings`.
5. **Namecheap remains the registrar** unless Matt separately decides to
   transfer registration — DNS delegation to Vercel's nameservers does not
   change who the domain is registered through.

`migration_status` lifecycle: `existing` → `planned` (inventory + parity
checklist drafted) → `approved` (Matt has explicitly approved cutover) →
`migrated` (cutover completed and verified). Only `sandbox` skips straight
to "safe to migrate directly" since it's disposable/non-critical.

### Running a production DNS migration report

This never changes anything — it only inventories and plans:

```python
from warden.webstudio.registry import get_site
from warden.webstudio import dns_migration, dns_namecheap

site = get_site("usemarius", "configs/webstudio.sites.yaml")
nameservers = dns_migration.detect_authoritative_nameservers(site.domain)
records = dns_namecheap.fetch_current_records(site.domain) if dns_namecheap.credentials_available() else []
inventory = dns_migration.build_inventory(site.domain, records, nameservers=nameservers)
plan = dns_migration.plan_production_migration(site, inventory)
report_path = dns_migration.write_migration_report(plan)
print(report_path, plan["recommended_action"])  # "no_automatic_migration" for an existing production domain
```

Or via the API: `POST /api/mcharness/webstudio/sites/{name}/dns-migration-report`.

## Namecheap DNS safety (fallback path)

Use this path only when a domain needs Namecheap-specific DNS features, or
hasn't been delegated to Vercel yet.

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
