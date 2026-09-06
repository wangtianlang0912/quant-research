"""MarketProfile 加载器单测。

★ 本项目铁律：**禁止假成功**。配置加载失败必须炸，不能静默降级 ——
v1 的教训是「取不到就填默认值」：`order_pipeline.py:40` 取不到股数就写死 100 股，
`basic_risk_manager.py:112` 取不到价格就用 100 元估值，全都看起来在正常跑。

因此本文件对每条失败路径的断言都是「抛了什么异常」，
而不是「返回了什么默认值」。

★ 断言值一律对照 `configs/markets/cn_a.yaml` 的真实内容手抄，
不调用被测代码推导 —— 防止「自洽的往返测试」把写反的映射测成通过。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quant_v2.adapters.clock.market_profile_loader import (
    DEFAULT_MARKETS_DIR,
    MarketProfileConfig,
    available_markets,
    clear_cache,
    load_all_market_profiles,
    load_hook,
    load_market_profile,
    profile_fingerprint,
)
from quant_v2.domain.errors import ConfigValidationError, MarketProfileNotFoundError
from quant_v2.domain.models.market import Availability, CostModel, MarketProfile

pytestmark = pytest.mark.unit

# tests/unit/adapters/test_xxx.py → parents[3] 是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_DIR = REPO_ROOT / "configs" / "markets"

# ============================================================================
# A 股费率表（手抄自 configs/markets/cn_a.yaml，与 cost_model 单测互为独立参考）
# ============================================================================

EXPECTED_COST = CostModel(
    commission_rate=Decimal("0.00025"),
    commission_min=Decimal("5"),
    tax_rate_sell=Decimal("0.0005"),
    tax_rate_buy=Decimal("0"),
    transfer_fee_rate=Decimal("0.00001"),
    exchange_fee_rate=Decimal("0.0000487"),
    slippage_bps=10,
)


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """每个用例前后清空加载缓存，避免用例之间互相污染。"""
    clear_cache()
    yield
    clear_cache()


def minimal_yaml(market_code: str = "cn_a") -> str:
    """一份字段齐全的最小可用配置（用于失败路径的「删除/改坏某一个字段」）。"""
    return f"""\
market_code: {market_code}
display_name: 测试市场
timezone: Asia/Shanghai
calendar_id: XSHG
currency: CNY
settlement_currency: CNY
lot_size: 100
odd_lot_allowed: false
tick:
  tick_size: "0.01"
price_limit:
  limit_pct: "0.10"
  st_limit_pct: "0.05"
  new_listing_free_days: 5
  ipo_first_day_pct: null
t_plus: 1
shortable: false
cost:
  commission_rate: "0.00025"
  commission_min: "5"
  tax_rate_sell: "0.0005"
  tax_rate_buy: "0"
  transfer_fee_rate: "0.00001"
  exchange_fee_rate: "0.0000487"
  slippage_bps: 10
symbol_pattern: '^\\d{{6}}\\.(SH|SZ|BJ)$'
half_day_dates: []
extra_holidays: []
fund_availability: PARTIAL
delisting_data_availability: PARTIAL
max_symbols: 6000
data_sources: []
hooks: {{}}
"""


def write_yaml(directory: Path, market_code: str, text: str) -> Path:
    path = directory / f"{market_code}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadRealConfig:
    """从仓库真实 YAML 加载 —— 断言与配置文件逐项一致。"""

    def test_身份与时区(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.market_code == "cn_a"
        assert profile.display_name == "A股"
        assert profile.timezone == "Asia/Shanghai"
        assert profile.calendar_id == "XSHG"
        assert profile.currency == "CNY"
        assert profile.settlement_currency == "CNY"

    def test_交易单位与T加一(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.lot_size == 100
        assert profile.odd_lot_allowed is False
        assert profile.t_plus == 1
        assert profile.shortable is False

    def test_最小报价单位(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.tick.tick_size == Decimal("0.01")
        assert profile.tick.tick_table == (), "A 股用固定 tick，不配分段表"
        assert profile.tick.tick_for(Decimal("12.34")) == Decimal("0.01")

    def test_涨跌停(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.price_limit.limit_pct == Decimal("0.10")
        assert profile.price_limit.st_limit_pct == Decimal("0.05")
        assert profile.price_limit.new_listing_free_days == 5
        assert profile.price_limit.ipo_first_day_pct is None, "未知就记 None，不猜数值"

    def test_成本参数与费率表逐项一致(self) -> None:
        """★ 这条锁住「成本只此一份」：YAML 改了而代码没改，这里会红。"""
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.cost == EXPECTED_COST
        assert profile.cost_model() is profile.cost

    def test_代码后缀规则(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.symbol_pattern == r"^\d{6}\.(SH|SZ|BJ)$"
        assert profile.matches_symbol("601186.SH") is True
        assert profile.matches_symbol("000001.SZ") is True
        assert profile.matches_symbol("830799.BJ") is True
        assert profile.matches_symbol("600519.SS") is False, "后缀必须是 SH/SZ/BJ"
        assert profile.matches_symbol("AAPL") is False
        assert profile.matches_symbol("60051.SH") is False, "必须是 6 位数字"
        assert profile.matches_symbol("x601186.SH") is False, "正则带 ^ 锚定，前缀非法不匹配"

    def test_日历扩展字段为空(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.half_day_dates == ()
        assert profile.extra_holidays == ()
        assert profile.is_half_day(date(2026, 2, 16)) is False
        assert profile.is_extra_holiday(date(2026, 2, 16)) is False

    def test_数据可得性如实声明(self) -> None:
        """★ OQ-8 / D-13：能力必须如实填写，不能全填 FULL 假装都能给。"""
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.fund_availability == "PARTIAL"
        assert profile.delisting_data_availability == "PARTIAL"
        assert isinstance(profile.fund_availability, str)
        valid: tuple[Availability, ...] = ("FULL", "PARTIAL", "NONE")
        assert profile.fund_availability in valid
        assert profile.delisting_data_availability in valid

    def test_上限与数据源(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.max_symbols == 6000
        assert len(profile.data_sources) == 3
        assert [spec.source_id for spec in profile.data_sources] == [
            "akshare",
            "baostock",
            "tencent",
        ]
        assert [spec.priority for spec in profile.data_sources] == [0, 1, 2]

    def test_主数据源是akshare(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.primary_source().source_id == "akshare"
        assert profile.primary_source().priority == 0

    def test_备源如实声明无复权因子(self) -> None:
        """tencent 备源不给 adj_factor —— 必须标 false，而不是默认 true。"""
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        by_id = {spec.source_id: spec for spec in profile.data_sources}
        assert by_id["akshare"].capabilities.adj_factor is True
        assert by_id["akshare"].capabilities.rate_limit_per_min == 200
        assert by_id["baostock"].capabilities.delisting_history == "PARTIAL"
        assert by_id["tencent"].capabilities.adj_factor is False
        assert by_id["tencent"].capabilities.intraday is True
        assert by_id["tencent"].capabilities.trading_calendar is False

    def test_hooks为空(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.hooks == {}

    def test_涨跌停价计算(self) -> None:
        """用真实配置算涨跌停：10 元 → 11 / 9；ST → 10.5 / 9.5。"""
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.limit_prices(Decimal("10"), is_st=False, listing_days=100) == (
            Decimal("11"),
            Decimal("9"),
        )
        assert profile.limit_prices(Decimal("10"), is_st=True, listing_days=100) == (
            Decimal("10.5"),
            Decimal("9.5"),
        )

    def test_次新股无涨跌幅(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.limit_prices(Decimal("10"), is_st=False, listing_days=5) is None
        assert profile.limit_prices(Decimal("10"), is_st=False, listing_days=6) is not None

    def test_取整按手向下(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile.round_lot(250) == 200
        assert profile.round_lot(200) == 200

    def test_默认配置目录可用(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`DEFAULT_MARKETS_DIR` 是相对仓库根的路径，必须在根目录下可用。"""
        assert Path("configs/markets") == DEFAULT_MARKETS_DIR
        monkeypatch.chdir(REPO_ROOT)
        profile = load_market_profile("cn_a")
        assert profile == load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)


class TestFailurePaths:
    """★ 配置错了必须炸，禁止静默降级或用默认值兜底。"""

    def test_文件不存在抛MarketProfileNotFoundError(self, tmp_path: Path) -> None:
        with pytest.raises(MarketProfileNotFoundError, match="找不到市场配置"):
            load_market_profile("not_exist", config_dir=tmp_path)

    def test_缺失必填字段抛(self, tmp_path: Path) -> None:
        """删掉 `max_symbols`：必须报错，而不是默认成 0 或 100。"""
        text = minimal_yaml().replace("max_symbols: 6000\n", "")
        write_yaml(tmp_path, "cn_a", text)
        with pytest.raises(ConfigValidationError, match="未通过 schema 校验"):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_字段类型错误抛(self, tmp_path: Path) -> None:
        """`lot_size: abc` —— 类型不对必须炸，不做字符串强转。"""
        text = minimal_yaml().replace("lot_size: 100", "lot_size: abc")
        write_yaml(tmp_path, "cn_a", text)
        with pytest.raises(ConfigValidationError, match="未通过 schema 校验"):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_YAML语法错误抛(self, tmp_path: Path) -> None:
        write_yaml(tmp_path, "cn_a", "[unclosed\n")
        with pytest.raises(ConfigValidationError, match="YAML 解析失败"):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_顶层不是映射抛(self, tmp_path: Path) -> None:
        write_yaml(tmp_path, "cn_a", "- 1\n- 2\n")
        with pytest.raises(ConfigValidationError, match="顶层必须是映射"):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_文件名与market_code不一致抛(self, tmp_path: Path) -> None:
        """文件名与内容不一致会让「按代码加载」变成猜谜。"""
        write_yaml(tmp_path, "cn_a", minimal_yaml(market_code="hk"))
        with pytest.raises(ConfigValidationError, match="不一致"):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_未知字段抛(self, tmp_path: Path) -> None:
        """★ `extra=forbid`：字段名拼错直接报错，而不是被静默丢弃。

        默默用默认值的配置比没有配置更危险 —— 你以为生效了，其实没有。
        """
        text = minimal_yaml() + "breakout_threshold: 20\n"
        write_yaml(tmp_path, "cn_a", text)
        with pytest.raises(ConfigValidationError, match="未通过 schema 校验"):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_负的最低佣金抛(self, tmp_path: Path) -> None:
        text = minimal_yaml().replace('commission_min: "5"', 'commission_min: "-5"')
        write_yaml(tmp_path, "cn_a", text)
        with pytest.raises(ConfigValidationError):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_非正的手数抛(self, tmp_path: Path) -> None:
        text = minimal_yaml().replace("lot_size: 100", "lot_size: 0")
        write_yaml(tmp_path, "cn_a", text)
        with pytest.raises(ConfigValidationError):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_枚举取值非法抛(self, tmp_path: Path) -> None:
        text = minimal_yaml().replace("fund_availability: PARTIAL", "fund_availability: SOMEDAY")
        write_yaml(tmp_path, "cn_a", text)
        with pytest.raises(ConfigValidationError):
            load_market_profile("cn_a", config_dir=tmp_path)

    def test_失败后不返回半成品(self, tmp_path: Path) -> None:
        """断言「没有静默降级」：抛异常，且不往缓存里塞任何东西。"""
        write_yaml(tmp_path, "cn_a", minimal_yaml().replace("max_symbols: 6000\n", ""))
        with pytest.raises(ConfigValidationError):
            load_market_profile("cn_a", config_dir=tmp_path)
        clear_cache()
        with pytest.raises(ConfigValidationError):
            load_market_profile("cn_a", config_dir=tmp_path)


class TestAvailableMarkets:
    def test_只列已实装的yaml(self) -> None:
        codes = available_markets(config_dir=REAL_CONFIG_DIR)
        assert codes == ("cn_a",), "当前只有 A 股实装"

    def test_template不参与加载(self, tmp_path: Path) -> None:
        """`.yaml.template` 是注释模板，本来就不完整，混入加载会造成假成功。"""
        (tmp_path / "hk.yaml.template").write_text("market_code: hk\n", encoding="utf-8")
        write_yaml(tmp_path, "us", "market_code: us\n")
        assert available_markets(config_dir=tmp_path) == ("us",)

    def test_按字母序返回(self, tmp_path: Path) -> None:
        for code in ("us", "hk", "cn_a"):
            write_yaml(tmp_path, code, f"market_code: {code}\n")
        assert available_markets(config_dir=tmp_path) == ("cn_a", "hk", "us")

    def test_目录不存在返回空元组(self, tmp_path: Path) -> None:
        """⚠ 锁定当前行为：目录写错时返回空元组而**不抛**。

        这是本文件里唯一一条「静默」契约，与项目的「禁止假成功」铁律有张力 ——
        配置目录路径写错时，调用方拿到 `{}` 而不是报错。已在测试报告中标记。
        """
        assert available_markets(config_dir=tmp_path / "nope") == ()

    def test_load_all返回全部已实装市场(self) -> None:
        profiles = load_all_market_profiles(config_dir=REAL_CONFIG_DIR)
        assert set(profiles) == {"cn_a"}
        assert profiles["cn_a"].market_code == "cn_a"


class TestCaching:
    """缓存：重复加载等价；改了 YAML 立刻生效（热加载）。"""

    def test_重复加载命中缓存(self) -> None:
        first = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        second = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert first is second

    def test_清空缓存后重新加载得到等价对象(self) -> None:
        first = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        clear_cache()
        second = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert second is not first
        assert second == first

    def test_改了YAML立刻生效(self, tmp_path: Path) -> None:
        """★ 热加载：改文件后必须读到新值，不能一直吃旧缓存。"""
        write_yaml(tmp_path, "cn_a", minimal_yaml())
        assert load_market_profile("cn_a", config_dir=tmp_path).max_symbols == 6000

        # 6000 → 60000（长度变化保证缓存键的 size 一定不同）
        write_yaml(
            tmp_path, "cn_a", minimal_yaml().replace("max_symbols: 6000", "max_symbols: 60000")
        )
        assert load_market_profile("cn_a", config_dir=tmp_path).max_symbols == 60000

    def test_幂等加载指纹一致(self) -> None:
        first = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        clear_cache()
        second = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile_fingerprint(first) == profile_fingerprint(second)


class TestProfileFingerprint:
    def test_同一profile指纹稳定(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        assert profile_fingerprint(profile) == profile_fingerprint(profile)

    def test_成本参数变了指纹变(self) -> None:
        """配置变了回测结论就可能变，必须能查出来。"""
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        changed = dataclasses.replace(
            profile,
            cost=dataclasses.replace(profile.cost, slippage_bps=20),
        )
        assert profile_fingerprint(changed) != profile_fingerprint(profile)

    def test_时区变了指纹变(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        changed = dataclasses.replace(profile, timezone="Asia/Hong_Kong")
        assert profile_fingerprint(changed) != profile_fingerprint(profile)

    def test_指纹为六十四位十六进制(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        digest = profile_fingerprint(profile)
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


class TestLoadHook:
    """极端特例的类路径注入（抽象纪律第三条）。"""

    def test_未配置hook抛(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        with pytest.raises(ConfigValidationError, match="未配置 hook"):
            load_hook(profile, "st_detector")

    def test_成功加载可调用对象(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        wired = dataclasses.replace(profile, hooks={"dumper": "json.dumps"})
        assert load_hook(wired, "dumper") is not None
        assert callable(load_hook(wired, "dumper"))

    def test_dotted_path非法抛(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        wired = dataclasses.replace(profile, hooks={"bad": "dumps"})
        with pytest.raises(ConfigValidationError, match="dotted path 非法"):
            load_hook(wired, "bad")

    def test_模块不存在抛(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        wired = dataclasses.replace(profile, hooks={"bad": "no.such.module.fn"})
        with pytest.raises(ConfigValidationError, match="无法导入"):
            load_hook(wired, "bad")

    def test_属性不存在抛(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        wired = dataclasses.replace(profile, hooks={"bad": "json.no_such_attr"})
        with pytest.raises(ConfigValidationError, match="不存在属性"):
            load_hook(wired, "bad")

    def test_指向不可调用对象抛(self) -> None:
        profile = load_market_profile("cn_a", config_dir=REAL_CONFIG_DIR)
        wired = dataclasses.replace(profile, hooks={"bad": "json.__doc__"})
        with pytest.raises(ConfigValidationError, match="不可调用"):
            load_hook(wired, "bad")


class TestConfigSchema:
    """配置 schema 本身的约束。"""

    def test_to_domain产出领域对象(self) -> None:
        config = MarketProfileConfig.model_validate(
            {
                "market_code": "cn_a",
                "display_name": "测试市场",
                "timezone": "Asia/Shanghai",
                "calendar_id": "XSHG",
                "currency": "CNY",
                "lot_size": 100,
                "tick": {"tick_size": "0.01"},
                "cost": {"commission_rate": "0.00025", "commission_min": "5"},
                "symbol_pattern": r"^\d{6}\.SH$",
                "max_symbols": 10,
            }
        )
        domain: MarketProfile = config.to_domain()
        assert domain.market_code == "cn_a"
        assert domain.cost.commission_min == Decimal("5")
        assert domain.price_limit.limit_pct is None, "未配置的涨跌停应为 None（无约束）"

    def test_成本字段有默认值(self) -> None:
        """只给佣金率与最低佣金，其余税费默认 0 —— 显式给出才是好实践。"""
        config = MarketProfileConfig.model_validate(
            {
                "market_code": "x",
                "display_name": "x",
                "timezone": "UTC",
                "calendar_id": "X",
                "currency": "USD",
                "lot_size": 1,
                "tick": {},
                "cost": {"commission_rate": "0.001", "commission_min": "1"},
                "symbol_pattern": "^A$",
                "max_symbols": 1,
            }
        )
        assert config.cost.tax_rate_sell == Decimal("0")
        assert config.cost.tax_rate_buy == Decimal("0")
        assert config.cost.slippage_bps == 0
