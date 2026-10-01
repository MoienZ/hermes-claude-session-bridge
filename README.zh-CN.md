# hermes-claude-session-bridge

**[Hermes Agent](https://hermes-agent.nousresearch.com/) ↔ [Claude Code](https://code.claude.com/) 会话互通桥 — 双向迁移，工具调用链完整保留。**

- **Hermes → Claude Code（无损）**：把任意 Hermes 会话注入 Claude Code，`claude --resume <uuid>` 直接恢复 — 完整历史，包括每一对 `tool_use` / `tool_result`。
- **Claude Code → Hermes**：一条命令导入 Claude Code（或 Codex CLI）会话到 Hermes。*该方向有损，见[保真度说明](#保真度两个方向各保留什么)。*

**核心原理**：`hermes sessions export --format trace` 导出的就是 **Claude Code 原生会话 JSONL 格式**（逐字段兼容：`uuid` / `parentUuid` / `message{role, content[]}`）。一个小脚本重新盖 `sessionId`、编码项目目录名、把文件放到 Claude Code 期望的位置即可。无索引文件、无 API 黑科技 — Claude Code 直接读 `~/.claude/projects/<dir>/<sessionId>.jsonl`。

已在 **Claude Code 2.1.285 + Hermes Agent 0.21.5 + Windows 10** 上实测（含 3.3 MB / 2,035 行 / 947 次工具调用的会话）。

---

## 安装

### 作为 Hermes skill（推荐）

```bash
git clone https://github.com/MoienZ/hermes-claude-session-bridge.git
# Windows
xcopy /E /I hermes-claude-session-bridge "%LOCALAPPDATA%\hermes\skills\hermes-claude-session-bridge"
# Linux / macOS / WSL
cp -r hermes-claude-session-bridge ~/.hermes/skills/ 2>/dev/null || \
  cp -r hermes-claude-session-bridge "${HERMES_HOME:-$HOME/.hermes}"/skills/
```

验证：`hermes skills list` 应显示 `hermes-claude-session-bridge … enabled`。

### 纯脚本（不装 skill）

`scripts/hermes_to_claude.py` 是零依赖的单文件脚本（Python 3.10+）：

```bash
python scripts/hermes_to_claude.py session.trace
```

---

## 使用

### A. 把 Hermes 会话喂给 Claude Code（无损）

```bash
# 1. 找会话
hermes sessions list                       # 可加 --source feishu --limit 30 过滤

# 2. 导出为 trace（= Claude Code 原生 JSONL）
hermes sessions export /tmp/x.trace --session-id 20261001_112408_a75817 --format trace

# 3. 注入 Claude Code 会话库
python scripts/hermes_to_claude.py /tmp/x.trace
```

输出：

```
会话统计: user=140 assistant=137 tool_use=135 tool_result=135 | 279行 644KB
工作目录: C:\Users\Administrator\Documents\Hermes
✓ 已注入。在 Claude Code 里恢复:
    cd "C:\Users\Administrator\Documents\Hermes"
    claude --resume e0353132-c44a-4a7f-9f4d-fff6e87169ae
```

```bash
# 4. 在 Claude Code 里恢复
cd "C:\Users\Administrator\Documents\Hermes"
claude --resume e0353132-c44a-4a7f-9f4d-fff6e87169ae
```

完成。Claude Code 会看到完整对话（含全部工具调用），就像发生在它自己那里一样。

**脚本参数**

| 参数 | 作用 |
|---|---|
| `--cwd <dir>` | 覆盖会话工作目录（必须存在，否则带警告回退） |
| `--dry-run` | 只打印统计和目标路径，不写文件 |

**注入后务必验证**（一次调用的事）：

```bash
claude --resume <uuid> -p "用一句话概括这个会话开头用户要求做什么"
```

### B. 导入 Claude Code / Codex CLI 会话到 Hermes

Hermes ≥ 0.21.5 内置：

```bash
hermes sessions import --from claude            # 交互选择 ~/.claude/projects 下的会话
hermes sessions import --from claude "<path>.jsonl"
hermes sessions import --from codex             # Codex CLI (~/.codex/sessions)
```

然后 `hermes --resume <新id>` 继续。

**配置级导入**（CLAUDE.md → 记忆、Bash 权限白名单 → `command_allowlist`、MCP 服务器、skills；密钥永不导入）：

```bash
hermes import-agent claude-code [--dry-run] [--overwrite --yes] [--sync]
```

---

## 注入原理

Claude Code 把会话存在 `~/.claude/projects/<编码后的cwd>/<sessionId>.jsonl`，`--resume <sessionId>` 直接读文件 — 没有独立索引需要更新。脚本因此：

1. **生成全新 UUID** 作为新 `sessionId`（不与现有会话冲突，原 Hermes 会话不动）。
2. **逐行重盖** `sessionId` 和 `cwd`。
3. **编码项目目录名**，规则与 Claude Code 完全一致：ASCII `[A-Za-z0-9_-]` 保留，其余每个字符（中文、`\`、`:`、`.`、空格）变成一个 `-`：

   ```
   C:\Users\Administrator\Nutstore\1\我的坚果云\00-皓琳文档\20260903-病例扫描件
   → C--Users-Administrator-Nutstore-1-------00------20260903------
   ```
   （规则由 3 个真实项目目录推导并验证。详见 [docs/directory-encoding.md](docs/directory-encoding.md)。）
4. **前插元数据行** `{"type":"mode","mode":"normal"}` 和 `{"type":"permission-mode","permissionMode":"bypassPermissions"}`，贴近原生文件（严格说非必需 — 裸 2 行文件也能恢复 — 但跨版本更稳）。
5. **跳过损坏 JSON 行**并告警；文件缺失/空文件返回非零退出码。

**cwd 回退**：会话原工作目录已不存在时，脚本回退到用户主目录并明确提示。恢复不受影响，只有旧工具调用里的相对路径语义会变。

---

## 保真度：两个方向各保留什么

| 内容 | Hermes → Claude Code | Claude Code → Hermes |
|---|---|---|
| 用户/助手文本 | ✅ 无损 | ✅ 无损 |
| 工具调用（`tool_use` + `tool_result` 配对） | ✅ 无损，ID 完整 | ⚠️ 压缩成 `[ran tool: X]` 占位文本 |
| thinking / 推理块 | ❌ `--format trace` 不导出 | ❌ 丢失 |
| 图片 | ❌ trace 无 image 块 | ❌ 丢失 |
| 工具名（`terminal` vs `Bash`、`read_file` vs `Read`） | ✅ **无需映射** — Claude Code 把它们当历史读取并理解；它自己发起的新调用才用自己的工具 | 不适用 |

**为什么 Claude→Hermes 有损**：`hermes sessions import` 把整个会话压缩成 1 条用户消息 + 1 条长助手消息（工具调用变占位文本）。它面向"继续聊"，不是归档。要无损归档，请保留原始 `~/.claude/projects/**.jsonl` 文件。

## 常见坑（全部实测验证）

| 情况 | 结果 |
|---|---|
| 恢复时报 `unrecognized_model`（如 glm-5.3 网关） | 只是计费层提示 — **恢复正常，上下文完整** |
| 在别的 cwd 下 `--resume` | 可用（按 sessionId 定位），但旧工具调用里的相对路径会有歧义 — 建议先 `cd` |
| `--fork-session` | 续写进**新**文件；不加则新对话追加进注入文件（都是正常行为） |
| `-p` 验证运行 | 会追加进注入文件 — 正常，不是污染 |
| 超大 tool_result（单行 > 100 KB） | 原样保留；3.3 MB 会话已验证 |
| Hermes gateway 会话（飞书/微信来源） | 导出正常；cwd 默认为 Hermes 工作目录 |
| `claude` CLI 未安装 | 注入照样成功，但装好前无法 resume |

## 测试矩阵（真实执行，非纸面推演）

| # | 场景 | 结果 |
|---|---|---|
| 1 | 最小 2 行会话注入→恢复 | ✅ Claude 准确复述 ARIS 插件任务 |
| 2 | 工具调用链往返（5 对 `tool_use`/`tool_result`） | ✅ 复述出 `date` 命令和"文件不存在→创建→读取"链路 |
| 3 | **3.3 MB / 2,035 行 / 947 次工具调用** | ✅ 739 次 terminal 调用数对了，最后一条用户消息复述正确 |
| 4 | 7 月的专利审查会话（644 KB）端到端 | ✅ 复述出交付物文件名 |
| 5 | 跨 cwd 恢复 / `--fork-session` | ✅ / ✅ 新文件续写，原文件不动 |
| 6 | 中文路径目录编码 | ✅ 规则与 3 个真实目录完全一致 |
| 7 | cwd 不存在 / 空文件 / 坏 JSON 行 / 文件缺失 | ✅ 优雅回退、告警、非零退出码 |

单元测试：`python tests/test_bridge.py`（11 项）。

## FAQ

**会动我原来的 Hermes 会话吗？** 不会。脚本只读导出的 `.trace` 文件，往 `~/.claude/projects/` 写一个新文件。

**能 Claude → Hermes → Claude 无损往返吗？** 不能 — Claude→Hermes 那步有损（见上表）。无损往返请归档原始 Claude JSONL，直接注入它。

**Linux / macOS 可用吗？** 机制完全相同（同样的 `~/.claude/projects` 布局），脚本是纯跨平台 Python，只有 skill 安装路径不同。本仓库在 Windows 上开发验证，欢迎其他平台反馈。

**支持哪些 Claude Code 版本？** 在 2.1.285 上验证。JSONL 结构（uuid/parentUuid/message）一直很稳定；未来版本若不兼容，验证一步会立刻暴露。

**Hermes 装好的 skill 到底放哪？** Windows 是 `~/AppData/Local/hermes/skills/` — **不是** `~/.hermes/skills/`。

## 许可

MIT — 见 [LICENSE](LICENSE)。

## 致谢

基于 [Hermes Agent](https://hermes-agent.nousresearch.com/)（Nous Research）构建。这座桥之所以存在，是因为 Hermes 的 `--format trace` 导出天生就说 Claude Code 的 JSONL 方言 — 本仓库只是把两头接上了。
