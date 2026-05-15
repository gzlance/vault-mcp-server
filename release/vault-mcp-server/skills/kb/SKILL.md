# /kb 知识库路由

知识库统一入口。输入 `/kb` 显示全部可用命令。

## 笔记
| 命令 | 说明 |
|------|------|
| `/kb-save` | 保存笔记（AI 推断参数，CWD 自动 project） |
| `/kb-search <关键词>` | 全文搜索笔记 |
| `/kb-list` | 列出笔记 |
| `/kb-update <标题>` | 更新/追加笔记内容 |
| `/kb-delete <标题>` | 删除笔记（标题定位 + 级联清理） |
| `/kb-learn` | 保存学习笔记到 permanent/ |

## 会话
| 命令 | 说明 |
|------|------|
| `/kb-resume` | 恢复项目上下文（日志+待办+架构笔记） |
| `/kb-log <摘要>` | 写会话日志（同步待办到 todos 表） |

## 待办
| 命令 | 说明 |
|------|------|
| `/kb-todo-list` | 列出待办 |
| `/kb-todo-done <id>` | 标记完成 |
| `/kb-todo-progress <id>` | 标记进行中 |
| `/kb-todo-pending <id>` | 恢复待处理 |
| `/kb-todo-delete <id>` | 删除待办 |

## 代码图谱
| 命令 | 说明 |
|------|------|
| `/kb-graph-build <项目>` | 构建代码图谱 |
| `/kb-graph-status <项目>` | 图谱构建状态 |
| `/kb-graph-query <符号>` | 搜索符号调用链 |

## 管理
| 命令 | 说明 |
|------|------|
| `/kb-init` | 初始化 Vault |
| `/kb-stats` | 统计面板 |
| `/kb-tags` | 标签列表 |
| `/kb-orphan` | 孤立笔记 |

## 自动行为
- 缺少上下文时优先 vault_search 查知识库
- 解决非平凡问题后提示保存
- 修改代码前检查图谱新鲜度
- 项目未初始化时提示 /kb-init
