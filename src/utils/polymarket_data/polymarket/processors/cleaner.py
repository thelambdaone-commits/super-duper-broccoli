#!/usr/bin/env python3
"""
Polymarket 数据清洗模块

功能：
1. clean_users: 用户交易数据清洗
   - 过滤合约地址和NaN价格
   - 拆分maker/taker为独立用户记录
   - 统一YES视角和方向
   - 按用户、时间排序

2. clean_trades: 交易数据清洗
   - 过滤合约地址和NaN价格
   - 统一YES视角
   - 保持原有字段
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# 合约地址（taker是这些地址的记录要删除）
CONTRACT_ADDRESSES = {
    '0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e',
    '0xc5d563a36ae78145c45a50134d48a1215220f80a'
}

# 默认批处理大小
DEFAULT_BATCH_SIZE = 5_000_000


def _process_users_batch(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    处理用户数据批次

    1. 过滤NaN价格和合约地址
    2. 拆分maker/taker
    3. 统一YES视角
    4. 统一方向（SELL转BUY，token_amount取负）
    """
    original_rows = len(df)

    # 添加原始顺序索引
    df = df.reset_index(drop=True)
    df['_original_order'] = df.index

    # 1. 过滤NaN价格
    nan_mask = df['price'].isna()
    if nan_mask.any():
        df = df[~nan_mask]

    # 2. 过滤合约地址（转小写比较）
    contract_mask = df['taker'].str.lower().isin(CONTRACT_ADDRESSES)
    if contract_mask.any():
        df = df[~contract_mask]

    if len(df) == 0:
        return None

    # 需要保留的公共字段
    common_cols = ['timestamp', 'datetime', 'block_number', 'transaction_hash',
                   'event_id', 'market_id', 'condition_id', '_original_order',
                   'nonusdc_side', 'price', 'token_amount', 'usd_amount']

    # 3. 拆分双方
    maker_df = df[common_cols + ['maker', 'maker_direction']].copy()
    maker_df = maker_df.rename(columns={'maker': 'user', 'maker_direction': 'direction'})
    maker_df['role'] = 'maker'
    maker_df['_sub_order'] = 0

    taker_df = df[common_cols + ['taker', 'taker_direction']].copy()
    taker_df = taker_df.rename(columns={'taker': 'user', 'taker_direction': 'direction'})
    taker_df['role'] = 'taker'
    taker_df['_sub_order'] = 1

    result_df = pd.concat([maker_df, taker_df], ignore_index=True)

    # 4. 统一YES视角
    is_token2 = result_df['nonusdc_side'] == 'token2'
    result_df.loc[is_token2, 'price'] = 1 - result_df.loc[is_token2, 'price']

    # 5. 统一方向
    is_sell = result_df['direction'] == 'SELL'
    result_df.loc[is_sell, 'token_amount'] = -result_df.loc[is_sell, 'token_amount']
    result_df['direction'] = 'BUY'

    # 保持顺序
    result_df = result_df.sort_values(['_original_order', '_sub_order'])
    result_df = result_df.drop(columns=['_original_order', '_sub_order', 'nonusdc_side'])

    # 最终列顺序
    result_df = result_df[['timestamp', 'datetime', 'block_number', 'transaction_hash',
                           'event_id', 'market_id', 'condition_id',
                           'user', 'role', 'price', 'token_amount', 'usd_amount']]

    return result_df


def _process_trades_batch(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    处理交易数据批次

    1. 过滤NaN价格和合约地址
    2. 统一YES视角
    """
    # 1. 过滤NaN价格
    nan_mask = df['price'].isna()
    if nan_mask.any():
        df = df[~nan_mask]

    # 2. 过滤合约地址（转小写比较）
    contract_mask = df['taker'].str.lower().isin(CONTRACT_ADDRESSES)
    if contract_mask.any():
        df = df[~contract_mask]

    if len(df) == 0:
        return None

    # 3. 统一YES视角
    df = df.copy()
    is_token2 = df['nonusdc_side'] == 'token2'
    df.loc[is_token2, 'price'] = 1 - df.loc[is_token2, 'price']
    df['nonusdc_side'] = 'token1'

    return df


def _sort_with_best_method(input_path: str, output_path: str, sort_columns: list):
    """使用最佳可用方法进行排序"""
    import os
    temp_output = output_path + '.tmp'
    sorted_ok = False

    # 方案1: DuckDB
    try:
        import duckdb
        logger.info("使用 DuckDB 排序...")
        order_clause = ', '.join(sort_columns)
        conn = duckdb.connect()
        conn.execute(f"""
            COPY (
                SELECT * FROM read_parquet('{input_path}')
                ORDER BY {order_clause}
            ) TO '{temp_output}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)
        conn.close()
        os.replace(temp_output, output_path)
        sorted_ok = True
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"DuckDB 排序失败: {e}")

    # 方案2: Polars
    if not sorted_ok:
        try:
            import polars as pl
            logger.info("使用 Polars 排序...")
            df = pl.scan_parquet(input_path).sort(sort_columns).collect()
            df.write_parquet(temp_output, compression='snappy')
            os.replace(temp_output, output_path)
            sorted_ok = True
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Polars 排序失败: {e}")

    # 方案3: PyArrow
    if not sorted_ok:
        logger.info("使用 PyArrow 排序...")
        table = pq.read_table(input_path)
        sort_keys = [(col, 'ascending') for col in sort_columns]
        sorted_table = table.sort_by(sort_keys)
        pq.write_table(sorted_table, output_path, compression='snappy')


def clean_users(
    input_path: Path,
    output_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    test_rows: Optional[int] = None
) -> dict:
    """
    清洗用户交易数据

    Args:
        input_path: 输入 trades.parquet 路径
        output_path: 输出 users.parquet 路径
        batch_size: 批处理大小
        test_rows: 测试模式，只处理前N行

    Returns:
        统计信息字典
    """
    start_time = datetime.now()
    logger.info(f"开始清洗用户数据: {input_path}")

    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    parquet_file = pq.ParquetFile(input_path)
    total_rows = parquet_file.metadata.num_rows
    if test_rows:
        total_rows = min(total_rows, test_rows)

    logger.info(f"总行数: {total_rows:,}")

    writer = None
    rows_processed = 0
    rows_written = 0
    batch_num = 0

    for batch in parquet_file.iter_batches(batch_size=batch_size):
        if test_rows and rows_processed >= test_rows:
            break

        batch_num += 1
        df = batch.to_pandas()

        if test_rows:
            remaining = test_rows - rows_processed
            df = df.head(remaining)

        result_df = _process_users_batch(df)

        if result_df is not None and len(result_df) > 0:
            result_table = pa.Table.from_pandas(result_df, preserve_index=False)

            if writer is None:
                writer = pq.ParquetWriter(str(output_path), result_table.schema, compression='snappy')

            writer.write_table(result_table)
            rows_written += len(result_df)

        rows_processed += len(df)
        progress = rows_processed / total_rows * 100
        logger.info(f"批次 {batch_num}: {rows_processed:,}/{total_rows:,} ({progress:.1f}%)")

    if writer:
        writer.close()

    clean_elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"清洗完成! 耗时: {clean_elapsed:.1f}秒")

    # 全局排序
    logger.info("开始全局排序（按用户、时间）...")
    sort_start = datetime.now()
    _sort_with_best_method(str(output_path), str(output_path), ['user', 'timestamp'])
    sort_elapsed = (datetime.now() - sort_start).total_seconds()
    logger.info(f"排序完成! 耗时: {sort_elapsed:.1f}秒")

    total_elapsed = (datetime.now() - start_time).total_seconds()

    stats = {
        'input_rows': rows_processed,
        'output_rows': rows_written,
        'expansion_ratio': rows_written / rows_processed if rows_processed > 0 else 0,
        'elapsed_seconds': total_elapsed
    }

    logger.info(f"用户数据清洗完成: {rows_processed:,} -> {rows_written:,} "
                f"({stats['expansion_ratio']:.2f}x), 耗时: {total_elapsed:.1f}秒")

    return stats


def clean_trades(
    input_path: Path,
    output_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    test_rows: Optional[int] = None
) -> dict:
    """
    清洗交易数据

    Args:
        input_path: 输入 trades.parquet 路径
        output_path: 输出 quant.parquet 路径
        batch_size: 批处理大小
        test_rows: 测试模式，只处理前N行

    Returns:
        统计信息字典
    """
    start_time = datetime.now()
    logger.info(f"开始清洗交易数据: {input_path}")

    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    parquet_file = pq.ParquetFile(input_path)
    total_rows = parquet_file.metadata.num_rows
    if test_rows:
        total_rows = min(total_rows, test_rows)

    logger.info(f"总行数: {total_rows:,}")

    writer = None
    rows_processed = 0
    rows_written = 0
    batch_num = 0

    for batch in parquet_file.iter_batches(batch_size=batch_size):
        if test_rows and rows_processed >= test_rows:
            break

        batch_num += 1
        df = batch.to_pandas()

        if test_rows:
            remaining = test_rows - rows_processed
            df = df.head(remaining)

        result_df = _process_trades_batch(df)

        if result_df is not None and len(result_df) > 0:
            result_table = pa.Table.from_pandas(result_df, preserve_index=False)

            if writer is None:
                writer = pq.ParquetWriter(str(output_path), result_table.schema, compression='snappy')

            writer.write_table(result_table)
            rows_written += len(result_df)

        rows_processed += len(df)
        progress = rows_processed / total_rows * 100
        logger.info(f"批次 {batch_num}: {rows_processed:,}/{total_rows:,} ({progress:.1f}%)")

    if writer:
        writer.close()

    elapsed = (datetime.now() - start_time).total_seconds()

    stats = {
        'input_rows': rows_processed,
        'output_rows': rows_written,
        'retention_ratio': rows_written / rows_processed if rows_processed > 0 else 0,
        'elapsed_seconds': elapsed
    }

    logger.info(f"交易数据清洗完成: {rows_processed:,} -> {rows_written:,} "
                f"({stats['retention_ratio']*100:.1f}%), 耗时: {elapsed:.1f}秒")

    return stats


def clean_trades_df(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    清洗单个 trades DataFrame（用于增量处理）

    Args:
        trades_df: 原始 trades DataFrame

    Returns:
        清洗后的 quant DataFrame
    """
    result = _process_trades_batch(trades_df)
    return result if result is not None else pd.DataFrame()


def clean_users_df(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    清洗单个 trades DataFrame 生成 users 数据（用于增量处理）

    Args:
        trades_df: 原始 trades DataFrame

    Returns:
        清洗后的 users DataFrame
    """
    result = _process_users_batch(trades_df)
    return result if result is not None else pd.DataFrame()
