# Session JSONL format notes (Claude Code 2.1.285 / Hermes 0.21.5 trace)

One JSON object per line. Only `user` and `assistant` message rows are
required for `--resume` to reconstruct a conversation; the rest are metadata.

## Message rows (the part Hermes `--format trace` emits)

```jsonc
// user turn (plain text)
{
  "parentUuid": "<uuid|null>",      // chain pointer — Claude tolerates imperfect chains
  "isSidechain": false,
  "cwd": "C:\\path\\to\\project",
  "sessionId": "<uuid>",
  "version": "hermes-agent",        // any string works
  "uuid": "<uuid>",
  "timestamp": "2026-10-01T03:20:23.367Z",
  "type": "user",
  "message": { "role": "user", "content": "plain string" }
}

// user turn carrying tool results (content becomes an array)
{ "type": "user", "message": { "role": "user", "content": [
  { "type": "tool_result",
    "tool_use_id": "call_3c68310be3824b0fa97242d7",   // must match the tool_use id
    "content": "{\"output\": \"...\", \"exit_code\": 0}" }
], ... }, ... }

// assistant turn
{ "type": "assistant", "message": { "role": "assistant", "content": [
  { "type": "text", "text": "..." },
  { "type": "tool_use",
    "id": "call_3c68310be3824b0fa97242d7",
    "name": "terminal",                              // any name; see below
    "input": { "command": "date" } }
], ... }, ... }
```

## Metadata rows (optional; native files have them)

```jsonc
{ "type": "mode", "mode": "normal", "sessionId": "<uuid>" }
{ "type": "permission-mode", "permissionMode": "bypassPermissions", "sessionId": "<uuid>" }
{ "type": "atis-latch", "atis": "", "sessionId": "<uuid>" }
{ "type": "file-history-snapshot", "messageId": "<uuid>", "snapshot": { ... } }
{ "type": "attachment", ... }
{ "type": "last-prompt", ... }
{ "type": "queue-operation", ... }
{ "type": "ai-title", ... }
{ "type": "cost-state", ... }
```

The injector writes the first two. A bare file with *only* message rows also
resumes fine (verified with a 2-line file).

## What Claude Code does on `--resume <sessionId>`

1. Scans `~/.claude/projects/*/<sessionId>.jsonl` — no index file.
2. Replays `user`/`assistant` rows into context (including foreign tool names —
   it reads `terminal` / `read_file` as history and understands them; it only
   uses its own `Bash` / `Read` for *new* calls).
3. Appends new turns to the same file. `--fork-session` writes a new file with
   a fresh sessionId instead.

## Non-goals / known gaps

- `thinking` blocks are not present in Hermes trace exports.
- `image` content blocks are not exported either.
- `parentUuid` chains in injected files come from Hermes export as-is;
  imperfect chains did not affect resume in testing.
