# Warden Model Gateway

**Status:** Operational — LiteLLM proxy on `:4000`, 6 model aliases, rule-based policy router, in-memory cache.

---

## Architecture

```
User / MCP Tool
     │
     ▼
┌─────────────────────────────────┐
│  Policy Router (policy.py)      │  ← 11 regex rules, zero LLM calls (95% of traffic)
│  Privacy Guard                  │  ← blocks private content from OpenRouter free tier
│  qwen3:0.6b fallback            │  ← only when rule confidence < 0.60
└───────────────┬─────────────────┘
                │  alias → warden-{local|fast|free|code|deep|embed}
                ▼
┌─────────────────────────────────┐
│  Context Budget (context_budget.py) │  ← per-alias token budgets, relevance scoring
│  Scores, trims, compresses      │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│  LiteLLM Proxy (:4000)          │  ← simple-shuffle routing, fallback chains
│  litellm_config.yaml            │  ← 6 aliases, RPM limits, in-memory cache
└───────────────┬─────────────────┘
                │
       ┌────────┼────────┐
       ▼        ▼        ▼
    Ollama    Groq   Cerebras  OpenRouter  HuggingFace
```

---

## Model Aliases

| Alias | Primary | Fallback | Context | Privacy | OR-Free |
|---|---|---|---|---|---|
| `warden-local` | Ollama qwen3:0.6b | Groq llama-3.1-8b | 4 096 | private | ✗ |
| `warden-fast` | Groq llama-3.1-8b | Cerebras llama3.1-8b → Ollama | 4 096 | private | ✗ |
| `warden-free` | OpenRouter gemma-3-12b:free | Groq fallback | 2 048 | public-safe | ✓ |
| `warden-code` | Groq llama-3.3-70b | Cerebras → OR qwen2.5-coder:free | 8 192 | private | ✗ |
| `warden-deep` | Groq llama-3.3-70b | Cerebras → OR qwen3-235b:free | 16 384 | private | ✗ |
| `warden-embed` | Ollama mxbai-embed-large | HF sentence-transformers | 512 | private | ✗ |

---

## Routing Rules

The policy router applies 11 regex rules in order. First match wins.

| Pattern | Alias | Confidence |
|---|---|---|
| `^(hi\|hello\|ok\|thanks)` | warden-local | 0.95 |
| `classify\|intent\|route\|tag` | warden-local | 0.90 |
| `summarise\|summarize\|tldr` | warden-local | 0.85 |
| `math\|calculate\|\d+[+-*/]\d+` | warden-local | 0.90 |
| `code\|bug.*fix\|\.py\|\.ts\|traceback` | warden-code | 0.85 |
| `write a .* function\|class\|endpoint` | warden-code | 0.85 |
| `architect\|trade-off\|should we\|pros and cons` | warden-deep | 0.80 |
| `root cause\|why does\|bottleneck\|diagnose` | warden-deep | 0.80 |
| `where we at\|status\|what's next\|plan` | warden-fast | 0.85 |
| `tool\|agent\|github\|memory\|recall\|warden` | warden-fast | 0.75 |
| `demo\|example\|hypothetically\|tutorial` | warden-free | 0.70 |
| *(no match)* | warden-fast | 0.50 |

When no rule matches (confidence 0.50 < threshold 0.60), `qwen3:0.6b` is invoked locally via Ollama for a secondary classification.

---

## Privacy Guard

Content matching any of these patterns is **never routed to `warden-free`** (OpenRouter free tier logs prompts):

- `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `CEREBRAS_API_KEY`, etc.
- `sk-or-*` or `sk-*` token patterns
- `# Warden Memory Context`
- `warden_recall`, `workbench`, `memory_id`, `session_id`, `evidence_id`
- `git log`, `git diff`, `git commit` (repo internals)
- `src/warden`, `src/marius`, `.env`

If content is private and the rule would route to `warden-free`, it is redirected to `warden-fast` with a warning.

---

## Context Budget

Per-alias token budgets enforce how much context reaches the model:

| Alias | Budget (tokens) |
|---|---|
| warden-local | 1 024 |
| warden-fast | 4 096 |
| warden-free | 2 048 |
| warden-code | 8 192 |
| warden-deep | 16 384 |
| warden-embed | 512 |

**Scoring:** Items are scored by keyword overlap with the query. Memories with a Jaccard similarity below 0.05 are dropped. Git context and system prompts always get 1.0 relevance. Tool outputs are compressed if they exceed their share of the budget.

**Item priorities (highest first):** system prompt → git context → tool outputs → high-relevance memories → conversation → low-relevance memories.

---

## Trace Storage

Traces are written to `~/.local/share/warden/gateway_traces.jsonl` (max 500 entries, pruned on write). No database required.

Each trace captures:
- `trace_id` (`gt_<10hex>`)
- `task_preview` (first 120 chars of input)
- `alias`, `provider`, `model`
- `classifier_used` (`rules` | `qwen` | `rules+qwen` | `forced`)
- `tokens_before` / `tokens_after` (context budget savings)
- `privacy`, `openrouter_free_blocked`
- `status` (`ok` | `error` | `fallback`)
- `elapsed_ms`, `timestamp`

---

## API Endpoints

All under `/api/mcharness/warden/model-gateway/`:

| Method | Path | Description |
|---|---|---|
| `GET` | `/status` | Provider health cards (Ollama, Groq, Cerebras, OpenRouter, HF, Tavily, Crawl4AI, LiteLLM) |
| `GET` | `/aliases` | All 6 alias definitions with metadata |
| `POST` | `/route-preview` | `{task, force_alias?}` → RouteDecision + budget summary |
| `POST` | `/context-preview` | `{query, alias?, memories, git_context, tool_outputs, system_prompt}` → budget inspection table |
| `GET` | `/traces?limit=50` | Recent gateway traces from JSONL |

---

## LiteLLM Proxy

Config: `litellm_config.yaml`  
Port: `4000`  
Service: `~/.config/systemd/user/litellm-warden.service`

Key settings:
- `routing_strategy: simple-shuffle` — randomises within each alias's provider list
- `num_retries: 2` — auto-retry on provider failure
- `cache: true`, `cache_params.type: local` — in-memory response caching (no Redis)
- Fallback chains: `warden-local` → `warden-fast` → `warden-local`

---

## Services

| Service | Port | Manages |
|---|---|---|
| Warden API | 6969 | FastAPI, all endpoints |
| LiteLLM proxy | 4000 | Model routing and caching |
| Crawl4AI | 8099 | URL scraping (local service) |
| Ollama | 11434 | Local models |

Start LiteLLM proxy:
```bash
systemctl --user start litellm-warden
```

Or manually:
```bash
env $(grep -v '^#' ~/.config/warden/cloud_keys.env | xargs) \
  .venv/bin/litellm --config litellm_config.yaml --port 4000
```

---

## UI: Model Gateway Control Room

Navigate to the Warden UI → **Gateway** tab.

Sections:
1. **Provider Status** — live health cards for all 8 providers
2. **Model Aliases** — 6 alias cards with privacy/cloud/OR-free chips
3. **Routing Simulator** — paste a task, preview which alias + provider it routes to
4. **Context Budget Inspector** — shows per-item kept/dropped/compressed breakdown
5. **Agent Gateway Trace Timeline** — last 50 traces from JSONL

---

## Running Tests

```bash
cd /home/matt/workspaces/warden/mcharness-public-export
.venv/bin/pytest tests/test_warden_gateway.py -v
```

All 20 tests should pass. Network is mocked — no API calls required.
