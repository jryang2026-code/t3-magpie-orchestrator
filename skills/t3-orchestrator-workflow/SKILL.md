---
name: t3-orchestrator-workflow
description: Single-entry multi-model orchestration workflow for T3 Code + Magpie. Keeps one flagship agent as the sole user-facing orchestrator, inspects live Magpie and Antigravity quotas via get_dispatch_brief (or magpie quota --json fallback) before delegating, gates P0 plans through an optional second-opinion reviewer, dispatches domain-matched harnesses, watches PRs with zero-token T3 watch_pull_request, and closes out P0/P1 fixes (max 2 rounds) and substantive P2 tracking issues cleanly.
---

# T3 Code Single-Entry Multi-Model Orchestrator Workflow

Use a single flagship orchestrator (typically `claudeAgent`) as the sole human conversation interface inside **T3 Code**, while dynamically routing work across specialized harnesses based on **live remaining quotas** and **per-harness strengths**.

> **Subagent Guardrail (Mandatory):** If you are running as a child task spawned by `delegate_task`, do **not** call `get_dispatch_brief` or spawn further sub-delegates unless your task explicitly requires it. Complete your assigned slice cleanly and report back.

---

## Step 1: Check Live Quotas & Capabilities First

Before planning multi-step delegation:

1. Call the MCP tool **`get_dispatch_brief`** (`magpie-dispatch`).
   - *Fallback if MCP is not registered:* run `magpie quota --json` and inspect `~/.config/t3-orchestrator/roster.json` (or this skill's `references/roster.example.json`).
   - Respect low-quota thresholds (`< 30%` remaining, or stale cache `⚠️STALE`): keep scarce flagship/secondary pools strictly on planning, complex architecture/UI, and critical reviews; shift exploration, routine edits, tests, and PR chores onto your Flash worker pool.
2. Call **`orchestrator_capabilities`** once per thread before your first `delegate_task` to verify exact `providerInstanceId`, model slugs, and option IDs on this machine (e.g. `effort`, `reasoningEffort`, `thinking`, `variant`, `thought_level`).

---

## Step 2: Plan & Conditional P0 Second-Opinion Gate

- **Small / well-scoped tasks:**
  - If codebase discovery is needed, dispatch a Flash worker (`role: "research"`) read-only first.
  - Have the primary orchestrator draft the slice plan and acceptance checks directly—**skip** second-opinion review to avoid extra latency and quota burn.
- **High-risk / cross-module / ambiguous P0 designs:**
  1. Primary orchestrator writes the draft plan (scope, boundaries, risks, verification plan).
  2. Dispatch your configured P0 second-opinion reviewer (if configured & within quota, e.g. `antigravity` `gemini-4-neon` with exact `thought_level: "medium"`) for a **read-only critique** focused on missing edge cases, state/concurrency flaws, and unnecessary complexity.
  3. Primary orchestrator synthesizes valid feedback into final actionable work slices.

---

## Step 3: Domain Routing & Worktree Discipline

Route tasks using the live roster (`~/.config/t3-orchestrator/roster.json`):
- **Codebase search, routine implementation, mechanical refactors, tests, docs, git PR chores:** Primary/secondary Flash workers (e.g. `pi` / `opencode` running your Magpie Flash routing group at max reasoning), plus optional lightweight co-pilot (e.g. `gemini-4-hydrogen` at `thought_level: "high"`) **only** while its weekly quota stays healthy.
- **Complex backend, concurrency, state machines, root-cause debugging:** Backend specialist (e.g. `codex` / `gpt-6.2-sol`, `reasoningEffort: "medium"`).
- **Complex frontend, UI/UX, interaction polish:** Primary orchestrator directly, or frontend-capable second specialist.

### Single-PR Sequential vs. Multi-PR Worktree Parallelism
- **One feature = one PR:** Dispatch sequential steps on the shared branch checkout—do **not** fork multiple parallel `isolation: "worktree"` writes for the same PR unless an explicit merge plan exists.
- **Independent parallel modules / PRs:** Use `isolation: "worktree"` so concurrent writers stay isolated on separate branches and each opens its own PR (use `gh stack` when PRs depend on one another).
- **Never poll child tasks:** Wait for T3 task-completion wake notifications instead of running `sleep`/`task_status` loops.

---

## Step 4: Pre-Push Gate, PR Creation & Zero-Token Watching

1. **Verification & pre-review gate:**
   - Require passing real tests/checks before opening a PR.
   - If `pr_reviewer_mode` is `"hybrid"` (or `"local_codex"`): run a local adversarial diff review (`codex` specialist or `codex review`) **before pushing** whenever changes touch core backend state, auth/security, migrations, or concurrency. Routine UI/small PRs can skip local pre-review and rely on CI + GitHub Auto-Review.
2. **Worker commit/PR handoff:**
   - Have a Flash worker verify `git status`, commit, push, and run `gh pr create` (verifying active `gh auth status` matches the repo).
3. **Zero-token PR watch:**
   - Once you have the PR URL, call T3's built-in **`watch_pull_request`** and end your turn.
   - **Never** leave an LLM worker polling `gh pr view` in a `sleep` loop—T3's `PullRequestWatchReactor` checks CI, reviews, conflicts, and merges for zero tokens.
4. **Auto-Review fallback (no deadlock):**
   - If the repository does not run GitHub Codex Auto-Review (or CI turns green with no bot review after a reasonable wait), post `@codex review` once if bot-triggered, or run a single local `codex review --base <base-branch>` fallback so the PR never stalls waiting on an unconfigured bot.

---

## Step 5: Wakeup Triage, 2-Round Breaker & Closeout

When `watch_pull_request` (or local fallback review) delivers findings:

1. **P0 / P1 (Blocking: correctness, security, concurrency, missing verification, failing CI):**
   - Route back to the domain owner (`codex` for backend, Flash worker / frontend specialist for UI/routine fixes) on the same branch to fix, re-verify, and push.
   - **2-round circuit breaker:** Allow at most **2 fix rounds** per batch of review findings. If P1 issues or red CI persist past round 2, stop worker churn and escalate directly to **Primary Orchestrator + Backend Specialist** joint takeover.
2. **P2 (Non-blocking suggestions):**
   - **Prevent issue spam:** Only create a tracking GitHub Issue (`gh issue create`) for substantive follow-up engineering debt (batching related suggestions into one issue with PR/comment links); skip trivial wording/formatting nits.
3. **Closeout:**
   - Only when required CI checks are green, zero P0/P1 blockers remain, and substantive P2s are tracked:
     - If `auto_merge_on_clean_p2` is `true` in `roster.json`: have a worker run `gh pr merge --squash --delete-branch` (reporting permission/branch-protection blocks if any) and clean temporary worktrees.
     - Otherwise: report PR link, checks status, and filed issue links so the human can click Merge.
