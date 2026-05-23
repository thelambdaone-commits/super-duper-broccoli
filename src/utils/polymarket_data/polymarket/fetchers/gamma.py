"""
Gamma API 客户端 - 获取市场元数据
"""

import json
import logging
import time
from typing import Dict, List, Any, Optional, Generator

import requests

from ..config import GAMMA_API_URL

logger = logging.getLogger(__name__)


class GammaApiClient:
    """Gamma API 客户端"""

    def __init__(self, timeout: int = 60, max_retries: int = 5):
        self.base_url = GAMMA_API_URL
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        # 设置默认 headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """发送请求"""
        url = f"{self.base_url}/{endpoint}"

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    wait_time = 5 * (attempt + 1)
                    logger.warning(f"API 限流，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"API 错误 {resp.status_code}")
                    time.sleep(3)
                    continue

            except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as e:
                wait_time = 5 * (attempt + 1)
                logger.warning(f"连接超时 (尝试 {attempt+1}/{self.max_retries})，等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
            except requests.exceptions.RequestException as e:
                logger.error(f"网络错误 (尝试 {attempt+1}/{self.max_retries}): {e}")
                time.sleep(5)
                continue

        logger.error(f"请求失败，已重试 {self.max_retries} 次")
        return None

    def get_markets(self, limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
        """获取市场列表"""
        params = {
            'limit': limit,
            'offset': offset,
            'order': 'createdAt',
            'ascending': 'true'
        }
        data = self._request('markets', params)
        if not data:
            return []
        return [self._parse_market(m) for m in data]

    def iter_all_markets(self, batch_size: int = 500) -> Generator[Dict[str, Any], None, None]:
        """迭代获取所有市场"""
        offset = 0
        while True:
            markets = self.get_markets(limit=batch_size, offset=offset)
            if not markets:
                break
            for m in markets:
                yield m
            if len(markets) < batch_size:
                break
            offset += len(markets)
            time.sleep(0.5)

    def fetch_all_markets(self, max_markets: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取所有市场"""
        markets = []
        for m in self.iter_all_markets():
            markets.append(m)
            if max_markets and len(markets) >= max_markets:
                break
        return markets

    def _parse_market(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """解析市场数据"""
        outcomes = self._parse_json(raw.get('outcomes', '[]'))
        clob_tokens = self._parse_json(raw.get('clobTokenIds', '[]'))
        outcome_prices = self._parse_json(raw.get('outcomePrices', '[]'))

        # 解析 event 信息
        events = raw.get('events', [])
        event_info = events[0] if events else {}

        return {
            'id': raw.get('id', ''),
            'question': raw.get('question', '') or raw.get('title', ''),
            'answer1': outcomes[0] if len(outcomes) > 0 else '',
            'answer2': outcomes[1] if len(outcomes) > 1 else '',
            'token1': clob_tokens[0] if len(clob_tokens) > 0 else '',
            'token2': clob_tokens[1] if len(clob_tokens) > 1 else '',
            'condition_id': raw.get('conditionId', ''),
            'neg_risk': raw.get('negRiskAugmented', False) or raw.get('negRisk', False),
            'slug': raw.get('slug', ''),
            'volume': raw.get('volume', ''),
            'created_at': raw.get('createdAt', ''),
            # 状态字段 - 使用 closed 而不是 resolved
            'closed': raw.get('closed', False),
            'active': raw.get('active', True),
            'archived': raw.get('archived', False),
            'end_date': raw.get('endDate', ''),
            # 结算结果 - outcomePrices 数组 [price1, price2]，值接近1的选项获胜
            'outcome_prices': str(outcome_prices) if outcome_prices else '[]',
            # Event 信息
            'event_id': event_info.get('id', ''),
            'event_slug': event_info.get('slug', ''),
            'event_title': event_info.get('title', ''),
        }

    def _parse_json(self, value: Any) -> List:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError, TypeError):
                return []
        return []

    def get_token_mapping(self, markets: Optional[List[Dict]] = None) -> Dict[str, Dict]:
        """创建 token_id -> market 映射"""
        if markets is None:
            markets = self.fetch_all_markets()

        mapping = {}
        for m in markets:
            if m['token1']:
                mapping[m['token1']] = {'market_id': m['id'], 'answer': m['answer1']}
            if m['token2']:
                mapping[m['token2']] = {'market_id': m['id'], 'answer': m['answer2']}
        return mapping

    def test_connection(self) -> bool:
        try:
            return bool(self.get_markets(limit=1))
        except (requests.exceptions.RequestException, ValueError, KeyError):
            return False

    def get_market_by_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        """通过 token_id 获取市场"""
        params = {'clob_token_ids': token_id}
        data = self._request('markets', params)
        if data and len(data) > 0:
            return self._parse_market(data[0])
        return None

    def fetch_missing_tokens(self, token_ids: List[str]) -> List[Dict[str, Any]]:
        """批量获取缺失的 token 对应的市场"""
        markets = []
        seen_market_ids = set()

        for token_id in token_ids:
            market = self.get_market_by_token(token_id)
            if market and market['id'] not in seen_market_ids:
                markets.append(market)
                seen_market_ids.add(market['id'])
                logger.info(f"找到市场 {market['id']} (token: {token_id[:20]}...)")
            time.sleep(0.3)

        logger.info(f"共找到 {len(markets)} 个缺失市场")
        return markets
