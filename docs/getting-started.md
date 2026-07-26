# Get Warden running

Warden AI Desk is a local Linux desktop application. Each installation has its
own projects, browser profiles, provider sessions, terminal history, and run
records. A fresh installation does not contain the maintainer's accounts,
credentials, conversations, Brain, or project data.

## Supported system

- Debian or Ubuntu on an x86-64 computer
- A normal desktop session with Electron/Chromium sandbox support
- Git, if you want to open and edit repositories
- An account with any AI provider you choose to use

Other Linux distributions and CPU architectures are not release-tested yet.

## Install the Debian package

1. Open the latest Warden release on GitHub.
2. Download both `warden-ai-desk_0.4.1_amd64.deb` and its `.sha256` file.
3. In a terminal opened in the download folder, verify and install it:

   ```bash
   sha256sum --check warden-ai-desk_0.4.1_amd64.deb.sha256
   sudo apt install ./warden-ai-desk_0.4.1_amd64.deb
   ```

4. Start **Warden AI Desk** from the application menu, or run:

   ```bash
   warden-ai-desk
   ```

Do not bypass Electron's Chromium sandbox with a permanent `--no-sandbox`
option. If the package will not start normally, open a GitHub issue with your
distribution, desktop environment, and the terminal error.

## Use your accounts

Chat and Build use two deliberately separate authentication paths.

### Chat websites

Select Claude, ChatGPT, Gemini, Grok, or another Web Platform and use the
website's normal sign-in page. The website owns authentication. Its cookies
stay in the selected named Warden browser profile under your Linux account.

- Warden does not import Chrome cookies.
- The maintainer cannot access your session.
- Use separate Warden profiles when you want personal and work website sessions
  kept apart.
- Adding a website never grants it terminal or filesystem access.

### Structured Build providers

Build missions require the provider's official local client. Install only the
clients you intend to use, sign into each client in a normal terminal, and then
press **Refresh** in Warden's Build authentication card.

| Provider | Sign-in owned by | Typical sign-in action |
|---|---|---|
| Codex | OpenAI Codex client | Run `codex login` |
| Claude | Claude Code | Run `claude` and complete its login flow |
| Gemini | Gemini CLI | Run `gemini` and complete Google sign-in |
| Grok | Grok client | Run `grok login` |

Client installation commands and account eligibility can change, so use the
provider's current official documentation. Warden checks the installed client
but does not read, copy, or store its OAuth token. API-key billing is an
explicit fallback and requires approval for every run.

You can use Chat and local terminals without configuring any structured Build
provider.

## First project

1. Choose **Build**.
2. Select **Open project** and choose a Git repository you own or can edit.
3. Warden checks whether the workspace is safe for an isolated managed mission.
4. Start with a small task and add a concrete “ready for review when” condition.
5. Review approvals, changed files, checks, and proof.
6. Choose **Apply to project** only when you accept the result. Otherwise request
   changes or discard the isolated worktree.

Commit or back up important work before testing agent-driven changes. Warden's
proof and Undo controls reduce risk but are not a replacement for source
control.

## Local data and removal

Warden normally stores desktop state under:

```text
~/.config/Warden AI Desk/
```

That directory can contain website sessions, project paths, terminal history,
and redacted run evidence. Protect it like browser profile data. To remove all
Warden desktop data, quit Warden first and delete that directory manually.
Uninstalling the package alone may leave the data directory in place.

The separate Python Warden service, browser-memory extension, mail connectors,
and private Brain integrations are optional advanced components. They are not
required for Warden AI Desk.

## Build from source

Use this path if no compatible package is available or you want to contribute:

```bash
git clone https://github.com/matthewjmcbridejr-code/Warden.git
cd Warden/desktop
npm ci
npm run check
npm run dev
```

Source development requires Node.js 22 or newer, npm, Git, a C/C++ toolchain
for `node-pty`, and Electron's Linux system libraries.

## Legacy local service

The repository also contains the earlier Python Warden service. Contributors
can start its canonical local UI with:

```bash
python -m venv .venv
.venv/bin/pip install -e .
scripts/warden-up
```

The desktop application is the recommended entry point for a new user. The
legacy service is optional and has additional provider and system-service
configuration.
