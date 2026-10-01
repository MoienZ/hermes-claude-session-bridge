# hermes-claude-session-bridge

**Bridge conversations between [Hermes Agent](https://hermes-agent.nousresearch.com/) and [Claude Code](https://code.claude.com/) — both directions, with full tool-call fidelity.**

- **Hermes → Claude Code (lossless):** inject any Hermes session into Claude Code so `claude --resume <uuid>` picks it up — complete history including every `tool_use` / `tool_result` pair.
- **Claude Code → Hermes:** import Claude Code (or Codex CLI) sessions into Hermes with one command. *Lossy by design — see [Fidelity](#fidelity-what-survives-each-direction).*

The whole trick: `hermes sessions export --format trace` emits **Claude Code's native session JSONL format** (field-for-field compatible: `uuid` / `parentUuid` / `message{role, content[]}`). A tiny script re-stamps the `sessionId`, encodes the project directory name, and drops the file where Claude Code expects it. No index files, no API hacks — Claude Code reads `~/.claude/projects/<dir>/<sessionId>.jsonl` directly.

Verified against **Claude Code 2.1.285 + Hermes Agent 0.21.5 on Windows 10** (including a 3.3 MB / 2,035-line / 947-tool-call session).

---

## Install

### As a Hermes skill (recommended)

```bash
git clone https://github.com/MoienZ/hermes-claude-session-bridge.git
# Windows
xcopy /E /I hermes-claude-session-bridge "%LOCALAPPDATA%\hermes\skills\hermes-claude-session-bridge"
# Linux / macOS / WSL
cp -r hermes-claude-session-bridge ~/.hermes/skills/ 2>/dev/null || \
  cp -r hermes-claude-session-bridge "${HERMES_HOME:-$HOME/.hermes}"/skills/
```

Verify: `hermes skills list` should show `hermes-claude-session-bridge … enabled`.

### Standalone (script only)

You don't need the skill — `scripts/hermes_to_claude.py` is a single-file Python 3.10+ script with zero dependencies:

```bash
python scripts/hermes_to_claude.py session.trace
```

---

## Usage

### A. Feed a Hermes session to Claude Code (lossless)

```bash
# 1. Find the session
hermes sessions list                       # or: --source feishu --limit 30

# 2. Export as trace (= Claude Code native JSONL)
hermes sessions export /tmp/x.trace --session-id 20261001_112408_a75817 --format trace

# 3. Inject into Claude Code's session store
python scripts/hermes_to_claude.py /tmp/x.trace
```

Output:

```
会话统计: user=140 assistant=137 tool_use=135 tool_result=135 | 279行 644KB
工作目录: C:\Users\Administrator\Documents\Hermes
✓ 已注入。在 Claude Code 里恢复:
    cd "C:\Users\Administrator\Documents\Hermes"
    claude --resume e0353132-c44a-4a7f-9f4d-fff6e87169ae
```

```bash
# 4. Resume in Claude Code
cd "C:\Users\Administrator\Documents\Hermes"
claude --resume e0353132-c44a-4a7f-9f4d-fff6e87169ae
```

That's it. Claude Code sees the full conversation — including every tool call — as if it had happened there.

**Script options**

| Flag | Effect |
|---|---|
| `--cwd <dir>` | Override the session working directory (must exist; falls back with a warning otherwise) |
| `--dry-run` | Print stats and target path without writing |

**Always verify** after injecting (takes one call):

```bash
claude --resume <uuid> -p "用一句话概括这个会话开头用户要求做什么"
# or: "Summarize the first user request in this session in one sentence"
```

### B. Import a Claude Code / Codex CLI session into Hermes

Built into Hermes ≥ 0.21.5:

```bash
hermes sessions import --from claude            # interactive picker over ~/.claude/projects
hermes sessions import --from claude "<path>.jsonl"
hermes sessions import --from codex             # Codex CLI (~/.codex/sessions)
```

Then `hermes --resume <new-id>` to continue.

**Config-level import** (CLAUDE.md → memories, Bash permission allowlist → `command_allowlist`, MCP servers, skills; credentials are never imported):

```bash
hermes import-agent claude-code [--dry-run] [--overwrite --yes] [--sync]
```

---

## How the injection works

Claude Code stores sessions at `~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl` and resolves `--resume <sessionId>` by reading that file directly — there is no separate index to update. The script therefore:

1. **Generates a fresh UUID** as the new `sessionId` (no collision with existing sessions, original Hermes session untouched).
2. **Re-stamps** `sessionId` and `cwd` on every line.
3. **Encodes the project directory name** exactly like Claude Code does: ASCII `[A-Za-z0-9_-]` kept, every other character (Chinese, `\`, `:`, `.`, space) becomes one `-`.

   ```
   C:\Users\Administrator\Nutstore\1\我的坚果云\00-皓琳文档\20260903-病例扫描件
   → C--Users-Administrator-Nutstore-1-------00------20260903------
   ```
   (This rule was derived and verified against 3 real project directories.)
4. **Prepends metadata lines** `{"type":"mode","mode":"normal"}` and `{"type":"permission-mode","permissionMode":"bypassPermissions"}` to closely mirror native files. (Not strictly required — a bare 2-line file also resumes — but safer across versions.)
5. **Skips corrupt JSON lines** with a warning; non-zero exit on missing/empty files.

**cwd fallback:** if the session's original working directory no longer exists, the script falls back to your home directory and says so. Resume still works; only relative-path semantics inside old tool calls change.

---

## Fidelity: what survives each direction

| Content | Hermes → Claude Code | Claude Code → Hermes |
|---|---|---|
| User / assistant text | ✅ lossless | ✅ lossless |
| Tool calls (`tool_use` + `tool_result` pairs) | ✅ lossless, IDs intact | ⚠️ collapsed to `[ran tool: X]` placeholders |
| Thinking / reasoning blocks | ❌ not exported by `--format trace` | ❌ dropped |
| Images | ❌ no image blocks in trace | ❌ dropped |
| Tool names (`terminal` vs `Bash`, `read_file` vs `Read`) | ✅ **no mapping needed** — Claude Code reads them as history and understands them; new calls it makes use its own tools | n/a |

**Why Claude→Hermes is lossy:** `hermes sessions import` compresses the whole conversation into one user message + one long assistant message (tool calls become placeholder text). It's meant for *continuing a chat*, not archival. For lossless archives, keep the original `~/.claude/projects/**.jsonl` files.

## Gotchas (all verified)

| Situation | What happens |
|---|---|
| `unrecognized_model` warning on resume (e.g. glm-5.3 gateway) | Billing-layer notice only — **resume works, context intact** |
| Resuming from a different cwd | Works (resolved by sessionId), but relative paths in old tool calls become ambiguous — `cd` first |
| `--fork-session` | Writes continuation to a *new* file; without it, new turns append to the injected file (both normal) |
| `-p` verification runs | Append to the injected file — expected, not corruption |
| Sessions with huge tool results (single line > 100 KB) | Passed through as-is; 3.3 MB session verified |
| Hermes gateway sessions (Feishu/WeChat origin) | Export fine; cwd defaults to the Hermes working directory |
| `claude` CLI missing | Injection still succeeds, but you can't resume until it's installed |

## Test matrix (executed, not theoretical)

| # | Scenario | Result |
|---|---|---|
| 1 | Minimal 2-line session → resume | ✅ Claude accurately recalled the ARIS-plugin task |
| 2 | Tool-call roundtrip (5 `tool_use`/`tool_result` pairs) | ✅ recalled the `date` command and the create-then-read file chain |
| 3 | **3.3 MB / 2,035 lines / 947 tool calls** | ✅ counted 739 `terminal` calls correctly, recalled the final user message |
| 4 | July patent-review session (644 KB), end-to-end | ✅ recalled deliverable filenames from months earlier |
| 5 | Cross-cwd resume / `--fork-session` | ✅ / ✅ new file, original untouched |
| 6 | Chinese-path directory encoding | ✅ rule matches 3 real directories exactly |
| 7 | Missing cwd / empty file / corrupt JSON lines / missing file | ✅ graceful fallback, warnings, non-zero exit |

## FAQ

**Does this touch my original Hermes session?** No. The script only reads the exported `.trace` file and writes one new file into `~/.claude/projects/`.

**Can I go Claude → Hermes → Claude losslessly?** No — the Claude→Hermes step is lossy (see table). For a lossless round-trip, archive the original Claude JSONL and inject *that* back.

**Linux / macOS?** The mechanism is identical (same `~/.claude/projects` layout). The script is pure cross-platform Python; only the skill-install path differs. Developed and verified on Windows — reports from other platforms welcome.

**Which Claude Code versions?** Verified on 2.1.285. The JSONL schema (uuid/parentUuid/message) has been stable; if a future version breaks it, the verify step will catch it immediately.

**Where does Hermes actually keep installed skills?** `~/AppData/Local/hermes/skills/` on Windows — *not* `~/.hermes/skills/`. (Cost us an hour. You're welcome.)

## License

MIT — see [LICENSE](LICENSE).

## Credits

Built with [Hermes Agent](https://hermes-agent.nousresearch.com/) (Nous Research). The bridge exists because Hermes' `--format trace` export already speaks Claude Code's JSONL dialect — this repo just connects the ends.
