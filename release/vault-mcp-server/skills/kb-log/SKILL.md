# /kb-log 会话日志

写入会话日志到 Vault。调用 `vault_log(project, summary, decisions?, todos?)`。
AI 从对话提取 summary/decisions/todos，project 从 CWD 推断。
