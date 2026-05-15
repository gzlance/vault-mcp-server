"""Vault MCP Server — 个人知识库 + 代码图谱 统一 MCP 服务。

基于 Obsidian Vault (~/vault/) 提供结构化存储、全文索引和代码图谱能力。
通过 MCP stdio 协议与 Claude Code 通信。
"""

import asyncio
import json
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from tools.graphify_tools import (
    handle_graphify_build,
    handle_graphify_query,
    handle_graphify_status,
)
from tools.vault_delete import handle_delete
from tools.vault_todo_done import handle_todo_done
from tools.vault_todo_delete import handle_todo_delete
from tools.vault_todo_list import handle_todo_list
from tools.vault_todo_pending import handle_todo_pending
from tools.vault_todo_progress import handle_todo_progress
from tools.vault_tools import (
    handle_init,
    handle_list,
    handle_log,
    handle_orphan,
    handle_resume,
    handle_save,
    handle_search,
    handle_stats,
    handle_tags,
    handle_update,
)

# 确保 PYTHONIOENCODING 为 UTF-8（Windows GBK 兼容）
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

server = Server("vault-mcp")


# ────────────────── 工具注册 ──────────────────


@server.list_tools()
async def list_tools() -> list[Tool]:
    """返回所有可用 MCP 工具列表。"""
    return [
        # ── P0 核心工具 ──
        Tool(
            name="vault_init",
            description="初始化 Vault 目录结构、模板文件和 SQLite 索引库。幂等操作——已初始化的部分自动跳过。",
            inputSchema={
                "type": "object",
                "properties": {
                    "vault_dir": {
                        "type": "string",
                        "description": "Vault 根目录路径，默认 ~/vault",
                    },
                    "project": {"type": "string", "description": "可选，同时初始化项目子目录"},
                },
            },
        ),
        Tool(
            name="vault_save",
            description="保存知识笔记到 Vault。校验 frontmatter 必填字段、匹配已有笔记生成 wikilink、写入 .md 文件并更新 SQLite 索引。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题"},
                    "content": {
                        "type": "string",
                        "description": "Markdown 正文（不含 frontmatter）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "permanent",
                            "solution",
                            "concept",
                            "tool",
                            "session-log",
                            "code-graph",
                        ],
                        "description": "笔记类型",
                    },
                    "project": {"type": "string", "description": "归属项目名"},
                    "vault_dir": {
                        "type": "string",
                        "description": "Vault 根目录路径，默认 ~/vault",
                    },
                },
                "required": ["title", "content", "tags", "type"],
            },
        ),
        Tool(
            name="vault_search",
            description="FTS5 全文搜索 Vault 笔记。返回结构化匹配结果，含标题、片段高亮、标签、相关度分数。搜索范围覆盖 permanent/ + project/ + graphify/。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "按标签过滤",
                    },
                    "project": {"type": "string", "description": "按项目过滤"},
                    "type": {"type": "string", "description": "按笔记类型过滤"},
                    "limit": {"type": "integer", "default": 10},
                    "offset": {"type": "integer", "default": 0},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="vault_resume",
            description="读取项目的最近会话日志和架构决策笔记，用于恢复工作上下文。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "项目名"},
                    "log_count": {
                        "type": "integer",
                        "default": 3,
                        "description": "返回最近 N 个会话日志",
                    },
                },
                "required": ["project"],
            },
        ),
        # ── P1 管理工具 ──
        Tool(
            name="vault_list",
            description="按条件结构化列出笔记，支持分页和排序。",
            inputSchema={
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "project": {"type": "string"},
                    "type": {"type": "string"},
                    "sort": {"type": "string", "enum": ["created", "updated", "title"]},
                    "limit": {"type": "integer", "default": 20},
                    "offset": {"type": "integer", "default": 0},
                },
            },
        ),
        Tool(
            name="vault_stats",
            description="返回知识库统计面板：笔记总数、按类型/项目分布、Top 标签、最近新增、链接密度。",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="vault_orphan",
            description="检测孤立笔记——没有被任何其他笔记引用（入度为0）或不引用任何笔记（出度为0）的笔记。",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="vault_update",
            description="更新已有笔记的正文内容，保留原有 frontmatter 并更新 updated 日期。",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_path": {"type": "string", "description": "笔记文件路径"},
                    "new_content": {"type": "string", "description": "替换正文"},
                    "append_content": {"type": "string", "description": "追加到正文末尾"},
                },
                "required": ["note_path"],
            },
        ),
        Tool(
            name="vault_tags",
            description="返回所有已用标签及使用频次，支持标签模糊搜索。",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "标签模糊搜索关键词"}},
            },
        ),
        Tool(
            name="vault_log",
            description="写入会话日志到 Vault。记录做了什么、决策、待办事项。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "项目名"},
                    "summary": {"type": "string", "description": "做了什么"},
                    "decisions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "决策列表",
                    },
                    "todos": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "待办列表",
                    },
                },
                "required": ["project", "summary"],
            },
        ),
        # ── P1 graphify 工具 ──
        Tool(
            name="graphify_build",
            description="对当前项目构建代码图谱，解析 graph.json 生成模块笔记到 Vault。依赖 graphify CLI。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "项目名"},
                    "project_dir": {"type": "string", "description": "项目根目录路径"},
                    "force": {"type": "boolean", "default": True},
                },
                "required": ["project", "project_dir"],
            },
        ),
        Tool(
            name="graphify_status",
            description="返回代码图谱构建状态：上次构建时间、节点数、边数、社区数。",
            inputSchema={
                "type": "object",
                "properties": {"project": {"type": "string"}},
                "required": ["project"],
            },
        ),
        Tool(
            name="graphify_query",
            description="在代码图谱中搜索符号（类/函数/方法），返回所属模块和调用关系。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "symbol": {"type": "string", "description": "符号名，支持模糊匹配"},
                    "fuzzy": {"type": "boolean", "default": True},
                },
                "required": ["project", "symbol"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """分发工具调用到对应的处理函数。"""
    try:
        if name == "vault_init":
            return await _handle_init(arguments)
        elif name == "vault_save":
            return await _handle_save(arguments)
        elif name == "vault_search":
            return await _handle_search(arguments)
        elif name == "vault_resume":
            return await _handle_resume(arguments)
        elif name == "vault_list":
            return await _handle_list(arguments)
        elif name == "vault_stats":
            return await _handle_stats(arguments)
        elif name == "vault_orphan":
            return await _handle_orphan(arguments)
        elif name == "vault_update":
            return await _handle_update(arguments)
        elif name == "vault_tags":
            return await _handle_tags(arguments)
        elif name == "vault_log":
            return await _handle_log(arguments)
        elif name == "vault_todo_list":
            return await _handle_todo_list(arguments)
        elif name == "vault_todo_done":
            return await _handle_todo_done(arguments)
        elif name == "vault_todo_progress":
            return await _handle_todo_progress(arguments)
        elif name == "vault_todo_pending":
            return await _handle_todo_pending(arguments)
        elif name == "vault_todo_delete":
            return await _handle_todo_delete(arguments)
        elif name == "vault_delete":
            return await _handle_delete(arguments)
        elif name == "graphify_build":
            return await _handle_graphify_build(arguments)
        elif name == "graphify_status":
            return await _handle_graphify_status(arguments)
        elif name == "graphify_query":
            return await _handle_graphify_query(arguments)
        else:
            return [
                TextContent(
                    type="text", text=json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
                )
            ]
    except Exception as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]


# ────────────────── 处理器引用（已从工具模块导入）──────────────────

_handle_init = handle_init
_handle_save = handle_save
_handle_search = handle_search
_handle_resume = handle_resume
_handle_list = handle_list
_handle_stats = handle_stats
_handle_orphan = handle_orphan
_handle_update = handle_update
_handle_tags = handle_tags
_handle_log = handle_log
_handle_delete = handle_delete
_handle_todo_list = handle_todo_list
_handle_todo_done = handle_todo_done
_handle_todo_progress = handle_todo_progress
_handle_todo_pending = handle_todo_pending
_handle_todo_delete = handle_todo_delete
_handle_graphify_build = handle_graphify_build
_handle_graphify_status = handle_graphify_status
_handle_graphify_query = handle_graphify_query


# ────────────────── 启动入口 ──────────────────


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
