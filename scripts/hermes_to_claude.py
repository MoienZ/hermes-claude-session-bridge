#!/usr/bin/env python3
"""Hermes trace → Claude Code session jsonl 注入器。

用法:
    python hermes_to_claude.py <trace文件> [--cwd <目录>] [--name <标题>]
                               [--dry-run] [--fork]

输入: `hermes sessions export <out>.trace --session-id <id> --format trace` 的产物
      (本身就是 Claude 原生 jsonl 行格式)。
输出: 写入 ~/.claude/projects/<编码目录>/<新uuid>.jsonl 并打印恢复命令。

设计依据 (实测于 Claude Code 2.1.285 / Hermes 0.21.5):
- Claude 按 sessionId 直连 projects/<dir>/<sid>.jsonl, 无索引文件
- 目录名编码: ASCII [A-Za-z0-9_-] 保留, 其余每字符(含中文/\\/ :/./空格) → 一个 '-'
- 前导 mode/permission-mode 行非必需(最小 2 行注入已验证), 但补上更贴近原生
"""
import argparse
import json
import os
import sys
import uuid


def encode_project_dir(cwd: str) -> str:
    """Claude Code 项目目录名编码 (逐字符规则, 与原生实测 100% 一致)。"""
    return "".join(
        c if (c.isascii() and (c.isalnum() or c in "-_")) else "-"
        for c in cwd
    )


def pick_cwd(trace_path: str, override: str | None) -> tuple[str, bool, str]:
    """返回 (使用的cwd, 是否回退, 说明)。优先级: --cwd > trace首行cwd(存在时) > 用户主目录。"""
    home = os.path.expanduser("~")
    if override:
        if os.path.isdir(override):
            return override, False, ""
        return home, True, f"--cwd 指定的 {override} 不存在"
    first = None
    with open(trace_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                first = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
    cwd = (first or {}).get("cwd") if isinstance(first, dict) else None
    if cwd and os.path.isdir(cwd):
        return cwd, False, ""
    if cwd:
        return home, True, f"会话原目录 {cwd} 已不存在"
    return home, True, "trace 未携带 cwd"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace", help="hermes sessions export --format trace 输出文件")
    ap.add_argument("--cwd", help="覆盖会话工作目录 (默认取 trace 首行, 不存在则回退主目录)")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不写文件")
    ap.add_argument("--fork", action="store_true", help="注入副本命名带 -hermes 后缀标题提示")
    args = ap.parse_args()

    if not os.path.isfile(args.trace):
        print(f"error: 找不到 {args.trace}", file=sys.stderr)
        return 2

    rows, bad = [], 0
    with open(args.trace, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        print(f"warning: 跳过 {bad} 行损坏 JSON", file=sys.stderr)
    if not rows:
        print("error: trace 中没有有效行", file=sys.stderr)
        return 2

    cwd, fell_back, why = pick_cwd(args.trace, args.cwd)
    new_sid = str(uuid.uuid4())

    out_lines = [
        json.dumps({"type": "mode", "mode": "normal", "sessionId": new_sid}),
        json.dumps({"type": "permission-mode", "permissionMode": "bypassPermissions", "sessionId": new_sid}),
    ]
    stats = {"user": 0, "assistant": 0, "tool_use": 0, "tool_result": 0, "other": 0}
    for d in rows:
        d["sessionId"] = new_sid
        d["cwd"] = cwd
        t = d.get("type")
        if t in ("user", "assistant"):
            stats[t] += 1
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        stats["tool_use"] += 1
                    elif isinstance(b, dict) and b.get("type") == "tool_result":
                        stats["tool_result"] += 1
        elif t:
            stats["other"] += 1
        out_lines.append(json.dumps(d, ensure_ascii=False))

    proj_dir = os.path.join(
        os.path.expanduser("~"), ".claude", "projects", encode_project_dir(cwd)
    )
    dst = os.path.join(proj_dir, new_sid + ".jsonl")
    size_kb = sum(len(l.encode("utf-8")) + 1 for l in out_lines) // 1024

    print(f"会话统计: user={stats['user']} assistant={stats['assistant']} "
          f"tool_use={stats['tool_use']} tool_result={stats['tool_result']} "
          f"其他行={stats['other']} | {len(out_lines)}行 {size_kb}KB")
    print(f"工作目录: {cwd}" + (f"  (已回退: {why})" if fell_back else ""))
    print(f"目标文件: {dst}")

    if args.dry_run:
        print("dry-run: 未写入")
    else:
        os.makedirs(proj_dir, exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out_lines) + "\n")
        print(f"\n✓ 已注入。在 Claude Code 里恢复:\n")
        print(f"    cd \"{cwd}\"")
        print(f"    claude --resume {new_sid}")
        print(f"\n  验证 (非交互): claude --resume {new_sid} -p \"用一句话概括这个会话开头用户要求做什么\"")
        print(f"  续写不污染原文件: claude --resume {new_sid} --fork-session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
