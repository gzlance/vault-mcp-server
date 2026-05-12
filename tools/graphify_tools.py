"""Vault MCP Server — 代码图谱工具实现。

提供 graphify_build/status/query 的处理逻辑。
依赖 graphify CLI（tree-sitter AST 提取工具）和 VaultDB。
"""

import json
import os
import subprocess
from pathlib import Path

from mcp.types import TextContent

from db import VaultDB
from tools._shared import check_required, get_vault_dir, json_reply

# ── 输入校验工具（已移至 tools._shared）──


def _find_graphify_cli() -> str | None:
    """在 PATH 中查找 graphify CLI。"""
    import shutil

    return shutil.which("graphify")


# ── graphify_build ──


async def handle_graphify_build(args: dict) -> list[TextContent]:
    # 输入校验
    ok, err = check_required(args, "project", "project_dir")
    if not ok:
        return err

    project = args["project"]
    project_dir = args["project_dir"]
    force = args.get("force", True)
    vault_dir = get_vault_dir(args)

    graphify_path = _find_graphify_cli()
    if not graphify_path:
        return json_reply(
            {
                "status": "error",
                "message": "graphify CLI 未安装。请运行: pip install graphifyy",
            }
        )

    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.exists():
        return json_reply(
            {
                "status": "error",
                "message": f"项目目录不存在: {project_dir}",
            }
        )

    graphify_vault = vault_dir / "graphify" / project
    graphify_vault.mkdir(parents=True, exist_ok=True)
    graph_json = graphify_vault / "graph.json"

    try:
        # graphify CLI v0.7+ 使用子命令模式: graphify update <path> --force
        cmd = [graphify_path, "update", str(project_path)]
        if force:
            cmd.append("--force")

        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(project_path),
            env=env,
            stdin=subprocess.DEVNULL,
        )

        if result.returncode != 0:
            return json_reply(
                {
                    "status": "error",
                    "message": "graphify 构建失败",
                    "stderr": result.stderr[-1000:],
                }
            )

        # graphify 默认输出到项目内的 graphify-out/，复制到 Vault 目录
        import shutil

        project_graph_json = project_path / "graphify-out" / "graph.json"
        project_index = project_path / "graphify-out" / "GRAPH_REPORT.md"
        if project_graph_json.exists():
            shutil.copy2(str(project_graph_json), str(graph_json))
        if project_index.exists():
            shutil.copy2(str(project_index), str(graphify_vault / "Index.md"))

        # 解析 graph.json 生成统计信息和 Community-*.md 模块笔记
        stats = {"node_count": 0, "edge_count": 0, "community_count": 0}
        community_count = 0
        if graph_json.exists():
            graph_data = json.loads(graph_json.read_text(encoding="utf-8"))
            nodes = graph_data.get("nodes", graph_data.get("elements", {}).get("nodes", []))
            # graphify 输出的边在 "links" 键下，兼容 "edges" 和嵌套格式
            links = graph_data.get(
                "links", graph_data.get("edges", graph_data.get("elements", {}).get("edges", []))
            )
            stats["node_count"] = len(nodes) if isinstance(nodes, list) else 0
            stats["edge_count"] = len(links) if isinstance(links, list) else 0
            if isinstance(nodes, list):
                community_count = _generate_community_notes(
                    nodes=nodes,
                    links=links if isinstance(links, list) else [],
                    output_dir=graphify_vault,
                    project=project,
                )
                stats["community_count"] = community_count

        db = VaultDB()
        db.record_graphify_build(
            project=project,
            commit_sha=_get_git_sha(project_path),
            node_count=stats["node_count"],
            edge_count=stats["edge_count"],
            community_count=stats["community_count"],
        )

        return json_reply(
            {
                "status": "ok",
                "project": project,
                "node_count": stats["node_count"],
                "edge_count": stats["edge_count"],
                "community_count": stats["community_count"],
                "output_dir": str(graphify_vault),
                "notes_generated": community_count,
            }
        )

    except subprocess.TimeoutExpired:
        return json_reply(
            {
                "status": "error",
                "message": "graphify 构建超时（300s）。对于大型项目，建议直接在终端运行: graphify update <project_dir>",
            }
        )
    except FileNotFoundError:
        return json_reply(
            {
                "status": "error",
                "message": "graphify CLI 已安装但无法调用（可执行文件缺失），请重新安装: pip install graphifyy",
            }
        )
    except json.JSONDecodeError as e:
        return json_reply({"status": "error", "message": f"graph.json 解析失败: {e}"})


def _get_git_sha(project_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(project_dir),
            stdin=subprocess.DEVNULL,
        )
        return result.stdout.strip()[:8] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _generate_community_notes(
    nodes: list[dict],
    links: list[dict],
    output_dir: Path,
    project: str,
) -> int:
    """Parse graph.json nodes/links and generate Community-*.md files.

    返回生成的社区数。
    """
    # 按社区分组节点
    communities: dict[int, list[dict]] = {}
    for node in nodes:
        comm = node.get("community")
        if comm is None:
            continue
        communities.setdefault(comm, []).append(node)

    # 构建节点 ID 索引（兼容 "id" 和 "name" 两种字段名）
    node_by_id: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("id") or n.get("name", "")
        if nid:
            node_by_id[nid] = n

    # 按社区分组边
    comm_links: dict[int, list[dict]] = {c: [] for c in communities}
    for link in links:
        src = node_by_id.get(link.get("source", ""))
        if src and src.get("community") is not None:
            comm_links.setdefault(src["community"], []).append(link)

    generated = 0
    for comm_id in sorted(communities.keys()):
        comm_nodes = communities[comm_id]
        # 提取社区标签（用最高频的源文件名作为名称）
        sources: dict[str, int] = {}
        for n in comm_nodes:
            src = n.get("source_file", "")
            if src:
                sources[src] = sources.get(src, 0) + 1
        comm_name = max(sources, key=sources.get) if sources else f"Community {comm_id}"

        # 去重节点（相同 source_file + label 合并）
        seen: set[str] = set()
        unique_nodes: list[dict] = []
        for n in comm_nodes:
            key = f"{n.get('source_file', '')}:{n.get('label', '')}"
            if key not in seen:
                seen.add(key)
                unique_nodes.append(n)

        # 收集社区内的边
        edges = comm_links.get(comm_id, [])
        edge_lines: list[str] = []
        for e in edges[:50]:  # 每个社区最多展示 50 条边
            src_node = node_by_id.get(e.get("source", ""), {})
            tgt_node = node_by_id.get(e.get("target", ""), {})
            rel = e.get("relation", "related")
            src_label = src_node.get("label", e.get("source", "?"))
            tgt_label = tgt_node.get("label", e.get("target", "?"))
            edge_lines.append(f"- `{src_label}` --{rel}--> `{tgt_label}`")

        md = _build_community_md(
            comm_id=comm_id,
            comm_name=comm_name,
            nodes=unique_nodes,
            edge_lines=edge_lines,
            project=project,
        )

        note_path = output_dir / f"Community-{comm_id}.md"
        note_path.write_text(md, encoding="utf-8")
        generated += 1

    return generated


def _build_community_md(
    comm_id: int,
    comm_name: str,
    nodes: list[dict],
    edge_lines: list[str],
    project: str,
) -> str:
    """构建单个社区 Markdown 笔记。"""
    from datetime import datetime

    lines = [
        "---",
        f"title: _COMMUNITY_Community {comm_id}",
        f'tags: ["graphify", "code-graph", "{project}"]',
        "type: code-graph",
        f"project: {project}",
        f"created: {datetime.now().strftime('%Y-%m-%d')}",
        "---",
        "",
        f"# Community {comm_id}: {comm_name}",
        "",
        f"**节点数:** {len(nodes)}",
        "",
    ]

    if nodes:
        lines.append("## 节点")
        lines.append("")
        # 按源文件分组
        files: dict[str, list[dict]] = {}
        for n in nodes:
            src = n.get("source_file", "未知文件")
            files.setdefault(src, []).append(n)
        for src, file_nodes in sorted(files.items()):
            lines.append(f"### {src}")
            for n in file_nodes[:30]:  # 每个文件最多 30 个符号
                label = n.get("label", "?")
                loc = n.get("source_location", "")
                loc_str = f" (L{loc})" if loc else ""
                lines.append(f"- `{label}`{loc_str}")
            if len(file_nodes) > 30:
                lines.append(f"- *... 还有 {len(file_nodes) - 30} 个符号*")
            lines.append("")

    if edge_lines:
        lines.append("## 关系")
        lines.append("")
        lines.extend(edge_lines)
        lines.append("")

    return "\n".join(lines)


# ── graphify_status ──


async def handle_graphify_status(args: dict) -> list[TextContent]:
    # 输入校验
    ok, err = check_required(args, "project")
    if not ok:
        return err

    project = args["project"]
    db = VaultDB()
    latest = db.get_latest_graphify_build(project)

    if not latest:
        return json_reply(
            {
                "status": "ok",
                "project": project,
                "built": False,
                "message": f"项目 {project} 尚未构建过代码图谱",
            }
        )

    return json_reply(
        {
            "status": "ok",
            "project": project,
            "built": True,
            "latest_build": {
                "commit_sha": latest.get("commit_sha"),
                "node_count": latest.get("node_count"),
                "edge_count": latest.get("edge_count"),
                "community_count": latest.get("community_count"),
                "built_at": latest.get("built_at"),
            },
        }
    )


# ── graphify_query ──


async def handle_graphify_query(args: dict) -> list[TextContent]:
    # 输入校验
    ok, err = check_required(args, "project", "symbol")
    if not ok:
        return err

    project = args["project"]
    symbol = args["symbol"]
    fuzzy = args.get("fuzzy", True)
    vault_dir = get_vault_dir(args)

    db = VaultDB()
    latest = db.get_latest_graphify_build(project)
    if not latest:
        return json_reply(
            {
                "status": "error",
                "message": f"项目 {project} 尚未构建过代码图谱，请先运行 graphify_build",
            }
        )

    graphify_dir = vault_dir / "graphify" / project
    if not graphify_dir.exists():
        return json_reply({"status": "ok", "symbol": symbol, "results": []})

    results = []
    for md_file in graphify_dir.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue

        match = (symbol.lower() in text.lower()) if fuzzy else (symbol in text)
        if match:
            results.append(
                {
                    "file": str(md_file.relative_to(vault_dir)).replace("\\", "/"),
                    "title": md_file.stem,
                }
            )

    return json_reply(
        {
            "status": "ok",
            "symbol": symbol,
            "count": len(results),
            "results": results[:20],
        }
    )
