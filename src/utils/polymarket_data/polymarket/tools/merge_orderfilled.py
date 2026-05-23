#!/usr/bin/env python3
"""
专门用于合并 orderfilled 文件的脚本

处理 schema 不一致的问题：
- 统一数据类型为 string
- 统一列顺序
- 处理缺失列
"""
import sys
import argparse
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def convert_batch_to_target_schema(batch, target_schema):
    """
    将 batch 转换为目标 schema

    Args:
        batch: RecordBatch
        target_schema: 目标 schema

    Returns:
        转换后的 RecordBatch
    """
    import pandas as pd

    # 转换为 pandas
    df = batch.to_pandas()

    # 创建新的 DataFrame，按照目标 schema
    new_df = pd.DataFrame()

    for field in target_schema:
        col_name = field.name

        if col_name in df.columns:
            # 列存在，转换类型
            if pa.types.is_string(field.type):
                # 转换为字符串
                new_df[col_name] = df[col_name].astype(str)
            elif pa.types.is_integer(field.type):
                # 转换为整数
                new_df[col_name] = pd.to_numeric(df[col_name], errors='coerce').fillna(0).astype('int64')
            else:
                new_df[col_name] = df[col_name]
        else:
            # 列不存在，创建空列
            if pa.types.is_string(field.type):
                new_df[col_name] = ''
            elif pa.types.is_integer(field.type):
                new_df[col_name] = 0
            else:
                new_df[col_name] = None

    # 转换回 Arrow Table
    table = pa.Table.from_pandas(new_df, schema=target_schema)
    return table.to_batches()[0]


def merge_orderfilled_files(file1, file2, output_file, auto_yes=False):
    """
    合并两个 orderfilled 文件

    Args:
        file1: 第一个文件（需要转换 schema）
        file2: 第二个文件（作为 schema 基准）
        output_file: 输出文件
        auto_yes: 自动确认覆盖
    """
    logger.info("=== 检查输入文件 ===")

    # 检查文件
    pf1 = pq.ParquetFile(file1)
    pf2 = pq.ParquetFile(file2)

    logger.info(f"[1] {Path(file1).name}: {pf1.metadata.num_rows:,} 行")
    logger.info(f"[2] {Path(file2).name}: {pf2.metadata.num_rows:,} 行")
    logger.info(f"总计: {pf1.metadata.num_rows + pf2.metadata.num_rows:,} 行")

    # 获取目标 schema（使用第二个文件的 schema）
    target_schema = pf2.schema_arrow
    logger.info(f"\n目标 schema（基于文件2）:")
    for field in target_schema:
        logger.info(f"  {field.name}: {field.type}")

    # 检查输出文件
    output_path = Path(output_file)
    if output_path.exists():
        logger.warning(f"输出文件已存在，将覆盖: {output_file}")
        if not auto_yes:
            response = input("确认覆盖？(yes/no): ")
            if response.lower() not in ['yes', 'y']:
                logger.info("取消操作")
                return False
        else:
            logger.info("自动确认覆盖（--yes）")

    # 开始合并
    logger.info(f"\n=== 开始合并 ===")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        writer = pq.ParquetWriter(output_file, target_schema, compression='snappy')
        total_rows_written = 0
        batch_size = 500000

        # 处理第一个文件（需要转换 schema）
        logger.info(f"[1/2] 处理 {Path(file1).name}（转换 schema）")
        batch_iter1 = pf1.iter_batches(batch_size=batch_size)
        batch_num = 1

        for batch in batch_iter1:
            # 转换 schema
            converted_batch = convert_batch_to_target_schema(batch, target_schema)
            writer.write_batch(converted_batch)
            total_rows_written += len(converted_batch)
            if batch_num % 10 == 0:
                logger.info(f"  已写入第 {batch_num} 批: {len(converted_batch):,} 行（累计 {total_rows_written:,} 行）")
            batch_num += 1

        logger.info(f"  ✓ 文件1完成，共 {pf1.metadata.num_rows:,} 行")

        # 处理第二个文件（直接写入）
        logger.info(f"[2/2] 处理 {Path(file2).name}")
        batch_iter2 = pf2.iter_batches(batch_size=batch_size)
        batch_num = 1

        for batch in batch_iter2:
            writer.write_batch(batch)
            total_rows_written += len(batch)
            if batch_num % 10 == 0:
                logger.info(f"  已写入第 {batch_num} 批: {len(batch):,} 行（累计 {total_rows_written:,} 行）")
            batch_num += 1

        logger.info(f"  ✓ 文件2完成，共 {pf2.metadata.num_rows:,} 行")

        # 关闭 writer
        writer.close()

        output_size_mb = output_path.stat().st_size / 1024 / 1024
        logger.info(f"\n=== 合并完成 ===")
        logger.info(f"输出文件: {output_file}")
        logger.info(f"总行数: {total_rows_written:,}")
        logger.info(f"文件大小: {output_size_mb:.1f} MB")

        return True

    except Exception as e:
        logger.error(f"合并失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='合并 orderfilled 文件（处理 schema 不一致）'
    )

    parser.add_argument('file1', help='第一个文件（需要转换）')
    parser.add_argument('file2', help='第二个文件（作为 schema 基准）')
    parser.add_argument('-o', '--output', required=True, help='输出文件路径')
    parser.add_argument('-y', '--yes', action='store_true', help='自动确认覆盖')

    args = parser.parse_args()

    success = merge_orderfilled_files(args.file1, args.file2, args.output, args.yes)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
