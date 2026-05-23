#!/usr/bin/env python3
"""
Parquet 文件排序脚本 - 内存高效版本
使用 DuckDB 外部排序，适合大文件处理

用法:
    # 直接指定输入输出文件路径
    python scripts/sort_parquet.py users -i /path/to/users.parquet -o /path/to/users_sorted.parquet
    python scripts/sort_parquet.py quant -i /path/to/quant.parquet -o /path/to/quant_sorted.parquet

    # 使用默认目录 (data/data_clean)
    python scripts/sort_parquet.py users
    python scripts/sort_parquet.py quant

    # 测试模式 (只处理前100万行)
    python scripts/sort_parquet.py users -i /path/to/users.parquet -o /path/to/test.parquet --test

cd /inspire/ssd/project/liyikang/wangzhengjie-253108090056/poly_onchain

nohup python scripts/sort_parquet.py users \
    -i /inspire/hdd/project/liyikang/public/Polymarket_dataset/dataset_latest/users.parquet \
    -o /inspire/hdd/project/liyikang/public/Polymarket_dataset/dataset_latest/users_sorted.parquet \
    > logs/sort_users.log 2>&1 &

nohup python scripts/sort_parquet.py quant \
    -i /inspire/hdd/project/liyikang/public/Polymarket_dataset/dataset_latest/quant.parquet \
    -o /inspire/hdd/project/liyikang/public/Polymarket_dataset/dataset_latest/quant_sorted.parquet \
    > logs/sort_quant.log 2>&1 &

# 查看进度
tail -f logs/sort_users.log

参数说明:
    users/quant   要排序的文件类型
    -i/--input    输入文件路径 (完整路径)
    -o/--output   输出文件路径 (完整路径)
    --test        测试模式，只处理前100万行
"""

import argparse
import os
import sys
import time
import gc
import shutil
from pathlib import Path

# DuckDB 用于内存高效的外部排序
import duckdb


def log(msg: str):
    """带时间戳的日志输出，立即 flush"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_temp_dir() -> str:
    """获取临时目录 - 集群用 SSD，本地用项目目录"""
    if os.path.exists('/inspire/ssd'):
        # 集群：用 SSD 目录，避免 HDD IO 问题
        temp_dir = '/inspire/ssd/project/liyikang/wangzhengjie-253108090056/.duckdb_temp'
    else:
        # 本地：用项目目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        temp_dir = os.path.join(script_dir, '..', '.duckdb_temp')
    temp_dir = os.path.abspath(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir


def cleanup_temp(temp_dir: str):
    """清理 DuckDB 临时文件"""
    if os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            log(f"清理临时目录失败: {e}")


def get_memory_limit_gb():
    """获取可用内存的一半作为限制"""
    try:
        import psutil
        available_gb = psutil.virtual_memory().available / (1024**3)
        # 使用可用内存的 50%，最多 64GB (集群可能内存更大)
        return min(available_gb * 0.5, 64)
    except ImportError:
        return 8  # 默认 8GB


def sort_users_parquet(input_path: str, output_path: str, test_mode: bool = False):
    """
    排序 users.parquet
    排序优先级: 1. user, 2. timestamp
    """
    log("=" * 60)
    log("排序 users.parquet")
    log(f"输入: {input_path}")
    log(f"输出: {output_path}")
    log(f"测试模式: {test_mode}")
    log("=" * 60)

    mem_limit = get_memory_limit_gb()
    log(f"内存限制: {mem_limit:.1f} GB")

    start_time = time.time()

    # 获取临时文件夹
    temp_dir = get_temp_dir()
    log(f"临时目录: {temp_dir}")

    # 创建 DuckDB 连接，配置外部排序
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{mem_limit:.0f}GB'")
    con.execute(f"SET temp_directory = '{temp_dir}'")
    con.execute("SET preserve_insertion_order = false")  # 允许并行处理

    try:
        # 构建查询
        if test_mode:
            # 测试模式：先限制行数再排序
            query = f"""
                COPY (
                    SELECT * FROM (
                        SELECT *
                        FROM read_parquet('{input_path}')
                        LIMIT 1000000
                    )
                    ORDER BY user ASC, CAST(timestamp AS BIGINT) ASC
                ) TO '{output_path}'
                (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 100000)
            """
        else:
            query = f"""
                COPY (
                    SELECT *
                    FROM read_parquet('{input_path}')
                    ORDER BY user ASC, CAST(timestamp AS BIGINT) ASC
                ) TO '{output_path}'
                (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 100000)
            """

        log("开始排序...")
        con.execute(query)

        elapsed = time.time() - start_time

        # 验证输出
        result = con.execute(f"SELECT COUNT(*) FROM read_parquet('{output_path}')").fetchone()
        log(f"完成! 输出行数: {result[0]:,}")
        log(f"耗时: {elapsed:.1f} 秒")

        # 显示排序后的样本
        log("排序后前5行:")
        samples = con.execute(f"""
            SELECT user, timestamp
            FROM read_parquet('{output_path}')
            LIMIT 5
        """).fetchall()
        for user, ts in samples:
            print(f"  {user[:20]}... | {ts}", flush=True)

    finally:
        con.close()
        del con
        gc.collect()
        cleanup_temp(temp_dir)
        log("内存已释放")


def sort_quant_parquet(input_path: str, output_path: str, test_mode: bool = False):
    """
    排序 quant.parquet
    排序优先级: 1. event_id, 2. market_id, 3. timestamp
    """
    log("=" * 60)
    log("排序 quant.parquet")
    log(f"输入: {input_path}")
    log(f"输出: {output_path}")
    log(f"测试模式: {test_mode}")
    log("=" * 60)

    mem_limit = get_memory_limit_gb()
    log(f"内存限制: {mem_limit:.1f} GB")

    start_time = time.time()

    # 获取临时文件夹
    temp_dir = get_temp_dir()
    log(f"临时目录: {temp_dir}")

    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{mem_limit:.0f}GB'")
    con.execute(f"SET temp_directory = '{temp_dir}'")
    con.execute("SET preserve_insertion_order = false")

    try:
        # 使用 TRY_CAST 处理空值或无效值
        if test_mode:
            query = f"""
                COPY (
                    SELECT * FROM (
                        SELECT *
                        FROM read_parquet('{input_path}')
                        LIMIT 1000000
                    )
                    ORDER BY
                        COALESCE(TRY_CAST(event_id AS BIGINT), 0) ASC,
                        COALESCE(TRY_CAST(market_id AS BIGINT), 0) ASC,
                        COALESCE(TRY_CAST(timestamp AS BIGINT), 0) ASC
                ) TO '{output_path}'
                (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 100000)
            """
        else:
            query = f"""
                COPY (
                    SELECT *
                    FROM read_parquet('{input_path}')
                    ORDER BY
                        COALESCE(TRY_CAST(event_id AS BIGINT), 0) ASC,
                        COALESCE(TRY_CAST(market_id AS BIGINT), 0) ASC,
                        COALESCE(TRY_CAST(timestamp AS BIGINT), 0) ASC
                ) TO '{output_path}'
                (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 100000)
            """

        log("开始排序...")
        con.execute(query)

        elapsed = time.time() - start_time

        result = con.execute(f"SELECT COUNT(*) FROM read_parquet('{output_path}')").fetchone()
        log(f"完成! 输出行数: {result[0]:,}")
        log(f"耗时: {elapsed:.1f} 秒")

        log("排序后前5行:")
        samples = con.execute(f"""
            SELECT event_id, market_id, timestamp, event_title
            FROM read_parquet('{output_path}')
            LIMIT 5
        """).fetchall()
        for eid, mid, ts, title in samples:
            print(f"  event={eid}, market={mid}, ts={ts} | {title[:40]}...", flush=True)

    finally:
        con.close()
        del con
        gc.collect()
        cleanup_temp(temp_dir)
        log("内存已释放")


def main():
    parser = argparse.ArgumentParser(description='Parquet 文件排序脚本')
    parser.add_argument('target', choices=['users', 'quant'],
                        help='要排序的文件类型: users 或 quant')
    parser.add_argument('-i', '--input', default=None,
                        help='输入文件路径 (完整路径)')
    parser.add_argument('-o', '--output', default=None,
                        help='输出文件路径 (完整路径)')
    parser.add_argument('--test', action='store_true',
                        help='测试模式，只处理前100万行')

    args = parser.parse_args()

    # 默认路径
    default_dir = Path('data/data_clean')
    suffix = "_test" if args.test else "_sorted"

    if args.target == 'users':
        input_file = args.input or str(default_dir / 'users.parquet')
        output_file = args.output or str(default_dir / f'users{suffix}.parquet')

        if not os.path.exists(input_file):
            print(f"错误: 文件不存在 {input_file}")
            sys.exit(1)

        sort_users_parquet(input_file, output_file, args.test)

    elif args.target == 'quant':
        input_file = args.input or str(default_dir / 'quant.parquet')
        output_file = args.output or str(default_dir / f'quant{suffix}.parquet')

        if not os.path.exists(input_file):
            print(f"错误: 文件不存在 {input_file}")
            sys.exit(1)

        sort_quant_parquet(input_file, output_file, args.test)

    print("\n" + "="*60, flush=True)
    print("全部完成!", flush=True)
    print("="*60, flush=True)


if __name__ == '__main__':
    main()
