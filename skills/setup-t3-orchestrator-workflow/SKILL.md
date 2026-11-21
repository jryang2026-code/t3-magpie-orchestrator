---
name: setup-t3-orchestrator-workflow
description: Configure T3 Code + Magpie quota-aware multi-model orchestration for your own subscriptions and available harnesses. Run once (or after adding accounts/models) via /setup-t3-orchestrator-workflow. Probes live models, filters broken endpoints, builds a personalized Flash Worker group, configures account safety guards, writes ~/.config/t3-orchestrator/roster.json, and registers the magpie-dispatch MCP server.
disable-model-invocation: true
---

# Setup T3 Orchestrator Workflow

Interactive, environment-probing setup guide for the `t3-orchestrator-workflow` skill. Because every user holds a different set of subscriptions, harnesses, and models, **never guess or hardcode model slugs—probe the user's actual machine first, verify health, confirm choices, and write user-local configuration outside this skill directory.**

## Rules

- Always back up any existing config file before modifying it.
- Never include or print API keys, OAuth tokens, cookies, or secrets in generated files or logs.
- Never write a model slug to `roster.json` unless you observed it live in `magpie models` / `~/.t3/caches/*.json` and verified it passes `magpie provider test` (or native session probe).
- Never blindly overwrite a user's entire `AGENTS.md` / `CLAUDE.md` — write into an isolated rule file (`~/.claude/rules/t3-orchestrator.md`) or a clearly fenced `<!-- t3-orchestrator:start --> ... <!-- t3-orchestrator:end -->` block.

---

## Step 1: Probe Installed Environment & Live Subscriptions

Run read-only checks to see what this machine actually has:

1. **Magpie gateway & accounts**:
   - `magpie status --json` (or inspect `~/.config/magpie/gateway.json`)
   - `magpie quota --json` and `magpie providers` and `magpie groups`
   - `magpie ls` (checks which agents are configured: `claude`, `codex`, `pi`, `opencode`, `omp`, etc.)
2. **T3 Code caches & settings** (if `~/.t3/` exists):
   - Read `~/.t3/userdata/settings.json` (`providerInstances`, `favorites`, `defaultModelSelection`, `textGenerationModelSelection`, `sourceControlWriterModelSelection`)
   - Read `~/.t3/caches/{claudeAgent,codex,pi,opencode,antigravity}.json` to capture exact T3 model slugs and capability option IDs (`effort`, `reasoningEffort`, `thinking`, `variant`, `thought_level`).
3. **GitHub CLI** (if PR automation is desired):
   - `gh auth status` (flag broken/expired accounts early).
4. **Dispatch script location**:
   - Locate `scripts/dispatch_mcp.py` relative to the companion `t3-orchestrator-workflow` skill directory (`~/.agents/skills/t3-orchestrator-workflow/scripts/dispatch_mcp.py` or sibling path).

Summarize your findings concisely before asking the user to make choices.

---

## Step 2: Health-Check Candidate Worker Models

Before bundling Flash / low-cost models into a routing group:

1. List all low-cost / Flash / fast-tier models exposed across the user's active Magpie providers.
2. Run `magpie provider test <provider> <model...>` on candidates (only free/subscription/fast models—avoid burning expensive flagship quota during setup).
3. Exclude any model that returns `400`, `403`, or `404` (e.g., disabled paid aliases on free-only accounts).
4. Separate **fixed subscription / rolling-window / free-tier pools** (put **first** in group order) from **pay-as-you-go / cash-balance providers** (put **last** as fallback, or omit per user preference).

---

## Step 3: Interactive Configuration Choices

Ask the user to confirm (prefer native choice cards when available, with sensible defaults):

1. **Role mapping** (adapting cleanly when a provider is absent):
   - **Primary Orchestrator & Hard Frontend**: e.g. `claudeAgent` (`claude/claude-opus-5-5`, `effort=medium`) or strongest available flagship.
   - **P0 Plan Second-Opinion Reviewer** *(optional)*: e.g. `antigravity` (`gemini-4-neon`, exact option `thought_level=medium`), or **None / Skip** if user has no Antigravity.
   - **Backend & Pre-Review Specialist**: e.g. `codex` (`codex/gpt-6.2-sol`, `reasoningEffort=medium`) or fallback reasoning model.
   - **Flash Workers**: `pi` and/or `opencode` bound to `magpie/group/flash-worker` (or custom group name), retiring redundant legacy harnesses like `omp` if desired.
2. **Account-pool safety hygiene** (for multi-account Magpie setups):
   - Recommend switching staggered multi-account `claude`/`codex` providers from restrictive pacing to `routing=smart`, enabling `pool --careful on`, `claudeNoExtraUsage on`, and Codex `quota credits off` (or `last`), plus `magpie visible <agent> <provider>` isolation.
3. **PR & Review workflow policy**:
   - `pr_reviewer_mode`: `"hybrid"` (GitHub Codex Auto-Review + local `codex` pre-review on high-risk diffs + local `codex review` fallback when bot absent/timeout), `"local_codex"`, or `"ci_only"`.
   - `auto_merge_on_clean_p2`: `false` (stop at Ready-to-Merge for user click) vs `true` (worker runs `gh pr merge --squash --delete-branch` once CI is green and tracking Issues are filed for substantive P2s).

---

## Step 4: Apply Configuration Safely

After backup + user confirmation:

1. **Create Flash Worker Magpie group** (if confirmed):
   ```bash
   magpie group add "Flash Worker" models=<verified-ordered-list-with-:max-or-nearest> routing=order stays=auto
   magpie group set flash-worker levels=low,medium,high,xhigh,max
   ```
   Wire chosen worker CLIs (`magpie pi group/flash-worker`, `magpie pi effort max`, `magpie opencode group/flash-worker`, `magpie opencode small group/flash-worker`), and primary CLIs (`magpie claude ...`, `magpie codex ...`).
2. **Write user-local roster** to **`~/.config/t3-orchestrator/roster.json`** (schema matching `t3-orchestrator-workflow/references/roster.example.json`, populated ONLY with verified slugs & exact T3 option IDs from Step 1–2).
3. **Register `magpie-dispatch` MCP** (where installed):
   - Claude Code: `claude mcp add -s user magpie-dispatch -- python3 <path-to-dispatch_mcp.py>`
   - Codex: `codex mcp add magpie-dispatch -- python3 <path-to-dispatch_mcp.py>`
   - Pi: `pi mcp add magpie-dispatch --exposure direct -- python3 <path-to-dispatch_mcp.py>` *(note: `--exposure direct` is required in Pi so the tool is callable without codemode wrapping)*
   - OpenCode: `opencode mcp add --global magpie-dispatch -- python3 <path-to-dispatch_mcp.py>`
4. **Install concise orchestrator trigger rule** (non-destructive):
   - Write `~/.claude/rules/t3-orchestrator.md` (or update fenced `<!-- t3-orchestrator:start -->` block in shared `AGENTS.md` if the user keeps a unified global file), explicitly reminding subagents (`delegate_task` children) **not** to re-query quotas or re-delegate.
5. **Update T3 Code preferences** *(if T3 is installed)*:
   - Warn that T3 Code caches `settings.json` in memory (`timeToLive: infinity`); either have the user apply/restart T3 Code after editing `~/.t3/userdata/settings.json` (pinning `favorites`, updating stale `textGenerationModelSelection`/`sourceControlWriterModelSelection`, disabling retired instances) so T3 refreshes `~/.t3/caches/*.json`.

---

## Step 5: Verify End-to-End

Run real verification after the final edit:
1. `python3 <path-to-dispatch_mcp.py> --cli` (confirm live Magpie quotas, optional Antigravity cache age, and accurate `~/.config/t3-orchestrator/roster.json` loading).
2. Send an actual stdio JSON-RPC `initialize` + `tools/list` + `tools/call` test to `<path-to-dispatch_mcp.py>`.
3. Verify `magpie ls`, `magpie groups`, `pi mcp list --json`, `claude mcp get magpie-dispatch`, `codex mcp get magpie-dispatch`, `opencode mcp list`.
4. Remind the user to start a **fresh thread** in T3 Code (restarting T3 Code first if `settings.json` changed).
