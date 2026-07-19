#!/usr/bin/env python3
"""K线缓存批量填充脚本 —— 为全市场扫描铺路"""
from __future__ import annotations
import json, os, sys, time, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src.data.akshare_client import TencentClient

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(BASE, 'data', 'cache')

def fill_kline(code: str, client: TencentClient) -> bool:
    """拉取并缓存单只K线"""
    cache_path = os.path.join(CACHE_DIR, f'klines_{code}.json')
    
    # 跳过已有且新鲜的缓存
    if os.path.exists(cache_path):
        try:
            data = json.load(open(cache_path))
            candles = data.get('candles', [])
            if candles and len(candles) >= 120:
                from datetime import date, timedelta
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                if candles[-1].get('date', '') >= yesterday:
                    return False  # 已缓存，跳过
        except:
            pass
    
    try:
        bars = client.get_kline(code, days=600)
        if bars and len(bars) >= 120:
            candles = [
                {'date': b.date, 'open': b.open, 'high': b.high,
                 'low': b.low, 'close': b.close, 'volume': b.volume}
                for b in bars
            ]
            json.dump({'date': date.today().isoformat(), 'candles': candles},
                     open(cache_path, 'w'))
            return True
    except Exception as e:
        logger.debug(f"失败 {code}: {e}")
    return False


if __name__ == '__main__':
    t0 = time.time()
    
    # 加载所有A股代码
    with open(os.path.join(CACHE_DIR, 'a_codes.json')) as f:
        codes = [c['code'] for c in json.load(f)['codes'] if c.get('price', 0) > 0]
    
    logger.info(f"全市场: {len(codes)} 只 → 批量拉K线")
    
    client = TencentClient()
    done = 0
    skipped = 0
    
    # 线程池并发拉取
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fill_kline, code, client): code for code in codes}
        for f in as_completed(futures):
            code = futures[f]
            try:
                if f.result():
                    done += 1
                else:
                    skipped += 1
            except:
                skipped += 1
            
            total = done + skipped
            if total % 100 == 0:
                logger.info(f"  进度 {total}/{len(codes)} | 新增 {done} | 跳过 {skipped} | {time.time()-t0:.0f}s")
    
    logger.info(f"\n✅ 完成: 新增 {done} 只, 跳过 {skipped} 只, 耗时 {time.time()-t0:.0f}s")
