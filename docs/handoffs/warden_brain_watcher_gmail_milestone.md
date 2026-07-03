# Warden Brain + Watcher + Gmail Milestone

Status: Working local product proof.

Commit:
14ba182 feat(warden): add watcher brain ingest and gmail imap connector

Proof:
- Gmail connected through IMAP app password.
- Gmail mail search works.
- Gmail mail read works.
- Warden Watcher extension reloaded.
- Browser page capture works.
- Captured source writes into Warden Brain / local Markdown vault.
- Brain can find saved source.
- Marius can answer from saved source.

Product loop proven:
Browser / Mail source → Warden capture → Brain vault → local index → Marius answer with source context.

Next priorities:
1. Polish Watcher UI.
2. Add recent captures panel in Warden.
3. Add "Ask Marius about this" after capture.
4. Improve YouTube/PDF extraction reliability.
5. Add one-click open note in Obsidian/vault.
6. Add public/brother-safe onboarding.
