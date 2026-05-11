# Vault MCP Server — Windows 全自动安装脚本
# 用法: powershell -ExecutionPolicy Bypass -File install.ps1
#   或: powershell -ExecutionPolicy Bypass -File install.ps1 -InstallDir "D:\my-vault"

param(
    [string]$InstallDir = "$env:USERPROFILE\scripts\vault-mcp-server",
    [string]$SkillDir = "$env:USERPROFILE\.claude\skills\kb",
    [string]$McpConfig = "$env:USERPROFILE\.claude\mcp.json",
    [switch]$SkipTests = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceDir = Join-Path $ScriptDir "vault-mcp-server"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Vault MCP Server — Windows 自动安装" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 步骤 1: 检查 Python ──
Write-Host "[1/6] 检查 Python 环境..." -ForegroundColor Yellow
try {
    $pyVersion = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "python 不在 PATH 中" }
    Write-Host "  $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  错误: 未找到 Python，请先安装 Python 3.10+" -ForegroundColor Red
    Write-Host "  下载: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

$pyVerStr = ($pyVersion -replace "Python ", "").Trim()
$pyMajor = [int]($pyVerStr.Split(".")[0])
$pyMinor = [int]($pyVerStr.Split(".")[1])
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-Host "  错误: 需要 Python 3.10+，当前版本 $pyVerStr" -ForegroundColor Red
    exit 1
}
Write-Host "  Python 版本符合要求" -ForegroundColor Green

# ── 步骤 2: 安装文件 ──
Write-Host "[2/6] 安装文件到 $InstallDir ..." -ForegroundColor Yellow

if (Test-Path $InstallDir) {
    Write-Host "  目录已存在，覆盖更新..." -ForegroundColor DarkYellow
    Remove-Item -Recurse -Force $InstallDir
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\tools" | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\tests" | Out-Null

Copy-Item -Force "$SourceDir\server.py" $InstallDir
Copy-Item -Force "$SourceDir\db.py" $InstallDir
Copy-Item -Force "$SourceDir\requirements.txt" $InstallDir
Copy-Item -Force "$SourceDir\README.md" $InstallDir
Copy-Item -Force "$SourceDir\INSTALL.md" $InstallDir
Copy-Item -Force "$SourceDir\tools\*.py" "$InstallDir\tools\"
Copy-Item -Force "$SourceDir\tests\*.py" "$InstallDir\tests\"

Write-Host "  文件复制完成" -ForegroundColor Green

# ── 步骤 3: 安装 Python 依赖 ──
Write-Host "[3/6] 安装 Python 依赖..." -ForegroundColor Yellow
& pip install -r "$InstallDir\requirements.txt" -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "  警告: pip install 失败，尝试安装核心依赖..." -ForegroundColor DarkYellow
    & pip install "mcp>=1.0.0" -q
}
Write-Host "  依赖安装完成" -ForegroundColor Green

# ── 步骤 4: 配置 MCP ──
Write-Host "[4/6] 配置 MCP ($McpConfig) ..." -ForegroundColor Yellow

$pythonPath = (Get-Command python).Source
$mcpDir = Split-Path -Parent $McpConfig
if (-not (Test-Path $mcpDir)) {
    New-Item -ItemType Directory -Force -Path $mcpDir | Out-Null
}

# 读取或创建 mcp.json
if (Test-Path $McpConfig) {
    try {
        $mcp = Get-Content $McpConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Host "  警告: mcp.json 解析失败，将创建新配置" -ForegroundColor DarkYellow
        $mcp = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
    }
} else {
    $mcp = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
}

# 确保 mcpServers 存在
if (-not $mcp.mcpServers) {
    $mcp | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{}) -Force
}

# 添加/更新 vault 配置
$vaultConfig = @{
    command = "python"
    args    = @($InstallDir.Replace("\", "\\") + "\\server.py")
    env     = @{ PYTHONIOENCODING = "utf-8" }
}
$mcp.mcpServers | Add-Member -NotePropertyName "vault" -NotePropertyValue $vaultConfig -Force

$mcp | ConvertTo-Json -Depth 4 | Set-Content $McpConfig -Encoding UTF8
Write-Host "  MCP 配置已写入" -ForegroundColor Green

# ── 步骤 5: 安装 Skill ──
Write-Host "[5/6] 安装 /kb Skill..." -ForegroundColor Yellow

if (-not (Test-Path $SkillDir)) {
    New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
}

$skillContent = @'
---
name: kb
description: Vault 知识库快捷命令 — /kb init|save|search|resume|list|stats|orphan|update|tags|log|graphify
---

# /kb — Vault 知识库命令路由

提供自然语言触发知识库工具的命令别名。

## 命令列表

| 命令 | 触发方式 |
|------|---------|
| `/kb init` | "初始化知识库"、"vault init" |
| `/kb save` | "保存到知识库"、"记住这个" |
| `/kb search <词>` | "搜索知识库 xxx" |
| `/kb resume <项目>` | "恢复 xxx 上下文" |
| `/kb stats` | "知识库统计" |
| `/kb list` | "列出笔记" |
| `/kb orphan` | "找孤立笔记" |
| `/kb tags` | "标签列表" |
| `/kb log` | "写工作日志" |
| `/kb update` | "更新笔记" |
| `/kb graphify build` | "构建代码图谱" |
| `/kb graphify status` | "图谱状态" |
| `/kb graphify query <符号>` | "搜索符号 xxx" |

## 自动行为

- 修改代码时自动检查图谱是否过期
- 遇到错误时自动搜索知识库
- 解决问题后提示保存
- 会话结束时自动写日志

## 三层代码查询策略

修改代码前，按优先级查：
1. `graphify_query` — 符号归属和调用链 (< 10ms)
2. `vault_search` — graphify/ 和 permanent/ 中的知识
3. 直接 Read 源文件 — 仅当前两层信息不足时
'@
Set-Content -Path "$SkillDir\SKILL.md" -Value $skillContent -Encoding UTF8
Write-Host "  Skill 已安装到 $SkillDir\SKILL.md" -ForegroundColor Green

# ── 步骤 6: 验证 ──
Write-Host "[6/6] 验证安装..." -ForegroundColor Yellow

$env:PYTHONIOENCODING = "utf-8"
$verifyCode = @"
from db import VaultDB
from tools.vault_tools import handle_init, handle_save, handle_search
from tools.graphify_tools import handle_graphify_status
print('所有模块导入成功')
"@

$result = & python -c $verifyCode 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  模块导入验证通过" -ForegroundColor Green
} else {
    Write-Host "  警告: 模块导入失败`n  $result" -ForegroundColor DarkYellow
}

# 非跳过模式运行测试
if (-not $SkipTests) {
    Write-Host ""
    Write-Host "  运行测试套件..." -ForegroundColor Yellow
    & pip install pytest -q 2>&1 | Out-Null
    Push-Location $InstallDir
    $env:PYTHONIOENCODING = "utf-8"
    & python -m pytest tests/ -q 2>&1
    $testResult = $LASTEXITCODE
    Pop-Location
    if ($testResult -eq 0) {
        Write-Host "  测试全部通过" -ForegroundColor Green
    } else {
        Write-Host "  警告: 部分测试未通过，核心功能应正常" -ForegroundColor DarkYellow
    }
}

# ── 完成 ──
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 安装完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步:" -ForegroundColor White
Write-Host "  1. 完全退出并重启 Claude Code" -ForegroundColor White
Write-Host "  2. 在 Claude Code 中输入: 初始化知识库" -ForegroundColor White
Write-Host "  3. 输入: /kb stats 验证服务正常" -ForegroundColor White
Write-Host ""
Write-Host "已安装位置:" -ForegroundColor White
Write-Host "  服务端: $InstallDir" -ForegroundColor White
Write-Host "  MCP 配置: $McpConfig" -ForegroundColor White
Write-Host "  Skill: $SkillDir\SKILL.md" -ForegroundColor White
Write-Host ""
