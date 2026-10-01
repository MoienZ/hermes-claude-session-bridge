# Hermes ↔ Claude Code 会话互导

把 Hermes 会话喂给 Claude Code（`claude --resume <uuid>` 可恢复、带完整工具调用链），以及把 Claude Code / Codex CLI 会话导入 Hermes。当用户说"把这个会话给 Claude Code / 在 Claude 里继续这个会话 / 导入 Claude 的会话 / 会话迁移"时使用。（实测于 Claude Code 2.1.285 + Hermes 0.21.5 + Windows）

**关键事实（实测验证）**：
- `hermes sessions export --format trace` 输出的就是 **Claude Code 原生 jsonl 格式**（uuid/parentUuid/message 结构逐字段兼容），这是双向桥的基石
- trace 保留完整工具调用链：`tool_use`（含 id/name/input）+ `tool_result`（含 tool_use_id/content）配对无损
- Claude Code 按 **sessionId 直连** `~/.claude/projects/<dir>/<sessionId>.jsonl` 恢复，无独立索引文件，注入即生效
- **Claude→Hermes 是有损的**：`hermes sessions import` 把整个会话压缩成 1条user + 1条assistant（工具调用变 `[ran tool: X]` 占位文本）。要做无损归档用 Claude 原生 jsonl 备份，导入 Hermes 只为了"继续聊"

## 流程 A：Hermes → Claude Code（无损，核心流程）

1. 找会话 ID：`hermes sessions list`（必要时 `--source feishu` 等过滤，`--limit 30`）
2. 导出：`hermes sessions export "<tmp>/x.trace" --session-id <hermes_id> --format trace`
3. 转换注入：`python <skill目录>/scripts/hermes_to_claude.py "<x.trace>"`（脚本自动做下面所有事）
4. 把输出里的 `claude --resume <uuid>` 命令告诉用户，提醒先 `cd <cwd>`

脚本做的转换（勿手写，边界都在脚本里）：
- 生成新 UUID 作 sessionId；替换每行 sessionId
- cwd 处理：会话 cwd 存在→用之；不存在→回退用户主目录；gateway 会话默认 Hermes 工作目录
- 项目目录名编码：`C:\Users\X\我的目录` → `C--Users-X-------`（规则：ASCII 字母数字 `-_` 保留，其余每个字符含中文/`\`/`:`/`.`/空格 → 一个 `-`）
- 前导元数据行：补 `{"type":"mode","mode":"normal"}` + `{"type":"permission-mode","permissionMode":"bypassPermissions"}`
- 单行 >10 万字符的巨型 tool_result 原样保留（Claude 3.3MB 会话实测通过）

验证（必须做）：注入后 `cd <cwd> && claude --resume <uuid> -p "用一句话概括这个会话开头用户要求做什么"`，能准确复述即成功。 `-p` 模式会追加对话到注入文件（Claude 正常行为，非污染）。

## 流程 B：Claude Code → Hermes

```
hermes sessions import --from claude                        # 交互选择
hermes sessions import --from claude "<path>.jsonl"         # 直接指定
hermes sessions import --from codex                         # Codex CLI (~/.codex/sessions)
```
结果：新 Hermes 会话 `<id>`，`hermes --resume <id>` 继续。**记住是有损压缩**（见上）。

配置级导入（CLAUDE.md→记忆、Bash 白名单→command_allowlist、MCP servers、skills；密钥永不导入）：
```
hermes import-agent claude-code [--dry-run] [--overwrite --yes] [--sync]
```

## 边界与坑（全部实测）

| 情况 | 结论/处理 |
|---|---|
| Claude 恢复时报 unrecognized_model（如 glm-5.3 网关） | 只是计费提示，**不影响恢复**，上下文完整 |
| 不在原 cwd 下 `--resume` | 照常工作（按 sessionId 定位）；但工具里的相对路径语义会错，建议先 cd |
| `--fork-session` | 生成新文件续写，原注入文件不动；不加则追加进注入文件（都正常） |
| 会话 cwd 目录已删除 | 脚本回退到用户主目录，恢复不受影响 |
| 中文/空格/点号路径 | 目录名编码规则已验证（每个非 ASCII 字符→一个`-`） |
| Hermes gateway 会话（feishu/weixin） | trace 正常，cwd 默认 Hermes 工作目录；3.3MB/2035行/947工具调用实测通过 |
| Hermes 工具名（terminal/read_file）与 Claude（Bash/Read）不同 | **不需要映射**——Claude 把它们当作历史工具调用原文读取，能正确复述；只有续写时新调用才用 Claude 自己的工具 |
| thinking 块 | Hermes trace 不导出 thinking；Claude 原生会话里的 thinking 在导入 Hermes 时丢失 |
| 会话里有图片 | Hermes trace 无 image 块；图片上下文不迁移 |
| claude CLI 不在 PATH | 流程 A 注入仍成功，但用户无法 resume；提示安装 |
| skill 安装目录 | Hermes 真实 skills 根是 `~/AppData/Local/hermes/skills/`（不是 `~/.hermes/skills/`） |
| Windows claude.cmd 与 bash 路径 | 注入用 Python（原生路径），验证命令在 git-bash 里 `cd` 后执行 |

## 相关命令速查

```bash
hermes sessions list [--source X] [--limit N]        # 找会话
hermes sessions export <out> --session-id <id> --format trace|md|jsonl|html
claude --resume <uuid> [-p "..."] [--fork-session]   # 恢复
claude --continue                                     # 最近会话（勿用于注入会话）
```
