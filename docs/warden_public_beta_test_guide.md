# Warden AI Desk public beta test

This test assumes you installed Warden on your own Debian or Ubuntu computer
using [Get Warden running](getting-started.md). It does not require access to
the maintainer's computer, accounts, Brain, or server.

## Ten-minute first-run test

1. Start **Warden AI Desk**.
2. Read the first-run account and privacy explanation.
3. Choose **Sign in to Chat**.
4. Open one AI website for which you have an account and complete its normal
   website sign-in.
5. Quit and reopen Warden. Confirm that the website session returns in the same
   Warden browser profile.
6. Choose **Build**, open a disposable Git repository, and start a local
   terminal.
7. If you already use Codex, Claude Code, Gemini CLI, or Grok, confirm Warden
   reports that official client's authentication accurately.
8. Start only a harmless structured mission, such as adding a text file, and
   confirm Warden shows activity, changed files, and review controls before
   anything reaches the project.

## Expected boundaries

- Website Chat works independently of structured Build providers.
- No account is pre-populated.
- A missing provider client is reported as missing, not connected.
- Warden does not silently choose API-key billing.
- Remote websites cannot access the project, terminal, or Warden IPC.
- Agent work remains isolated until **Apply to project**.
- Private Brain proof is optional; local proof remains available.

## Useful feedback

Report:

- distribution and desktop environment;
- installation method;
- the exact step that was confusing or failed;
- what you expected;
- what Warden displayed;
- a screenshot with account names, email addresses, project paths, prompts, and
  provider content removed.

Never attach cookies, tokens, passwords, API keys, Chromium profile folders, or
private repository contents to a public issue.
