# /kb 知识库路由

将自然语言指令映射到 Vault MCP 工具。极薄路由层，只做命令分发和参数提取。

## 命令映射

| 用户说 | 调用 MCP 工具 |
|--------|--------------|
| 「初始化知识库」「/kb init」 | `vault_init` |
| 「保存到知识库」「记住这个」 | `vault_save` |
| 「搜索知识库」「/kb search <关键词>」 | `vault_search` |
| 「恢复上下文」「/kb resume <项目>」 | `vault_resume` |
| 「列出笔记」「/kb list」 | `vault_list` |
| 「知识库统计」「/kb stats」 | `vault_stats` |
| 「找孤立笔记」「/kb orphan」 | `vault_orphan` |
| 「更新笔记」「/kb update」 | `vault_update` |
| 「标签列表」「/kb tags」 | `vault_tags` |
| 「写工作日志」「/kb log」 | `vault_log` |
| 「构建代码图谱」「/kb graphify build」 | `graphify_build` |
| 「图谱状态」「/kb graphify status」 | `graphify_status` |
| 「搜索符号」「/kb graphify query」 | `graphify_query` |

## 保存流程

当用户说「保存到知识库」时，按以下步骤执行：

1. **回顾对话**，提取问题背景、解决方案、关键代码片段
2. **确定元数据**：
   - `title` — 简洁描述，用中文（如 "Windows Git Bash 中 subprocess 编码问题"）
   - `tags` — 相关技术栈关键词（如 `["windows", "python", "subprocess", "encoding"]`）
   - `type` — 根据内容选择：`solution`（问题解决）/ `permanent`（永久知识）/ `concept`（概念）/ `tool`（工具技巧）
   - `project` — 如果与特定项目相关则填写
3. **构建 Markdown 正文** — 包含问题背景、解决方案、关键命令/代码、参考链接。手动添加 `[[已知笔记标题]]` 格式的 wikilink。如果记不住有哪些已知笔记，可先用纯文本标题，`vault_save` 会**自动检测**已知笔记标题的纯文本出现，将其替换为 `[[wikilink]]` 格式（无需手动逐个加链接）
4. **调用 `vault_save`**：
   ```json
   {
     "title": "...",
     "content": "...",
     "tags": ["..."],
     "type": "solution",
     "project": "optional"
   }
   ```
5. **告知用户保存结果**：
   - 文件路径（如 `permanent/windows-git-bash-zhong-subprocess-bian-ma-wen-ti.md`）
   - wikilink 发现数量（`wikilinks_found`）和自动建议数量（`wikilinks_auto_suggested`）
   - 如果是更新已有笔记则标明 `action: updated`

## 三层代码查询策略

修改代码前，按优先级逐层查询。上层信息足够时不再深入：

```
用户: "这个 Bug 在哪" / "怎么改这个功能"
         |
         v
┌─────────────────────────────────────────────┐
│ 第一层: graphify_query + graphify_status     │
│ - graphify_query(symbol) → 符号归属+调用链   │
│ - graphify_status() → 模块概览               │
│ 耗时: <10ms    消耗: ~100 token              │
│ 优先使用！信息足够即停止。                     │
└────────────────────┬────────────────────────┘
                     | 信息不够
                     v
┌─────────────────────────────────────────────┐
│ 第二层: vault_search 搜索图谱+知识笔记        │
│ - vault_search() → graphify/ + permanent/    │
│ - vault_resume() → 项目架构决策               │
│ 耗时: <50ms    消耗: ~500 token              │
└────────────────────┬────────────────────────┘
                     | 仍不够（需看具体代码）
                     v
┌─────────────────────────────────────────────┐
│ 第三层: 直接 Read 原始代码文件               │
│ - 前两层定位到具体文件后，精确 Read            │
│ 耗时: 视文件    消耗: 视文件                  │
└─────────────────────────────────────────────┘
```

**规则：**
1. 第一层：`graphify_query` + `vault_search(graphify/)` — 符号归属和调用链
2. 第二层：`vault_search(permanent/)` — 模块职责和历史方案
3. 第三层：仅当前两层不足时，才直接 Read 原始代码文件

## 自动行为

以下场景 Claude 应主动执行知识库操作，无需用户显式命令：

### 解决问题后提示保存

当解决了一个非平凡问题（超过 3 步操作或跨文件修改）时：
- 主动问用户：「这个解决方案可以保存到知识库，要记录吗？」
- 用户确认后执行保存流程
- 自动识别相关技术栈标签（根据对话中出现的语言、框架、工具）

### 遇到错误时自动搜索

当遇到编译错误、运行时异常、配置问题时：
- 自动调用 `vault_search` 搜索相关错误关键词
- 如果找到匹配笔记，优先应用笔记中的解决方案
- 搜索范围覆盖 permanent/ 和 graphify/ 目录

### 修改代码前检查图谱状态

当修改项目代码文件（.py/.ts/.js/.go/.java/.cs/.rs 等）时：
1. 先调用 `graphify_status` 检查代码图谱是否过期（超过 7 天未构建，或 commit 不匹配）
2. 如果过期，提醒用户：「代码图谱已过期，建议运行 `/kb graphify build` 更新」
3. 如果图谱有效，优先用 `graphify_query` 查找相关模块调用链

### 会话日志记录

每次编码会话结束时：
1. 调用 `vault_log` 写入本次会话摘要
2. 参数包含：`project`（项目名）、`summary`（做了什么）、`decisions`（关键决策）、`todos`（待办事项）

## graphify 构建流程

当用户说「构建代码图谱」「/kb graphify build」或系统提示图谱过期时：

1. **确定参数**：
   - `project` — 当前项目名（从 CLAUDE.md 或对话上下文中获取）
   - `project_dir` — 项目根目录的绝对路径
2. **调用 `graphify_build`**：
   ```json
   {
     "project": "myproject",
     "project_dir": "/path/to/project",
     "force": true
   }
   ```
3. **等待结果**（最长 120 秒）：
   - 成功：返回 `node_count`（节点数）、`edge_count`（边数）、`community_count`（社区数）
   - 失败：检查 graphify CLI 是否安装（`pip install graphifyy`）或项目目录是否正确
4. **报告结果**：
   > 代码图谱构建完成！myproject: 42 个模块，87 条依赖关系，5 个社区。图谱笔记已写入 ~/vault/graphify/myproject/。
5. **后续使用**：
   - 用 `graphify_query` 搜索任意符号
   - 用 `vault_search` 检索图谱笔记
   - 在 Obsidian 中打开 Graph View 可视化浏览

## 通用约定

- 笔记使用中文撰写，技术术语保留英文
- 内部链接使用 Obsidian `[[wikilink]]` 格式，禁止 Markdown `[text](url)` 格式做内部链接
- `type: permanent` 的笔记应包含至少 2 个 wikilink
- 文件名由 `vault_save` 自动生成为 kebab-case
