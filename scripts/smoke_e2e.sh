#!/usr/bin/env bash
#
# 端到端冒烟：从零开始验证"这个仓库 clone 下来能跑"。
#
# v1 最惨痛的教训之一：仓库 clone 下来跑不起来（src/data/ 被 .gitignore 吞掉），
# 且没人发现 —— 因为从来没有人做过一次"干净环境全量冒烟"。
#
# 用法：  ./scripts/smoke_e2e.sh
# 退出码：0 = 全部通过；非 0 = 首个失败步骤的退出码

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

step() {
  printf '\n\033[36m==> %s\033[0m\n' "$1"
}

step "0/6 前置检查：uv 可用"
command -v uv >/dev/null 2>&1 || { echo "未找到 uv，请先安装：https://docs.astral.sh/uv/"; exit 1; }
uv --version

step "1/6 依赖安装（uv sync --frozen）"
uv sync --frozen

step "2/6 静态检查：ruff"
uv run ruff check src tests tools
uv run ruff format --check src tests tools

step "3/6 类型检查：mypy --strict（核心域）"
uv run mypy

step "4/6 架构扫描：ARCH001~013"
uv run python -m tools.arch_lint.cli --root .

step "5/6 测试与覆盖率"
uv run pytest --cov=quant_v2 --cov=tools --cov-report=term-missing -q
uv run coverage report --fail-under=60
uv run coverage report --fail-under=85 \
  --include="src/quant_v2/domain/*,src/quant_v2/indicators/*"

step "6/6 入库纪律：git 工作区干净"
untracked="$(git ls-files --others --exclude-standard || true)"
if [ -n "$untracked" ]; then
  echo "::error::存在未纳入版本控制的文件："
  echo "$untracked"
  exit 1
fi
dirty="$(git status --porcelain || true)"
if [ -n "$dirty" ]; then
  echo "::error::工作区不干净："
  echo "$dirty"
  exit 1
fi

printf '\n\033[32m冒烟通过：仓库可复现地跑通全部本地门禁。\033[0m\n'
