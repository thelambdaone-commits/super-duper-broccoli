"""
事件解码器 - 只解码 OrderFilled 事件
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from web3 import Web3
from eth_utils import to_checksum_address

logger = logging.getLogger(__name__)


class EventDecoder:
    """OrderFilled 事件解码器"""

    # OrderFilled 事件 ABI
    ORDER_FILLED_ABI = [
        ("orderHash", "bytes32", True),
        ("maker", "address", True),
        ("taker", "address", True),
        ("makerAssetId", "uint256", False),
        ("takerAssetId", "uint256", False),
        ("makerAmountFilled", "uint256", False),
        ("takerAmountFilled", "uint256", False),
        ("makerFee", "uint256", False),
        ("takerFee", "uint256", False),
        ("protocolFee", "uint256", False),
    ]

    def __init__(self):
        self.w3 = Web3()

    def decode(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """解码 OrderFilled 事件"""
        topics = record.get('topics', [])
        data = record.get('data', '')

        # 设置事件名（因为我们只爬 OrderFilled）
        record['event_name'] = 'OrderFilled'

        indexed = [(n, t) for n, t, i in self.ORDER_FILLED_ABI if i]
        non_indexed = [(n, t) for n, t, i in self.ORDER_FILLED_ABI if not i]

        params = {}

        # 解码 indexed 参数 (从 topics)
        for i, (name, ptype) in enumerate(indexed):
            if i + 1 < len(topics):
                params[name] = self._decode_topic(ptype, topics[i + 1])

        # 解码 non-indexed 参数 (从 data)
        if non_indexed and data:
            types = [t for _, t in non_indexed]
            values = self._decode_data(types, data)
            for (name, _), val in zip(non_indexed, values):
                params[name] = val

        record['decoded_params'] = params
        return record

    def decode_batch(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量解码"""
        return [self.decode(r) for r in records]

    def format_event(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """格式化 OrderFilled 事件为输出格式"""
        params = record.get('decoded_params', {})

        # 基础字段
        result = {
            'transaction_hash': record.get('transaction_hash', ''),
            'block_number': record.get('block_number', 0),
            'log_index': record.get('log_index', 0),
            'timestamp': record.get('timestamp', 0),
            'contract': record.get('contract', ''),
            'event_name': 'OrderFilled',
        }

        # 格式化时间
        ts = result['timestamp']
        if isinstance(ts, (int, float)) and 0 < ts < 4102444800:
            result['datetime'] = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

        # OrderFilled 参数 (asset_id 是超大整数，必须转成字符串)
        result.update({
            'order_hash': params.get('orderHash', ''),
            'maker': params.get('maker', ''),
            'taker': params.get('taker', ''),
            'maker_asset_id': str(params.get('makerAssetId', 0)),
            'taker_asset_id': str(params.get('takerAssetId', 0)),
            'maker_amount_filled': params.get('makerAmountFilled', 0),
            'taker_amount_filled': params.get('takerAmountFilled', 0),
            'maker_fee': params.get('makerFee', 0),
            'taker_fee': params.get('takerFee', 0),
            'protocol_fee': params.get('protocolFee', 0),
        })

        return result

    def format_batch(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量格式化"""
        return [self.format_event(r) for r in records]

    def _decode_topic(self, ptype: str, value: str) -> Any:
        """解码 topic"""
        try:
            val = value.replace('0x', '').zfill(64)
            if ptype == 'address':
                return to_checksum_address('0x' + val[24:])
            elif ptype == 'uint256':
                return int(val, 16)
            elif ptype == 'bytes32':
                return value
            return value
        except (ValueError, TypeError, AttributeError):
            return value

    def _decode_data(self, types: List[str], data: Any) -> List[Any]:
        """解码 data 字段"""
        try:
            if isinstance(data, bytes):
                data = data.hex()
            clean = data.replace('0x', '')
            if len(clean) % 64 != 0:
                clean = clean.ljust(((len(clean) // 64) + 1) * 64, '0')

            results = []
            offset = 0

            for ptype in types:
                if offset + 64 > len(clean):
                    results.append(0 if ptype.startswith('uint') else None)
                    continue

                chunk = clean[offset:offset + 64]

                if ptype.startswith('uint') and not ptype.endswith('[]'):
                    results.append(int(chunk, 16))
                elif ptype == 'address':
                    results.append(to_checksum_address('0x' + chunk[24:]))
                elif ptype.endswith('[]'):
                    # 简化处理数组
                    results.append([])
                else:
                    results.append('0x' + chunk)

                offset += 64

            return results
        except Exception as e:
            logger.warning(f"解码失败: {e}")
            return [0 if t.startswith('uint') else None for t in types]
