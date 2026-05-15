#!/usr/bin/env bash
# Vault MCP Server — Linux/macOS 全自动安装脚本
# 用法: bash install.sh
#   或: bash install.sh --install-dir /opt/vault-mcp --skip-tests
set -euo pipefail

INSTALL_DIR="${HOME}/scripts/vault-mcp-server"
SKILLS_DIR="${HOME}/.claude/skills"
MCP_CONFIG="${HOME}/.claude.json"
SKIP_TESTS=false

# ── 解析参数 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --skill-dir)   SKILLS_DIR="$2"; shift 2 ;;
        --mcp-config)  MCP_CONFIG="$2"; shift 2 ;;
        --skip-tests)  SKIP_TESTS=true; shift ;;
        --help)
            echo "用法: bash install.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --install-dir DIR   安装目录 (默认: ~/scripts/vault-mcp-server)"
            echo "  --skill-dir DIR     Skills 目录 (默认: ~/.claude/skills)"
            echo "  --mcp-config FILE   MCP 配置文件 (默认: ~/.claude.json)"
            echo "  --skip-tests        跳过测试"
            echo "  --help              显示帮助"
            exit 0
            ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/vault-mcp-server"

# ── 颜色输出 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================"
echo -e " Vault MCP Server — Linux/macOS 自动安装"
echo -e "========================================${NC}"
echo ""

# ── 步骤 1: 检查 Python ──
echo -e "${YELLOW}[1/6] 检查 Python 环境...${NC}"

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1)
        major=$(echo "$ver" | grep -oP '\d+' | head -1)
        minor=$(echo "$ver" | grep -oP '\d+' | sed -n '2p')
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}  错误: 未找到 Python 3.10+，请先安装 Python${NC}"
    echo -e "${RED}  Ubuntu/Debian: sudo apt install python3 python3-pip${NC}"
    echo -e "${RED}  macOS:         brew install python3${NC}"
    exit 1
fi
echo -e "${GREEN}  找到 $($PYTHON_CMD --version)${NC}"

# ── 步骤 2: 安装文件 ──
echo -e "${YELLOW}[2/6] 安装文件到 $INSTALL_DIR ...${NC}"

if [ -d "$INSTALL_DIR" ]; then
    echo -e "  目录已存在，覆盖更新..."
    rm -rf "$INSTALL_DIR"
fi
mkdir -p "$INSTALL_DIR/tools"
mkdir -p "$INSTALL_DIR/tests"

cp "$SOURCE_DIR/server.py" "$INSTALL_DIR/"
cp "$SOURCE_DIR/db.py" "$INSTALL_DIR/"
cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$SOURCE_DIR/README.md" "$INSTALL_DIR/"
cp "$SOURCE_DIR/INSTALL.md" "$INSTALL_DIR/"
cp -r "$SOURCE_DIR/skills" "$INSTALL_DIR/"

cp "$SOURCE_DIR/tools/"*.py "$INSTALL_DIR/tools/"
cp "$SOURCE_DIR/tests/"*.py "$INSTALL_DIR/tests/"

echo -e "${GREEN}  文件复制完成${NC}"

# ── 步骤 3: 安装 Python 依赖 ──
echo -e "${YELLOW}[3/6] 安装 Python 依赖...${NC}"
if ! "$PYTHON_CMD" -m pip install -r "$INSTALL_DIR/requirements.txt" -q 2>/dev/null; then
    echo -e "  警告: 完整依赖安装失败，安装核心依赖..."
    "$PYTHON_CMD" -m pip install "mcp>=1.0.0" -q
fi
echo -e "${GREEN}  依赖安装完成${NC}"

# ── 步骤 4: 配置 MCP ──
echo -e "${YELLOW}[4/6] 配置 MCP ($MCP_CONFIG) ...${NC}"

MCP_DIR="$(dirname "$MCP_CONFIG")"
mkdir -p "$MCP_DIR"

# 读取或创建 ~/.claude.json（使用 Python 处理 JSON 避免 jq 依赖）
"$PYTHON_CMD" -c "
import json, os, sys

mcp_path = '$MCP_CONFIG'
vault_config = {
    'command': '$PYTHON_CMD',
    'args': ['$INSTALL_DIR/server.py'],
    'env': {'PYTHONIOENCODING': 'utf-8'}
}

if os.path.exists(mcp_path):
    try:
        with open(mcp_path, 'r') as f:
            mcp = json.load(f)
    except json.JSONDecodeError:
        print('  警告: .claude.json 解析失败，创建新配置')
        mcp = {}
else:
    mcp = {}

if 'mcpServers' not in mcp:
    mcp['mcpServers'] = {}

mcp['mcpServers']['vault'] = vault_config

with open(mcp_path, 'w') as f:
    json.dump(mcp, f, indent=2, ensure_ascii=False)

print('  MCP 配置已写入')
"
echo -e "${GREEN}  MCP 配置完成${NC}"

# ── 步骤 5: 安装 Skills (21 个命令) ──
echo -e "${YELLOW}[5/6] 安装 /kb 命令集 (21 skills)...${NC}"

for skill_dir in "$INSTALL_DIR/skills/"*; do
    skill_name=$(basename "$skill_dir")
    mkdir -p "$SKILLS_DIR/$skill_name"
    cp "$skill_dir/SKILL.md" "$SKILLS_DIR/$skill_name/SKILL.md"
done
echo -e "${GREEN}  21 个 Skills 已安装到 $SKILLS_DIR/${NC}"

# ── 步骤 6: 验证 ──
echo -e "${YELLOW}[6/6] 验证安装...${NC}"

export PYTHONIOENCODING=utf-8
if "$PYTHON_CMD" -c "
from db import VaultDB
from tools.vault_save import handle_save
from tools.vault_search import handle_search
from tools.vault_delete import handle_delete
from tools.vault_todo_list import handle_todo_list
from tools.graphify_tools import handle_graphify_status
print('所有模块导入成功')
" 2>&1; then
    echo -e "${GREEN}  模块导入验证通过${NC}"
else
    echo -e "  警告: 模块导入失败"
fi

# 非跳过模式运行测试
if [ "$SKIP_TESTS" = false ]; then
    echo ""
    echo -e "${YELLOW}  运行测试套件...${NC}"
    "$PYTHON_CMD" -m pip install pytest -q 2>/dev/null || true
    cd "$INSTALL_DIR"
    PYTHONIOENCODING=utf-8 "$PYTHON_CMD" -m pytest tests/ -q 2>&1 || true
    cd "$OLDPWD"
fi

# ── 完成 ──
echo ""
echo -e "${CYAN}========================================"
echo -e " 安装完成！"
echo -e "========================================${NC}"
echo ""
echo -e "下一步:"
echo -e "  1. 完全退出并重启 Claude Code"
echo -e "  2. 在 Claude Code 中输入: 初始化知识库"
echo -e "  3. 输入: /kb stats 验证服务正常"
echo ""
echo -e "已安装位置:"
echo -e "  服务端: ${INSTALL_DIR}"
echo -e "  MCP 配置: ${MCP_CONFIG}"
echo -e "  Skills: ${SKILLS_DIR}/ (21 commands)"
echo ""
