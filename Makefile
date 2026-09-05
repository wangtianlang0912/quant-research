# quant_research_v2 · 一键入口
#
# 设计原则：单人维护，每周 < 10 小时。
# Makefile 里的每个 target 都必须是"一条命令就能得到结论"的，
# 不能出现"跑完还要人肉看日志才知道对不对"的 target。

.DEFAULT_GOAL := help
.PHONY: help sync lock dev test test-one lint fmt type arch coverage coverage-core check clean schema smoke

# 核心域覆盖率阈值（§8.4 双阈值之一）
CORE_SCOPE := src/quant_v2/domain,src/quant_v2/indicators

help: ## 显示本帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

sync: ## uv sync --frozen（CI 同款，验证 lock 与 pyproject 一致）
	uv sync --frozen

lock: ## 重新生成 uv.lock
	uv lock

dev: sync ## 安装开发环境（含 pre-commit 钩子说明）
	@echo "提示：pre-commit 未纳入默认依赖，需要时执行: uv run pre-commit install"

test: ## 跑全部测试
	uv run pytest

test-one: ## 单测快速跑：make test-one ARGS="-k macd -vv"
	uv run pytest $(ARGS)

lint: ## ruff check
	uv run ruff check src tests tools

fmt: ## ruff format --check（CI 门禁）；自动改写用 make fmt-fix
	uv run ruff format --check src tests tools

fmt-fix: ## ruff format 自动改写
	uv run ruff format src tests tools

fix: ## ruff check --fix（只修能安全自动修的）
	uv run ruff check --fix src tests tools

type: ## mypy --strict（核心域）
	uv run mypy

# ★ 自研 AST 静态扫描（ARCH001~013）。
#   用 AST 而非 grep：grep 的误报率会逼工程师绕过门禁，那门禁就形同虚设。
arch: ## 架构静态扫描 tools/arch_lint
	uv run python -m tools.arch_lint.cli --root .

coverage: ## 覆盖率：整体 ≥60% + 核心域 ≥85%（双阈值）
	uv run coverage erase
	uv run pytest --cov=quant_v2 --cov=tools --cov-report=term-missing --cov-report=xml -q
	@echo "--- 整体阈值 60% ---"
	uv run coverage report --fail-under=60
	@echo "--- 核心域阈值 85%（$(CORE_SCOPE)）---"
	uv run coverage report --fail-under=85 --include="$(CORE_SCOPE)/*"

coverage-core: ## 只看核心域覆盖率
	uv run coverage report --include="$(CORE_SCOPE)/*" --show-missing

schema: ## 重新生成 configs/schemas/*.json（D-01 契约落盘）
	uv run python -m quant_v2.tools.export_schemas

smoke: ## 端到端冒烟
	./scripts/smoke_e2e.sh

clean: ## 清理缓存与产物（不动 var/ 里的数据）
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml
	find . -type d -name __pycache__ -not -path "./.venv/*" -prune -exec rm -rf {} +

check: lint fmt type arch test ## ★ 本地等价于 CI 的全量门禁（推送前跑这个）
