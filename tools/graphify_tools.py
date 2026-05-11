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
from tools._shared import json_reply, get_vault_dir, DEFAULT_VAULT_DIR, check_required


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
        return json_reply({
            "status": "error",
            "message": "graphify CLI 未安装。请运行: pip install graphifyy",
        })

    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.exists():
        return json_reply({
            "status": "error",
            "message": f"项目目录不存在: {project_dir}",
        })

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
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(project_path), env=env,
        )

        if result.returncode != 0:
            return json_reply({
                "status": "error",
                "message": "graphify 构建失败",
                "stderr": result.stderr[-1000:],
            })

        # graphify 默认输出到项目内的 graphify-out/，复制到 Vault 目录
        import shutil
        project_graph_json = project_path / "graphify-out" / "graph.json"
        project_index = project_path / "graphify-out" / "GRAPH_REPORT.md"
        if project_graph_json.exists():
            shutil.copy2(str(project_graph_json), str(graph_json))
        if project_index.exists():
            shutil.copy2(str(project_index), str(graphify_vault / "Index.md"))

        stats = {"node_count": 0, "edge_count": 0, "community_count": 0}
        if graph_json.exists():
            graph_data = json.loads(graph_json.read_text(encoding="utf-8"))
            nodes = graph_data.get("nodes", graph_data.get("elements", {}).get("nodes", []))
            edges = graph_data.get("edges", graph_data.get("elements", {}).get("edges", []))
            stats["node_count"] = len(nodes) if isinstance(nodes, list) else 0
            stats["edge_count"] = len(edges) if isinstance(edges, list) else 0
            if isinstance(nodes, list) and nodes and "community" in nodes[0]:
                stats["community_count"] = len(set(n.get("community", 0) for n in nodes))

        db = VaultDB()
        db.record_graphify_build(
            project=project,
            commit_sha=_get_git_sha(project_path),
            node_count=stats["node_count"],
            edge_count=stats["edge_count"],
            community_count=stats["community_count"],
        )

        return json_reply({
            "status": "ok",
            "project": project,
            "node_count": stats["node_count"],
            "edge_count": stats["edge_count"],
            "community_count": stats["community_count"],
            "output_dir": str(graphify_vault),
        })

    except subprocess.TimeoutExpired:
        return json_reply({"status": "error", "message": "graphify 构建超时（120s）"})
    except FileNotFoundError:
        return json_reply({
            "status": "error",
            "message": "graphify CLI 已安装但无法调用（可执行文件缺失），请重新安装: pip install graphifyy",
        })
    except json.JSONDecodeError as e:
        return json_reply({"status": "error", "message": f"graph.json 解析失败: {e}"})


def _get_git_sha(project_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=str(project_dir),
        )
        return result.stdout.strip()[:8] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


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
        return json_reply({
            "status": "ok", "project": project, "built": False,
            "message": f"项目 {project} 尚未构建过代码图谱",
        })

    return json_reply({
        "status": "ok", "project": project, "built": True,
        "latest_build": {
            "commit_sha": latest.get("commit_sha"),
            "node_count": latest.get("node_count"),
            "edge_count": latest.get("edge_count"),
            "community_count": latest.get("community_count"),
            "built_at": latest.get("built_at"),
        },
    })


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
        return json_reply({
            "status": "error",
            "message": f"项目 {project} 尚未构建过代码图谱，请先运行 graphify_build",
        })

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
            results.append({
                "file": str(md_file.relative_to(vault_dir)).replace("\\", "/"),
                "title": md_file.stem,
            })

    return json_reply({
        "status": "ok", "symbol": symbol,
        "count": len(results), "results": results[:20],
    })
