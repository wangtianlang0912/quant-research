#!/usr/bin/env python3
"""
港股全主板荐股报告生成器（增强版）

增强点：
1. 优先使用 AKShare 获取港股全主板标的列表（~2200只）
2. AKShare 不可用时降级到东方财富/腾讯接口
3. 指数数据优先用 AKShare 获取
4. 策略引擎复用项目 7 个正式策略类
"""

import json
import os
import sys
import time
import logging
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import uuid
from src.domain.enums import SignalDirection, AdjustType, Frequency
from src.domain.ids import RunId, StrategyId
from src.domain.models.market import Bar
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyContext, StrategyConfig, StrategyMetadata
from src.domain.models.portfolio import Portfolio, Position
from src.strategies.trend_following import TrendFollowingStrategy
from src.strategies.bollinger_bands import BollingerBandsStrategy
from src.strategies.macd_rsi import MacdRsiStrategy
from src.strategies.donchian_channel import DonchianChannelStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.vwap import VwapStrategy
from src.strategies.breakout_strategy import BreakoutStrategy

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ─────────────────────────── 数据结构 ───────────────────────────

def make_session():
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount('http://', adapter)
    s.mount('https://', adapter)
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://quote.eastmoney.com/',
    })
    return s


def safe_float(v):
    try:
        if v == '-' or v is None or v == '':
            return 0.0
        return float(v)
    except (ValueError, TypeError):
        return 0.0


@dataclass
class HKQuote:
    code: str        # 如 hk00700
    raw_code: str    # 如 00700
    name: str
    price: float
    change_pct: float
    volume: float
    amount: float    # 成交额（港元）
    turnover_rate: float
    pe: float
    market_cap: float
    industry: str = ""


@dataclass
class KlineBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


# K线本地缓存
KLINE_CACHE_DIR = os.path.join(PROJECT_ROOT, 'data', 'cache', 'klines')


def _kline_cache_path(code: str) -> str:
    os.makedirs(KLINE_CACHE_DIR, exist_ok=True)
    return os.path.join(KLINE_CACHE_DIR, f'{code}.json')


def _load_cached_kline(code: str) -> Optional[List[KlineBar]]:
    try:
        cache_path = _kline_cache_path(code)
        if not os.path.exists(cache_path):
            return None
        with open(cache_path, 'r') as f:
            data = json.load(f)
        if data.get('cached_date') != date.today().isoformat():
            return None
        return [KlineBar(**b) for b in data.get('bars', [])]
    except Exception:
        return None


def _save_cached_kline(code: str, bars: List[KlineBar]):
    try:
        cache_path = _kline_cache_path(code)
        with open(cache_path, 'w') as f:
            json.dump({
                'cached_date': date.today().isoformat(),
                'bars': [asdict(b) for b in bars],
            }, f, ensure_ascii=False)
    except Exception:
        pass


# ─────────────────────── AKShare 数据获取 ───────────────────────

def fetch_hk_spot_akshare() -> Optional[List[HKQuote]]:
    """使用 AKShare 获取港股全主板行情列表"""
    try:
        import akshare as ak
    except ImportError:
        logger.warning("AKShare 未安装")
        return None

    quotes = []
    seen = set()

    # 方法1: stock_hk_spot_em - 东方财富港股实时行情
    for attempt in range(3):
        try:
            logger.info("AKShare: 尝试 stock_hk_spot_em 获取港股全主板行情...")
            df = ak.stock_hk_spot_em()
            if df is None or df.empty:
                logger.warning("AKShare stock_hk_spot_em 返回空数据")
                continue

            logger.info(f"AKShare 获取到 {len(df)} 条原始数据")
            # 列名: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率-动态, 市净率, 总市值, 流通市值
            for _, row in df.iterrows():
                try:
                    raw_code = str(row.get('代码', '')).zfill(5)
                    name = str(row.get('名称', ''))
                    price = safe_float(row.get('最新价'))
                    change_pct = safe_float(row.get('涨跌幅'))
                    volume = safe_float(row.get('成交量'))
                    amount = safe_float(row.get('成交额'))
                    turnover = safe_float(row.get('换手率'))
                    pe = safe_float(row.get('市盈率-动态'))
                    mc = safe_float(row.get('总市值'))

                    # 过滤衍生品
                    if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
                        continue
                    if price <= 0:
                        continue
                    # 最低成交额门槛：500万港元
                    if amount < 5e6:
                        continue
                    # 最低市值门槛：5000万港元
                    if mc > 0 and mc < 5e7:
                        continue

                    code = f'hk{raw_code}'
                    if code in seen:
                        continue
                    seen.add(code)

                    quotes.append(HKQuote(
                        code=code,
                        raw_code=raw_code,
                        name=name,
                        price=price,
                        change_pct=change_pct,
                        volume=volume,
                        amount=amount,
                        turnover_rate=turnover,
                        pe=pe,
                        market_cap=mc,
                        industry='',
                    ))
                except Exception:
                    continue

            if quotes:
                quotes.sort(key=lambda x: x.amount, reverse=True)
                logger.info(f"AKShare 有效港股标的: {len(quotes)} 只")
                return quotes
        except Exception as e:
            logger.warning(f"AKShare stock_hk_spot_em 尝试 {attempt+1}/3 失败: {e}")
            time.sleep(2)

    # 方法2: stock_hk_spot - 新浪港股
    try:
        logger.info("AKShare: 尝试 stock_hk_spot (新浪) 获取港股行情...")
        df = ak.stock_hk_spot()
        if df is not None and not df.empty:
            logger.info(f"AKShare (新浪) 获取到 {len(df)} 条数据")
            for _, row in df.iterrows():
                try:
                    raw_code = str(row.get('代码', '')).zfill(5)
                    name = str(row.get('中文名称', ''))
                    price = safe_float(row.get('最新价'))
                    change_pct = safe_float(row.get('涨跌幅'))
                    volume = safe_float(row.get('成交量'))
                    amount = safe_float(row.get('成交额'))

                    if not raw_code or not name:
                        continue
                    if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
                        continue
                    if price <= 0:
                        continue
                    # 新浪成交额单位为港元，放宽到100万
                    if amount < 1e6:
                        continue

                    code = f'hk{raw_code}'
                    if code in seen:
                        continue
                    seen.add(code)

                    quotes.append(HKQuote(
                        code=code,
                        raw_code=raw_code,
                        name=name,
                        price=price,
                        change_pct=change_pct,
                        volume=volume,
                        amount=amount,
                        turnover_rate=0,
                        pe=0,
                        market_cap=0,
                        industry='',
                    ))
                except Exception:
                    continue

            if quotes:
                quotes.sort(key=lambda x: x.amount, reverse=True)
                logger.info(f"AKShare (新浪) 有效港股标的: {len(quotes)} 只")
                return quotes
    except Exception as e:
        logger.warning(f"AKShare stock_hk_spot (新浪) 失败: {e}")

    return quotes if quotes else None


def fetch_hk_kline_akshare(raw_code: str, days: int = 60) -> Optional[List[KlineBar]]:
    """使用 AKShare 获取港股日K线"""
    try:
        import akshare as ak
    except ImportError:
        return None

    # 方法1: stock_hk_hist - 东方财富港股历史行情
    for attempt in range(2):
        try:
            end_date = date.today().strftime('%Y%m%d')
            start_date = (date.today() - timedelta(days=days * 3)).strftime('%Y%m%d')
            df = ak.stock_hk_hist(symbol=raw_code, period='daily',
                                  start_date=start_date, end_date=end_date, adjust='qfq')
            if df is None or df.empty:
                continue

            bars = []
            for _, row in df.iterrows():
                try:
                    d = str(row.get('日期', ''))
                    bars.append(KlineBar(
                        date=d,
                        open=safe_float(row.get('开盘')),
                        high=safe_float(row.get('最高')),
                        low=safe_float(row.get('最低')),
                        close=safe_float(row.get('收盘')),
                        volume=safe_float(row.get('成交量')),
                    ))
                except Exception:
                    continue

            if bars and len(bars) >= 15:
                return bars[-days:]
        except Exception:
            time.sleep(0.5)

    # 方法2: stock_hk_daily - 新浪港股日K
    try:
        df = ak.stock_hk_daily(symbol=f'hk{raw_code}', adjust='qfq')
        if df is not None and not df.empty:
            bars = []
            for _, row in df.tail(days).iterrows():
                try:
                    d = str(row.get('date', row.index[0] if hasattr(row, 'index') else ''))
                    bars.append(KlineBar(
                        date=d,
                        open=safe_float(row.get('open')),
                        high=safe_float(row.get('high')),
                        low=safe_float(row.get('low')),
                        close=safe_float(row.get('close')),
                        volume=safe_float(row.get('volume')),
                    ))
                except Exception:
                    continue
            if bars and len(bars) >= 15:
                return bars[-days:]
    except Exception:
        pass

    return None


def fetch_index_kline_akshare(symbol: str, days: int = 60) -> Optional[List[KlineBar]]:
    """使用 AKShare 获取指数K线"""
    try:
        import akshare as ak
    except ImportError:
        return None

    # 方法1: stock_hk_index_daily_sina
    for attempt in range(2):
        try:
            df = ak.stock_hk_index_daily_sina(symbol=symbol)
            if df is None or df.empty:
                continue
            bars = []
            for _, row in df.tail(days).iterrows():
                try:
                    d = str(row.get('date', ''))
                    bars.append(KlineBar(
                        date=d,
                        open=safe_float(row.get('open')),
                        high=safe_float(row.get('high')),
                        low=safe_float(row.get('low')),
                        close=safe_float(row.get('close')),
                        volume=safe_float(row.get('volume')),
                    ))
                except Exception:
                    continue
            if bars and len(bars) >= 10:
                return bars[-days:]
        except Exception:
            time.sleep(0.5)

    # 方法2: stock_hk_index_spot_em
    try:
        df = ak.stock_hk_index_daily_em(symbol=symbol)
        if df is not None and not df.empty:
            bars = []
            for _, row in df.tail(days).iterrows():
                try:
                    d = str(row.get('date', ''))
                    bars.append(KlineBar(
                        date=d,
                        open=safe_float(row.get('open')),
                        high=safe_float(row.get('high')),
                        low=safe_float(row.get('low')),
                        close=safe_float(row.get('close')),
                        volume=safe_float(row.get('volume')),
                    ))
                except Exception:
                    continue
            if bars and len(bars) >= 10:
                return bars[-days:]
    except Exception:
        pass

    return None


# ─────────────────────── 东方财富/腾讯 降级方案 ───────────────────────

def fetch_hk_spot_tencent(session):
    """通过腾讯财经接口批量获取港股行情数据"""
    logger.info("降级方案: 腾讯接口获取港股行情...")

    core_codes = [
        '00700', '09988', '01810', '00941', '03690', '02318', '02628',
        '00398', '02328', '00688', '00883', '00005', '00011', '01299',
        '02269', '01093', '00669', '00960', '02313', '00001', '00002',
        '00003', '00006', '00012', '00016', '00017', '00027', '00066',
        '00175', '00241', '00267', '00288', '00291', '00386', '00493',
        '00522', '00656', '00728', '00762', '00823', '00836', '00857',
        '00868', '00914', '00939', '00968', '00981', '01024', '01070',
        '01109', '01177', '01200', '01357', '01378', '01448', '01576',
        '01658', '01725', '01766', '01896', '01919', '02015', '02018',
        '02039', '02196', '02202', '02238', '02382', '02498', '02518',
        '02601', '02607', '02688', '02799', '02823', '02899', '03888',
        '03988', '06030', '06606', '06618', '06690', '06862', '06969',
        '09618', '09633', '09668', '09888', '09999',
        '02013', '02878', '03032', '06060', '07772',
        '02020', '02202', '02162', '01113', '01833',
        '09868', '01211', '02238', '01715', '09896',
        '02388', '01651', '01361', '06098', '03908',
        '01109', '00678', '01207', '00817', '01918',
        '00857', '00883', '00368', '00386',
    ]

    all_codes = list(set(core_codes))
    logger.info(f"核心港股标的: {len(all_codes)} 只")

    all_quotes = []
    batch_size = 80

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        tencent_codes = [f'r_hk{c}' for c in batch]
        url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"

        try:
            r = session.get(url, timeout=10)
            text = r.content.decode('gbk', errors='replace')

            for line in text.strip().split(';'):
                if not line or '="=" ' in line or '~' not in line:
                    continue
                try:
                    data_part = line.split('="', 1)[1].rstrip('"')
                    parts = data_part.split('~')
                    if len(parts) < 35:
                        continue

                    code = parts[2] if len(parts) > 2 else ''
                    name = parts[1] if len(parts) > 1 else ''
                    price = safe_float(parts[3])
                    change_pct = safe_float(parts[32])
                    volume = safe_float(parts[6])
                    amount = safe_float(parts[37]) * 10000
                    turnover = safe_float(parts[38]) if len(parts) > 38 else 0

                    if price <= 0 or name == '' or code == '':
                        continue
                    if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
                        continue

                    raw_code = code.replace('hk', '').replace('r_hk', '')

                    all_quotes.append(HKQuote(
                        code=f'hk{raw_code}',
                        raw_code=raw_code,
                        name=name,
                        price=price,
                        change_pct=change_pct,
                        volume=volume,
                        amount=amount,
                        turnover_rate=turnover,
                        pe=0,
                        market_cap=0,
                        industry='',
                    ))
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"腾讯行情获取失败批次{i}: {e}")

        time.sleep(0.2)

    all_quotes.sort(key=lambda x: x.amount, reverse=True)
    logger.info(f"腾讯接口港股行情: {len(all_quotes)} 只")
    return all_quotes


def fetch_hk_spot_list(session):
    """获取港股主板行情列表 - AKShare优先 → 东方财富 → 腾讯"""
    logger.info("开始获取港股主板行情列表...")

    # 1. 尝试 AKShare
    ak_quotes = fetch_hk_spot_akshare()
    if ak_quotes and len(ak_quotes) >= 50:
        logger.info(f"AKShare 获取成功: {len(ak_quotes)} 只")
        return ak_quotes, 'akshare'

    # 2. 尝试东方财富
    logger.warning("AKShare 不可用或数据不足，尝试东方财富...")
    fs_filters = ['m:128+t:3', 'm:128+t:4']
    fields = 'f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f20,f100'
    all_items = []
    success = False
    for fs in fs_filters:
        for page in range(1, 6):
            url = (
                f'https://push2.eastmoney.com/api/qt/clist/get'
                f'?pn={page}&pz=500&po=1&np=1&fltt=2&invt=2'
                f'&fid=f6&fs={fs}&fields={fields}'
            )
            try:
                r = session.get(url, timeout=10)
                if r.status_code != 200:
                    continue
                data = r.json()
                if data is None or data.get('data') is None:
                    break
                items = data['data'].get('diff') or []
                if not items:
                    break
                all_items.extend(items)
                success = True
            except Exception:
                time.sleep(1)

    if success and all_items:
        quotes = []
        seen = set()
        for item in all_items:
            raw_code = str(item.get('f12', ''))
            name = item.get('f14', '')
            price = safe_float(item.get('f2'))
            change_pct = safe_float(item.get('f3'))
            volume = safe_float(item.get('f5'))
            amount = safe_float(item.get('f6'))
            turnover = safe_float(item.get('f8'))
            pe = safe_float(item.get('f9'))
            mc = safe_float(item.get('f20'))
            industry = item.get('f100', '') or ''

            if any(kw in name for kw in ['购', '沽', '牛', '熊', '轮']):
                continue
            if price <= 0:
                continue
            if mc > 0 and mc < 1e8:
                continue
            if amount < 5e7:
                continue

            code = f'hk{raw_code}'
            if code in seen:
                continue
            seen.add(code)

            quotes.append(HKQuote(
                code=code, raw_code=raw_code, name=name, price=price,
                change_pct=change_pct, volume=volume, amount=amount,
                turnover_rate=turnover, pe=pe, market_cap=mc, industry=industry,
            ))

        quotes.sort(key=lambda x: x.amount, reverse=True)
        if len(quotes) >= 50:
            logger.info(f"东方财富获取成功: {len(quotes)} 只")
            return quotes, 'eastmoney'

    # 3. 腾讯降级
    logger.warning("东方财富接口不可用，切换到腾讯接口...")
    tencent_quotes = fetch_hk_spot_tencent(session)
    return tencent_quotes, 'tencent'


def _fetch_kline_eastmoney_fast(raw_code: str, days: int) -> Optional[List[KlineBar]]:
    secid = f"128.{raw_code}"
    end_date = date.today().strftime('%Y%m%d')
    start_date = (date.today() - timedelta(days=days * 2)).strftime('%Y%m%d')
    url = (
        f'https://push2his.eastmoney.com/api/qt/stock/kline/get'
        f'?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
        f'&klt=101&fqt=1&beg={start_date}&end={end_date}&lmt={days}'
    )
    try:
        r = requests.get(url, timeout=8, headers={
            'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/',
        })
        if r.status_code != 200:
            return None
        data = r.json()
        if data is None or data.get('data') is None:
            return None
        klines = data['data'].get('klines') or []
        if not klines:
            return None
        bars = []
        for line in klines:
            parts = line.split(',')
            if len(parts) >= 7:
                bars.append(KlineBar(
                    date=parts[0], open=safe_float(parts[1]), high=safe_float(parts[2]),
                    low=safe_float(parts[3]), close=safe_float(parts[4]), volume=safe_float(parts[5]),
                ))
        return bars[-days:] if bars else None
    except Exception:
        return None


def _fetch_kline_tencent(session, raw_code: str, days: int) -> Optional[List[KlineBar]]:
    try:
        url = 'http://ifzq.gtimg.cn/appstock/app/fqkline/get'
        params = {'param': f'hk{raw_code},day,,,{days + 5},qfq'}
        r = session.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get('code') != 0:
            return None
        days_data = data.get('data', {}).get(f'hk{raw_code}', {}).get('day', [])
        if not days_data:
            return None
        bars = []
        for d in days_data[-days:]:
            if len(d) >= 6:
                bars.append(KlineBar(
                    date=str(d[0]), open=safe_float(d[1]), close=safe_float(d[2]),
                    high=safe_float(d[3]), low=safe_float(d[4]), volume=safe_float(d[5]),
                ))
        return bars if bars else None
    except Exception:
        return None


def fetch_hk_kline(session, code, days=60):
    """获取单只港股日K线 — 缓存优先 → AKShare → 东方财富 → 腾讯"""
    raw_code = code.replace('hk', '')

    # 1. 检查本地缓存
    cached = _load_cached_kline(code)
    if cached is not None and len(cached) >= min(days, 20):
        return cached[-days:]

    # 2. AKShare
    bars = fetch_hk_kline_akshare(raw_code, days)
    if bars and len(bars) >= min(days, 15):
        _save_cached_kline(code, bars)
        return bars

    # 3. 东方财富
    bars = _fetch_kline_eastmoney_fast(raw_code, days)
    if bars and len(bars) >= min(days, 20):
        _save_cached_kline(code, bars)
        return bars

    # 4. 腾讯
    bars = _fetch_kline_tencent(session, raw_code, days)
    if bars and len(bars) >= min(days, 15):
        _save_cached_kline(code, bars)
        return bars

    return []


def fetch_index_kline(session, index_code, days=60):
    """获取指数K线 - AKShare优先 → 东方财富"""
    # 1. AKShare
    ak_symbol = 'HSI' if 'HSI' in index_code else 'HSTECH'
    bars = fetch_index_kline_akshare(ak_symbol, days)
    if bars and len(bars) >= 10:
        return bars

    # 2. 东方财富
    url = (
        f'https://push2his.eastmoney.com/api/qt/stock/kline/get'
        f'?secid={index_code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
        f'&klt=101&fqt=1&beg={(date.today()-timedelta(days=days*2)).strftime("%Y%m%d")}&end={date.today().strftime("%Y%m%d")}&lmt={days}'
    )
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        if data is None or data.get('data') is None:
            return []
        klines = data['data'].get('klines') or []
        bars = []
        for line in klines:
            parts = line.split(',')
            if len(parts) >= 7:
                bars.append(KlineBar(
                    date=parts[0], open=safe_float(parts[1]), high=safe_float(parts[2]),
                    low=safe_float(parts[3]), close=safe_float(parts[4]), volume=safe_float(parts[5]),
                ))
        return bars[-days:]
    except Exception as e:
        logger.warning(f"指数K线获取失败 {index_code}: {e}")
        return []


# ─────────────────────── 策略引擎 ───────────────────────

STRATEGY_CLASSES = {
    'trend_following':  TrendFollowingStrategy,
    'bollinger_bands':  BollingerBandsStrategy,
    'macd_rsi':         MacdRsiStrategy,
    'donchian_channel': DonchianChannelStrategy,
    'mean_reversion':   MeanReversionStrategy,
    'vwap':             VwapStrategy,
    'breakout':         BreakoutStrategy,
}

STRATEGY_WEIGHTS = {
    'trend_following':  0.20, 'bollinger_bands': 0.15, 'macd_rsi': 0.20,
    'donchian_channel': 0.15, 'mean_reversion': 0.10, 'vwap': 0.10, 'breakout': 0.10,
}

STRATEGY_MIN_BARS = {
    'trend_following': 20, 'bollinger_bands': 20, 'macd_rsi': 26,
    'donchian_channel': 20, 'mean_reversion': 20, 'vwap': 10, 'breakout': 60,
}

STRATEGY_MAX_BARS = 60


def kline_to_bar(k: KlineBar) -> Bar:
    return Bar(
        symbol='', timestamp=datetime.strptime(k.date, '%Y-%m-%d') if '-' in k.date
        else datetime.strptime(k.date, '%Y%m%d'),
        open=Decimal(str(k.open)), high=Decimal(str(k.high)), low=Decimal(str(k.low)),
        close=Decimal(str(k.close)), volume=Decimal(str(k.volume)),
        frequency=Frequency.DAY_1, adjust_type=AdjustType.NONE,
    )


def kline_to_candle(k: KlineBar) -> dict:
    return {'date': k.date, 'open': k.open, 'high': k.high, 'low': k.low, 'close': k.close, 'volume': k.volume}


def make_context(bars: List[Bar], strategy_meta: StrategyMetadata) -> StrategyContext:
    return StrategyContext(
        run_id=RunId('hk_scan'), as_of=datetime.now(), bars=bars,
        portfolio=Portfolio(cash=Decimal('0'), total_value=Decimal('0')),
        config=StrategyConfig(params={}), metadata=strategy_meta,
    )


def run_strategy_scan(strategy_name, strategy_cls, bars: List[Bar], kline_bars: List[KlineBar]) -> List[Signal]:
    min_bars = STRATEGY_MIN_BARS.get(strategy_name, 20)
    if len(bars) < min_bars:
        return []

    if strategy_name == 'macd_rsi':
        strategy = strategy_cls()
        context1 = make_context(bars[:-1], strategy.metadata())
        strategy.on_bar(context1)
        context2 = make_context(bars, strategy.metadata())
        return strategy.on_bar(context2)

    if strategy_name == 'vwap':
        strategy = strategy_cls(window=10, max_dev=15.0)
        context = make_context(bars, strategy.metadata())
        return strategy.on_bar(context)

    if strategy_name == 'breakout':
        if len(kline_bars) < 60:
            return []
        strategy = strategy_cls(score_min=18)
        candles = [kline_to_candle(k) for k in kline_bars]
        sig = strategy.scan_symbol(candles, '', datetime.now())
        return [sig] if sig else []

    strategy = strategy_cls()
    context = make_context(bars, strategy.metadata())
    return strategy.on_bar(context)


def signal_to_score(sig: Signal, strategy_name: str) -> float:
    weight = STRATEGY_WEIGHTS.get(strategy_name, 0.10)
    if sig.direction == SignalDirection.LONG:
        return weight * 50 * float(sig.strength)
    elif sig.direction == SignalDirection.SHORT:
        return -weight * 50 * float(sig.strength)
    return 0.0


# ─────────────────────── 扫描引擎 ───────────────────────

@dataclass
class StrategySignal:
    strategy: str
    direction: str
    strength: float
    reason: str


@dataclass
class StockScanResult:
    code: str
    name: str
    price: float
    change_pct: float
    amount: float
    turnover_rate: float
    pe: float
    market_cap: float
    industry: str
    total_score: float
    buy_signals: List[StrategySignal] = field(default_factory=list)
    sell_signals: List[StrategySignal] = field(default_factory=list)
    rsi: float = 50.0
    macd_signal: str = ""
    zscore: float = 0.0
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    bollinger_upper: float = 0.0
    bollinger_lower: float = 0.0
    donchian_upper: float = 0.0
    donchian_lower: float = 0.0
    strategy_signals: dict = field(default_factory=dict)


def scan_stock(quote: HKQuote, bars: List[KlineBar]) -> StockScanResult:
    result = StockScanResult(
        code=quote.code, name=quote.name, price=quote.price,
        change_pct=quote.change_pct, amount=quote.amount,
        turnover_rate=quote.turnover_rate, pe=quote.pe,
        market_cap=quote.market_cap, industry=quote.industry, total_score=0.0,
    )

    if len(bars) < 20:
        if quote.change_pct >= 3:
            result.total_score = 10
            result.buy_signals.append(StrategySignal("简化", "buy", 0.3, f"涨幅{quote.change_pct:+.1f}%"))
        return result

    strategy_bars = [kline_to_bar(k) for k in bars]

    for sname, scls in STRATEGY_CLASSES.items():
        try:
            signals = run_strategy_scan(sname, scls, strategy_bars, bars)
            for sig in signals:
                sc = signal_to_score(sig, sname)
                result.total_score += sc
                if sig.direction == SignalDirection.LONG:
                    result.buy_signals.append(StrategySignal(sname, 'buy', float(sig.strength), sig.reason))
                elif sig.direction == SignalDirection.SHORT:
                    result.sell_signals.append(StrategySignal(sname, 'sell', float(sig.strength), sig.reason))
                result.strategy_signals[sname] = {
                    'direction': sig.direction.value, 'strength': float(sig.strength),
                    'reason': sig.reason, 'score': sc,
                }
        except Exception as e:
            logger.debug(f"策略 {sname} 异常 {quote.code}: {e}")

    closes = [b.close for b in bars]
    if len(closes) >= 14:
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else sum(gains) / len(gains) if gains else 1
        avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else sum(losses) / len(losses) if losses else 1
        if avg_loss > 0:
            result.rsi = 100 - (100 / (1 + avg_gain / avg_loss))
        else:
            result.rsi = 100.0

    result.ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
    result.ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0
    result.ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0

    if len(closes) >= 20:
        sma = result.ma20
        variance = sum((c - sma) ** 2 for c in closes[-20:]) / 20
        std = variance ** 0.5
        result.bollinger_upper = sma + 2 * std
        result.bollinger_lower = sma - 2 * std
        mean = sum(closes[-20:]) / 20
        std2 = (sum((c - mean) ** 2 for c in closes[-20:]) / 20) ** 0.5
        result.zscore = (closes[-1] - mean) / std2 if std2 > 0 else 0

    if len(bars) >= 20:
        result.donchian_upper = max(b.high for b in bars[-20:])
        result.donchian_lower = min(b.low for b in bars[-20:])

    buy_reasons = [s.reason for s in result.buy_signals if s.strategy == 'macd_rsi']
    sell_reasons = [s.reason for s in result.sell_signals if s.strategy == 'macd_rsi']
    if buy_reasons:
        result.macd_signal = '金叉'
    elif sell_reasons:
        result.macd_signal = '死叉'

    amount_yi = quote.amount / 1e8
    if amount_yi >= 10:
        result.total_score += 5
    elif amount_yi >= 5:
        result.total_score += 3
    if 10 <= quote.pe <= 30:
        result.total_score += 5
    elif quote.pe > 0 and quote.pe <= 50:
        result.total_score += 2

    return result


def _fetch_and_scan(q: HKQuote, session) -> StockScanResult:
    bars = fetch_hk_kline(session, q.code, days=STRATEGY_MAX_BARS)
    return scan_stock(q, bars)


def scan_market(quotes: List[HKQuote], session, top_klines=300):
    """批量扫描市场 — 并发取K线 + 正式策略扫描"""
    scan_list = quotes[:top_klines]
    logger.info(f"正式策略扫描（7策略 + 并发+缓存），K线标的 {len(scan_list)} 只...")

    results = []
    kline_ok = 0

    max_workers = min(12, len(scan_list))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_and_scan, q, session): q for q in scan_list}
        for i, future in enumerate(as_completed(future_map)):
            try:
                result = future.result()
                if result.strategy_signals:
                    kline_ok += 1
                results.append(result)
            except Exception as e:
                q = future_map[future]
                logger.debug(f"扫描异常 {q.code}: {e}")
                results.append(scan_stock(q, []))

            if (i + 1) % 50 == 0:
                logger.info(f"并发扫描进度 {i+1}/{len(scan_list)}，K线成功 {kline_ok}/{i+1}")

    # 剩余标的做简化版
    remaining = quotes[top_klines:]
    for q in remaining:
        results.append(scan_stock(q, []))

    results.sort(key=lambda r: r.total_score, reverse=True)
    logger.info(f"扫描完成 共 {len(results)} 只，K线成功率: {kline_ok}/{len(scan_list)}")
    return results


# ─────────────────────── 辅助函数 ───────────────────────

def calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def calc_macd(closes: List[float], fast=12, slow=26, signal=9) -> Tuple[float, float, float]:
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    def ema(data, period):
        k = 2 / (period + 1)
        val = data[0]
        for p in data[1:]:
            val = p * k + val * (1 - k)
        return val
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = ema_fast - ema_slow
    difs = []
    for i in range(slow, len(closes)):
        ef = ema(closes[:i+1], fast)
        es = ema(closes[:i+1], slow)
        difs.append(ef - es)
    dea = ema(difs, signal) if len(difs) >= signal else dif
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def calc_ma(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


# ─────────────────────── 市场情绪分析 ───────────────────────

def analyze_market_sentiment(session) -> Dict:
    hsi_bars = fetch_index_kline(session, "100.HSI", 60)
    hstech_bars = fetch_index_kline(session, "100.HSTECH", 60)

    sentiment = {
        'hsi_change': 0, 'hsi_rsi': 50, 'hsi_macd': '', 'hsi_trend': '中性',
        'hsi_price': 0, 'hsi_ma5': 0, 'hsi_ma20': 0,
        'hstech_change': 0, 'hstech_rsi': 50, 'hstech_macd': '', 'hstech_trend': '中性',
        'hstech_price': 0, 'hstech_ma5': 0, 'hstech_ma20': 0,
        'overall': '中性',
    }

    if hsi_bars and len(hsi_bars) >= 2:
        hsi_closes = [b.close for b in hsi_bars]
        sentiment['hsi_change'] = (hsi_closes[-1] - hsi_closes[-2]) / hsi_closes[-2] * 100 if hsi_closes[-2] > 0 else 0
        sentiment['hsi_price'] = hsi_closes[-1]
        if len(hsi_closes) >= 26:
            sentiment['hsi_rsi'] = calc_rsi(hsi_closes, 14)
            dif, dea, macd_bar = calc_macd(hsi_closes)
            sentiment['hsi_macd'] = '金叉' if macd_bar > 0 and dif > dea else '死叉' if macd_bar < 0 else '中性'
            sentiment['hsi_ma5'] = calc_ma(hsi_closes, 5)
            sentiment['hsi_ma20'] = calc_ma(hsi_closes, 20)
            if hsi_closes[-1] > sentiment['hsi_ma5'] > sentiment['hsi_ma20']:
                sentiment['hsi_trend'] = '多头'
            elif hsi_closes[-1] < sentiment['hsi_ma5'] < sentiment['hsi_ma20']:
                sentiment['hsi_trend'] = '空头'

    if hstech_bars and len(hstech_bars) >= 2:
        hstech_closes = [b.close for b in hstech_bars]
        sentiment['hstech_change'] = (hstech_closes[-1] - hstech_closes[-2]) / hstech_closes[-2] * 100 if hstech_closes[-2] > 0 else 0
        sentiment['hstech_price'] = hstech_closes[-1]
        if len(hstech_closes) >= 26:
            sentiment['hstech_rsi'] = calc_rsi(hstech_closes, 14)
            dif, dea, macd_bar = calc_macd(hstech_closes)
            sentiment['hstech_macd'] = '金叉' if macd_bar > 0 and dif > dea else '死叉' if macd_bar < 0 else '中性'
            sentiment['hstech_ma5'] = calc_ma(hstech_closes, 5)
            sentiment['hstech_ma20'] = calc_ma(hstech_closes, 20)
            if hstech_closes[-1] > sentiment['hstech_ma5'] > sentiment['hstech_ma20']:
                sentiment['hstech_trend'] = '多头'
            elif hstech_closes[-1] < sentiment['hstech_ma5'] < sentiment['hstech_ma20']:
                sentiment['hstech_trend'] = '空头'

    buy_count = sum(1 for k in ['hsi_trend', 'hstech_trend'] if sentiment[k] == '多头')
    sell_count = sum(1 for k in ['hsi_trend', 'hstech_trend'] if sentiment[k] == '空头')
    if buy_count >= 2:
        sentiment['overall'] = '偏多'
    elif sell_count >= 2:
        sentiment['overall'] = '偏空'
    else:
        sentiment['overall'] = '震荡'

    return sentiment


def sector_analysis(results: List[StockScanResult]) -> Dict:
    sector_data = {}
    for r in results:
        industry = r.industry or infer_industry(r.name)
        if industry not in sector_data:
            sector_data[industry] = {'count': 0, 'avg_score': 0, 'buy_count': 0, 'sell_count': 0, 'total_score': 0}
        s = sector_data[industry]
        s['count'] += 1
        s['total_score'] += r.total_score
        if r.total_score > 20:
            s['buy_count'] += 1
        elif r.total_score < -10:
            s['sell_count'] += 1

    for industry, s in sector_data.items():
        s['avg_score'] = s['total_score'] / s['count'] if s['count'] > 0 else 0

    sorted_sectors = sorted(sector_data.items(), key=lambda x: x[1]['avg_score'], reverse=True)
    return sorted_sectors


def infer_industry(name: str) -> str:
    industry_keywords = {
        '银行': ['银行', 'Bank'], '保险': ['保险', 'Ins'],
        '地产': ['地产', '房地产', '置业', 'Property', 'Real'],
        '科技': ['科技', 'Tech', '软件', '信息', '互联网', '数码'],
        '消费': ['消费', '零售', '百货', '超市', '便利店'],
        '医药': ['医药', '制药', '药业', '生物', '医疗', '健康'],
        '能源': ['石油', '天然气', '煤炭', '能源', 'Energy', 'Oil'],
        '金融': ['证券', '信托', '基金', '金融', 'Fin'],
        '制造': ['制造', '工业', '机械', '装备', '建材', '钢铁'],
        '电信': ['电信', '通信', 'Mobile', 'Telecom'],
        '汽车': ['汽车', '车', 'Auto', 'Motor'],
        '航空': ['航空', '飞机', 'Airlines', 'Air'],
        '电力': ['电力', '电能', 'Power', 'Electric'],
        '航运': ['航运', '港口', '物流', 'Shipping', 'Port'],
        '食品': ['食品', '饮料', '乳', '酒', '茶'],
        '纺织': ['纺织', '服装', '鞋', 'Apparel'],
        '教育': ['教育', '培训', 'Education'],
        '传媒': ['传媒', '媒体', '出版', 'Media', 'Entertainment'],
        '新能源': ['光伏', '新能源', '锂', '电池', 'Solar', 'EV'],
        '半导体': ['芯片', '半导体', 'Chip', 'Semiconductor'],
        '游戏': ['游戏', 'Game', '娱乐'],
    }
    for industry, keywords in industry_keywords.items():
        for kw in keywords:
            if kw in name:
                return industry
    return '其他'


# ─────────────────────── 报告生成 ───────────────────────

def generate_report(results: List[StockScanResult], sentiment: Dict, sectors,
                    report_date: str, data_source: str, total_scanned: int) -> str:
    buy_candidates = sorted([r for r in results if r.total_score > 20], key=lambda x: x.total_score, reverse=True)[:10]
    sell_candidates = sorted([r for r in results if r.total_score < -10], key=lambda x: x.total_score)[:5]

    lines = []
    lines.append(f"📊 港股全主板荐股报告 | {report_date}")
    lines.append("=" * 40)
    lines.append(f"数据来源: {data_source} | 扫描标的: {total_scanned}只")
    lines.append("")

    # 市场情绪
    lines.append("📈 市场情绪判断")
    lines.append("-" * 20)
    if sentiment['hsi_price'] > 0:
        lines.append(f"恒生指数: {sentiment['hsi_price']:.0f} | {sentiment['hsi_trend']} | RSI={sentiment['hsi_rsi']:.0f} | MACD={sentiment['hsi_macd']} | 涨跌={sentiment['hsi_change']:+.2f}%")
    else:
        lines.append(f"恒生指数: {sentiment['hsi_trend']} | RSI={sentiment['hsi_rsi']:.0f} | MACD={sentiment['hsi_macd']} | 涨跌={sentiment['hsi_change']:+.2f}%")
    if sentiment['hstech_price'] > 0:
        lines.append(f"恒生科技: {sentiment['hstech_price']:.0f} | {sentiment['hstech_trend']} | RSI={sentiment['hstech_rsi']:.0f} | MACD={sentiment['hstech_macd']} | 涨跌={sentiment['hstech_change']:+.2f}%")
    else:
        lines.append(f"恒生科技: {sentiment['hstech_trend']} | RSI={sentiment['hstech_rsi']:.0f} | MACD={sentiment['hstech_macd']} | 涨跌={sentiment['hstech_change']:+.2f}%")
    lines.append(f"综合判断: {sentiment['overall']}")
    lines.append("")

    # 买入推荐
    if buy_candidates:
        lines.append("🔥 推荐买入标的 TOP 10")
        lines.append("-" * 20)
        for i, r in enumerate(buy_candidates, 1):
            entry = r.price * 0.98
            stop_loss = r.price * 0.94
            take_profit = r.price * 1.15
            buy_reasons = [s.reason for s in r.buy_signals[:3]]
            reason_str = ' | '.join(buy_reasons) if buy_reasons else '综合得分偏高'
            medal = ['🥇', '🥈', '🥉', '🏅', '🏅', '🏅', '🏅', '🏅', '🏅', '🏅'][min(i-1, 9)]

            lines.append(f"{medal}{i}. {r.code} {r.name}")
            lines.append(f"   💰 现价{r.price:.2f}港元 ({r.change_pct:+.2f}%)")
            lines.append(f"   🎯 入场{entry:.2f} | 止损{stop_loss:.2f} | 目标{take_profit:.2f}")
            lines.append(f"   📊 得分{r.total_score:.0f} | RSI={r.rsi:.0f} | MACD={r.macd_signal}")
            lines.append(f"   📝 {reason_str}")
            lines.append(f"   🏭 {r.industry or infer_industry(r.name)}")
            lines.append("")
    else:
        lines.append("今日暂无强买入信号标的")
        lines.append("")

    # 卖出建议
    if sell_candidates:
        lines.append("⚠️ 建议卖出/减仓标的 TOP 5")
        lines.append("-" * 20)
        for i, r in enumerate(sell_candidates, 1):
            sell_reasons = [s.reason for s in r.sell_signals[:3]]
            reason_str = ' | '.join(sell_reasons) if sell_reasons else '综合得分偏低'
            lines.append(f"🔻{i}. {r.code} {r.name}")
            lines.append(f"   💰 现价{r.price:.2f}港元 ({r.change_pct:+.2f}%)")
            lines.append(f"   📊 得分{r.total_score:.0f} | RSI={r.rsi:.0f} | MACD={r.macd_signal}")
            lines.append(f"   📝 {reason_str}")
            lines.append(f"   🏭 {r.industry or infer_industry(r.name)}")
            lines.append("")
    else:
        lines.append("今日暂无强卖出信号标的")
        lines.append("")

    # 行业板块轮动
    lines.append("🔄 行业板块信号轮动")
    lines.append("-" * 20)
    hot_sectors = [s for s in sectors[:5] if s[1]['avg_score'] > 0]
    cold_sectors = [s for s in sectors[-5:] if s[1]['avg_score'] < 0]
    if hot_sectors:
        lines.append("🔥 热门板块:")
        for name, s in hot_sectors:
            lines.append(f"   {name}: 平均得分{s['avg_score']:.1f} | 买入{s['buy_count']}只 / 共{s['count']}只")
    if cold_sectors:
        lines.append("❄️ 冷门板块:")
        for name, s in cold_sectors:
            lines.append(f"   {name}: 平均得分{s['avg_score']:.1f} | 卖出{s['sell_count']}只 / 共{s['count']}只")
    if not hot_sectors and not cold_sectors:
        lines.append("各板块信号相对均衡")
    lines.append("")

    # 扫描统计
    total = len(results)
    buy_count = len([r for r in results if r.total_score > 20])
    sell_count = len([r for r in results if r.total_score < -10])
    neutral_count = total - buy_count - sell_count
    lines.append(f"📊 扫描统计: 共{total}只 | 买入信号{buy_count}只 | 卖出信号{sell_count}只 | 中性{neutral_count}只")
    lines.append("")

    # 风险提示
    lines.append("⚠️ 风险提示")
    lines.append("-" * 20)
    lines.append("1. 以上荐股仅供参考，不构成投资建议")
    lines.append("2. 港股市场波动较大，需注意汇率风险和做空机制")
    lines.append("3. 技术指标存在滞后性，建议结合基本面综合判断")
    lines.append("4. 入场前请做好仓位管理和风险控制")
    lines.append("5. 过往信号表现不代表未来收益")

    return '\n'.join(lines)


def save_report(report: str, results: List[StockScanResult], report_date: str):
    reports_dir = os.path.join(PROJECT_ROOT, 'reports', 'hk_daily')
    os.makedirs(reports_dir, exist_ok=True)

    txt_path = os.path.join(reports_dir, f'hk_report_{report_date}.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f"报告已保存: {txt_path}")

    json_path = os.path.join(reports_dir, f'hk_scan_{report_date}.json')
    data = {
        'date': report_date, 'timestamp': datetime.now().isoformat(),
        'total_stocks': len(results),
        'buy_count': len([r for r in results if r.total_score > 20]),
        'sell_count': len([r for r in results if r.total_score < -10]),
        'top_buy': [asdict(r) for r in sorted([r for r in results if r.total_score > 20], key=lambda x: x.total_score, reverse=True)[:10]],
        'top_sell': [asdict(r) for r in sorted([r for r in results if r.total_score < -10], key=lambda x: x.total_score)[:5]],
        'all_results': [asdict(r) for r in results[:50]],
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"数据已保存: {json_path}")

    return txt_path, json_path


# ─────────────────────── 主流程 ───────────────────────

def is_hk_trading_day():
    today = date.today()
    if today.weekday() >= 5:
        return False, "周末休市"

    # 香港交易所 2026 年官方公众假期（来源: HKEX Circular ce_SEHK_CT_075_2025）
    hk_holidays = [
        '2026-01-01',  # 元旦
        '2026-02-17', '2026-02-18', '2026-02-19',  # 农历新年
        '2026-04-03',  # 耶稣受难节 Good Friday
        '2026-04-06',  # 清明节翌日
        '2026-04-07',  # 复活节星期一翌日
        '2026-05-01',  # 劳动节
        '2026-05-25',  # 佛诞翌日
        '2026-06-19',  # 端午节
        '2026-07-01',  # 香港特别行政区成立纪念日
        '2026-10-01',  # 国庆节
        '2026-10-19',  # 重阳节翌日
        '2026-12-25',  # 圣诞节
    ]

    if today.isoformat() in hk_holidays:
        return False, f"香港公众假期({today.isoformat()})"

    return True, "交易日"


def main():
    logger.info("=" * 40)
    logger.info("港股全主板荐股报告生成（增强版）")
    logger.info("=" * 40)

    is_trading, reason = is_hk_trading_day()
    if not is_trading:
        logger.info(f"今日非交易日: {reason}，跳过推送")
        reports_dir = os.path.join(PROJECT_ROOT, 'reports', 'hk_daily')
        os.makedirs(reports_dir, exist_ok=True)
        log_path = os.path.join(reports_dir, f'log_{date.today().isoformat()}.txt')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"非交易日: {reason}，跳过推送\n")
        return None

    session = make_session()

    # 获取行情数据
    quotes, data_source = fetch_hk_spot_list(session)
    if not quotes:
        logger.error("所有行情接口均不可用")
        return None

    logger.info(f"有效港股标的: {len(quotes)} 只 (来源: {data_source})")

    # 市场情绪
    logger.info("分析市场情绪...")
    sentiment = analyze_market_sentiment(session)
    logger.info(f"市场情绪: {sentiment['overall']}")

    # 策略扫描
    logger.info("开始策略扫描...")
    # 扫描 Top 300 标的的K线（按成交额排序）
    top_klines = min(300, len(quotes))
    results = scan_market(quotes, session, top_klines=top_klines)

    # 行业板块分析
    sectors = sector_analysis(results)

    # 生成报告
    report_date = date.today().strftime('%Y-%m-%d')
    report = generate_report(results, sentiment, sectors, report_date, data_source, len(quotes))

    # 保存报告
    txt_path, json_path = save_report(report, results, report_date)

    print(report)
    return txt_path, json_path, report


if __name__ == '__main__':
    main()
