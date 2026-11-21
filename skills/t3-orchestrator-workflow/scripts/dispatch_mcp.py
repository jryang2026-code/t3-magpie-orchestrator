#!/usr/bin/env python3
"""Portable read-only MCP server exposing live Magpie + T3 quotas and orchestrator roster."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
EXAMPLE_ROSTER_PATH = SKILL_DIR / "references" / "roster.example.json"
USER_ROSTER_PATH = pathlib.Path.home() / ".config" / "t3-orchestrator" / "roster.json"

MAGPIE_CONFIG_DIR = pathlib.Path.home() / ".config" / "magpie"
MAGPIE_PROVIDERS_PATH = MAGPIE_CONFIG_DIR / "providers.json"
MAGPIE_GATEWAY_PATH = MAGPIE_CONFIG_DIR / "gateway.json"
ANTIGRAVITY_CACHE_PATH = pathlib.Path.home() / ".t3" / "caches" / "antigravity.json"

SERVER_INFO = {
    "name": "magpie-dispatch",
    "version": "1.2.0",
}

TOOL_DEF = {
    "name": "get_dispatch_brief",
    "description": (
        "Read live subscription/plan remaining quotas from local Magpie gateway (and T3 Antigravity cache if present), "
        "plus the user's T3 orchestrator roster and PR workflow policy."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_hint": {
                "type": "string",
                "description": (
                    "Optional focus (e.g. 'frontend', 'backend', 'review', 'worker', 'p0', 'pr') "
                    "to highlight tailored routing and PR gate advice."
                ),
            },
            "include_all": {
                "type": "boolean",
                "description": "Include group member details and all auxiliary providers.",
            },
        },
        "additionalProperties": False,
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}


def load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_roster() -> tuple[dict[str, Any], str]:
    env_path = os.environ.get("T3_ORCHESTRATOR_ROSTER")
    if env_path:
        p = pathlib.Path(os.path.expanduser(env_path))
        if p.is_file():
            data = load_json(p, None)
            if isinstance(data, dict):
                return data, str(p)
    if USER_ROSTER_PATH.is_file():
        data = load_json(USER_ROSTER_PATH, None)
        if isinstance(data, dict):
            return data, str(USER_ROSTER_PATH)
    data = load_json(EXAMPLE_ROSTER_PATH, {})
    return (data if isinstance(data, dict) else {}), f"{EXAMPLE_ROSTER_PATH} (example fallback)"


def resolve_gateway_quotas_url(roster: dict[str, Any]) -> str:
    env_url = os.environ.get("MAGPIE_QUOTAS_URL")
    if env_url:
        return env_url
    gw = load_json(MAGPIE_GATEWAY_PATH, {})
    addr = str(gw.get("addr") or "").strip() if isinstance(gw, dict) else ""
    if addr and ":" in addr:
        host, port = addr.rsplit(":", 1)
        host = host.strip("[]")
        if host in ("", "::", "0.0.0.0"):
            host = "127.0.0.1"
        if port.isdigit():
            return f"http://{host}:{port}/v1/magpie/quotas"
    return str(roster.get("magpie_gateway_url") or "http://127.0.0.1:3425/v1/magpie/quotas")


def fetch_magpie_quotas(url: str) -> tuple[list[dict[str, Any]], str | None]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"], None
        if isinstance(payload, list):
            return payload, None
        return [], "Unexpected JSON payload from Magpie /v1/magpie/quotas"
    except urllib.error.URLError as exc:
        return [], f"Magpie gateway unreachable at {url}: {exc.reason}"
    except Exception as exc:
        return [], f"Failed querying Magpie quotas: {exc}"


def fetch_antigravity_limits(cache_path: pathlib.Path) -> dict[str, Any] | None:
    if not cache_path.is_file():
        return None
    data = load_json(cache_path, None)
    if not isinstance(data, dict):
        return None
    ul = data.get("usageLimits")
    if not isinstance(ul, dict) or not ul.get("windows"):
        return None
    return ul


def fmt_reset(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return iso_str[:16]


def format_age(iso_str: str | None) -> tuple[str, bool]:
    if not iso_str:
        return "unknown", True
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        mins = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
        if mins < 60:
            return f"{mins}m ago", False
        hrs = mins // 60
        return f"{hrs}h ago", hrs >= 2
    except Exception:
        return iso_str[:16], True


def summarize_window(w: dict[str, Any]) -> str:
    name = w.get("name", "?")
    rem = w.get("remaining")
    disp = w.get("display")
    rst = fmt_reset(w.get("resetsAt"))
    rem_txt = f"{rem:.0f}%" if isinstance(rem, (int, float)) else "?"
    parts = [f"{name} rem={rem_txt}"]
    if disp:
        parts.append(f"(used {disp})")
    if rst:
        parts.append(f"rst={rst}")
    return " ".join(parts)


def get_group_members(group_id: str) -> list[str]:
    cfg = load_json(MAGPIE_PROVIDERS_PATH, {})
    for g in cfg.get("groups") or []:
        if isinstance(g, dict) and g.get("id") == group_id and not g.get("hidden"):
            out: list[str] = []
            for m in g.get("members") or []:
                if isinstance(m, str):
                    out.append(m)
                elif isinstance(m, dict) and m.get("model"):
                    out.append(str(m["model"]))
            return out
    return []


def build_brief(task_hint: str = "", include_all: bool = False) -> str:
    roster, roster_src = load_roster()
    gateway_url = resolve_gateway_quotas_url(roster)
    entries, err = fetch_magpie_quotas(gateway_url)
    agy_path = pathlib.Path(os.path.expanduser(roster.get("antigravity_cache_path", str(ANTIGRAVITY_CACHE_PATH))))
    agy_limits = fetch_antigravity_limits(agy_path)

    threshold = float(roster.get("low_quota_threshold_percent", 30))
    worker_group = str(roster.get("worker_group") or "flash-worker")

    lines: list[str] = [
        f"# Live Quota & T3 Orchestrator Brief ({datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')})",
        f"_Roster source: `{roster_src}`_",
    ]
    if err:
        lines.append(f"⚠️ {err} (start Magpie before dispatching)")

    by_provider: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        pid = str(e.get("provider") or "unknown")
        by_provider.setdefault(pid, []).append(e)

    # 1. Primary Flagship Pools
    lines.append("\n## 1. Primary Subscription Pools")
    primary_pids = [p for p in ("claude", "codex") if p in by_provider]
    for pid in primary_pids:
        for idx, it in enumerate(by_provider[pid], 1):
            label = f"{pid} #{idx}"
            plan = it.get("plan") or ""
            wins = [
                summarize_window(w)
                for w in (it.get("windows") or [])
                if w.get("lane") != "images" and w.get("display") != "Unknown"
            ]
            resets = (it.get("resets") or {}).get("count")
            extra = f" | resets={resets}" if resets is not None else ""
            lines.append(f"- **{label}** ({plan}): " + " ; ".join(wins) + extra)
    if not primary_pids:
        lines.append("- No active Claude/Codex quotas returned by Magpie.")

    # 2. Antigravity Pool (only if cache exists)
    agy_gemini_weekly_rem: float | None = None
    agy_3p_weekly_rem: float | None = None
    if agy_limits:
        lines.append("\n## 2. Antigravity Quota Pool (T3 Local Cache)")
        checked_raw = agy_limits.get("checkedAt")
        checked_at = fmt_reset(checked_raw)
        age_str, is_stale = format_age(checked_raw)
        stale_flag = " ⚠️STALE (>2h)" if is_stale else ""
        win_strs: list[str] = []
        for w in agy_limits.get("windows") or []:
            wid = str(w.get("id") or w.get("label") or "?")
            used = w.get("usedPercent")
            rem = max(0.0, 100.0 - float(used)) if isinstance(used, (int, float)) else None
            if wid == "gemini-weekly" and rem is not None:
                agy_gemini_weekly_rem = rem
            elif wid == "3p-weekly" and rem is not None:
                agy_3p_weekly_rem = rem
            rst = fmt_reset(w.get("resetsAt"))
            rem_s = f"{rem:.1f}%" if rem is not None else "?"
            s = f"{wid} rem={rem_s}"
            if rst:
                s += f" rst={rst}"
            win_strs.append(s)
        lines.append(f"- **antigravity** (cache={checked_at}, {age_str}{stale_flag}): " + " ; ".join(win_strs))

    # 3. Worker & Auxiliary Pools
    lines.append(f"\n## 3. Worker & Auxiliary Pools (`group/{worker_group}`)")
    other_pids = [k for k in by_provider if k not in ("claude", "codex")]
    for pid in sorted(other_pids):
        items = by_provider[pid]
        summaries: list[str] = []
        for it in items:
            if it.get("balance") is not None:
                summaries.append(f"balance={it['balance']}")
            else:
                wins = [
                    summarize_window(w)
                    for w in (it.get("windows") or [])
                    if w.get("lane") != "images" and w.get("display") != "Unknown"
                ]
                if wins:
                    summaries.append(" ; ".join(wins))
        if summaries:
            lines.append(f"- **{pid}**: " + " | ".join(summaries))

    members = get_group_members(worker_group)
    if members:
        if include_all:
            lines.append(f"- **group/{worker_group} ({len(members)} members)**: " + ", ".join(members))
        else:
            lines.append(f"- **group/{worker_group}**: {len(members)} active members configured")

    # 4. Roster Matrix
    lines.append("\n## 4. T3 Harness & Model Roster")
    for h in roster.get("harnesses", []):
        opt = f", `{h['option_spec']}`" if h.get("option_spec") else ""
        lines.append(
            f"- **{h['label']}** (`{h['t3_instance']}` / `{h['model']}`{opt}): "
            f"Strengths: {h['strengths']} | Avoid: {h['avoid']}"
        )
    retired = roster.get("retired_harnesses") or []
    if retired:
        lines.append(f"- **Disabled / Retired**: {', '.join(retired)}")

    # 5. Dynamic Advice
    advice: list[str] = []
    for pid in ("claude", "codex"):
        rems = [
            w.get("remaining", 0)
            for it in by_provider.get(pid, [])
            for w in (it.get("windows") or [])
            if "day" in str(w.get("name", "")).lower() or "week" in str(w.get("name", "")).lower()
            if isinstance(w.get("remaining"), (int, float))
        ]
        if rems and max(rems) < threshold:
            advice.append(f"⚠️ {pid} weekly pool max remaining < {threshold:.0f}%: reserve strictly for flagship orchestration/review.")

    if agy_gemini_weekly_rem is not None and agy_gemini_weekly_rem < threshold:
        advice.append(
            f"⚠️ Antigravity `gemini-weekly` remaining {agy_gemini_weekly_rem:.1f}% (< {threshold:.0f}%): "
            f"reserve `gemini-4-neon` (`thought_level=medium`) for P0 second-opinion/hard UI; route light work to `group/{worker_group}`."
        )
    if agy_3p_weekly_rem is not None and agy_3p_weekly_rem < threshold:
        advice.append(f"Antigravity `3p-weekly` remaining {agy_3p_weekly_rem:.1f}%: avoid 3P models inside Antigravity; use native harnesses.")

    auto_merge = bool(roster.get("auto_merge_on_clean_p2", False))
    rev_mode = str(roster.get("pr_reviewer_mode") or "hybrid")
    merge_rule = "Worker executes `gh pr merge --squash --delete-branch` when CI green & only P2 issues remain" if auto_merge else "Stop at Ready-to-Merge & report PR URL for human merge click"
    advice.append(f"Policy: reviewer={rev_mode}; closeout={merge_rule}; max review-fix rounds=2 before escalating.")

    if task_hint:
        hl = task_hint.lower()
        if any(k in hl for k in ("p0", "arch", "plan")):
            advice.append("P0/Architecture gate: Draft in primary orchestrator -> optional second-opinion review -> decompose.")
        if any(k in hl for k in ("back", "api", "db", "review")):
            advice.append("Backend/Review: Assign backend specialist; run local pre-review before push on high-risk changes.")
        if any(k in hl for k in ("pr", "commit")):
            advice.append("PR flow: Worker commits/pushes/opens PR -> parent calls `watch_pull_request` (no polling workers).")

    lines.append("\n## 5. Dispatch Guidance")
    for a in advice:
        lines.append(f"- {a}")

    return "\n".join(lines)


def write_message(msg: dict[str, Any], framed: bool) -> None:
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if framed:
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header + raw)
    else:
        sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def read_messages() -> tuple[dict[str, Any], bool] | None:
    buf = sys.stdin.buffer
    while True:
        first = buf.readline()
        if not first:
            return None
        stripped = first.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(b"content-length:"):
            length = int(stripped.split(b":", 1)[1].strip())
            while True:
                hdr = buf.readline()
                if not hdr or hdr in (b"\r\n", b"\n"):
                    break
            body = buf.read(length)
            return json.loads(body.decode("utf-8")), True
        return json.loads(stripped.decode("utf-8")), False


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        proto = params.get("protocolVersion") or "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"protocolVersion": proto, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO},
        }
    if method == "notifications/initialized" or req_id is None:
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [TOOL_DEF]}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name != "get_dispatch_brief":
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
        text = build_brief(
            task_hint=str(args.get("task_hint") or ""),
            include_all=bool(args.get("include_all", False)),
        )
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}], "isError": False}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        print(build_brief(include_all=True))
        return 0
    while True:
        item = read_messages()
        if item is None:
            return 0
        msg, framed = item
        resp = handle_request(msg)
        if resp is not None:
            write_message(resp, framed)


if __name__ == "__main__":
    raise SystemExit(main())
