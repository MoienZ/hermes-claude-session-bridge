# How the directory-name encoding was derived (and how to re-verify it)

Claude Code stores sessions under:

```
~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl
```

`<encoded-cwd>` is the session's working directory with every character that is
**not** ASCII `[A-Za-z0-9_-]` replaced by a single `-` (this includes `\`, `:`,
`.`, spaces, and each CJK character counting as one `-`).

## Verification against real directories

```
C:\Users\Administrator\Nutstore\1\我的坚果云\00-皓琳文档\20260903-病例扫描件
→ C--Users-Administrator-Nutstore-1-------00------20260903------
                                                ^ 我的坚果云 = 5 chars → 5 dashes
                                                    ^ 皓琳文档 = 4 chars → 4 dashes
                                                              ^ 病例扫描件 = 5 chars → 5 dashes

C:\Users\Administrator\Documents\Moien\01-摸鱼天地\20260716-EVEOnline挂机脚本
→ C--Users-Administrator-Documents-Moien-01------20260716-EVEOnline----
```

Both derived names matched the real on-disk directories exactly.

## Reference implementation

```python
def encode_project_dir(cwd: str) -> str:
    return "".join(
        c if (c.isascii() and (c.isalnum() or c in "-_")) else "-"
        for c in cwd
    )
```

## Re-verify on your machine

```bash
# List real project dirs
ls ~/.claude/projects/
# Pick one, find a session inside it, and check its recorded cwd
head -1 ~/.claude/projects/<some-dir>/<some-session>.jsonl | python3 -c \
  "import json,sys; print(json.loads(sys.stdin.readline())['cwd'])"
# Then encode that cwd with the function above and compare
```

## Notes

- Drive letter `C:` becomes `C-` + `-` = `C--` (the `:` is one dash, the `\` is another).
- The encoding is per-character; it never collapses consecutive dashes.
- Claude Code resolves `--resume <sessionId>` by reading the file directly, so
  the directory name only needs to be *consistent* for the picker/UI grouping —
  but matching the real encoding keeps sessions listed under the right project.
