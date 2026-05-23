#!/usr/bin/env python3
"""
合并多个 parquet 文件

nohup python scripts/merge_parquet.py \
  data/dataset/orderfilled.parquet \
  data/dataset/orderfilled_refetched_20251230_055516.parquet \
  -o data/dataset/orderfilled_merged.parquet \
  -y \
  > logs/merge_orderfilled.log 2>&1 &

支持指定输入文件列表和输出文件，按顺序合并
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


def merge_parquet_files(input_files, output_file, dry_run=False, auto_yes=False):
    """
    合并多个 parquet 文件

    Args:
        input_files: 输入文件列表（按顺序）
        output_file: 输出文件路径
        dry_run: 是否只显示信息不实际合并
        auto_yes: 自动确认覆盖
    """
    # 验证输入文件
    valid_files = []
    total_rows = 0

    logger.info("=== 检查输入文件 ===")
    for i, file_path in enumerate(input_files, 1):
        p = Path(file_path)
        if not p.exists():
            logger.error(f"[{i}] 文件不存在: {file_path}")
            continue

        try:
            # 只读取元数据，不加载实际数据
            parquet_file = pq.ParquetFile(file_path)
            rows = parquet_file.metadata.num_rows
            size_mb = p.stat().st_size / 1024 / 1024
            total_rows += rows
            valid_files.append(file_path)
            logger.info(f"[{i}] {p.name}: {rows:,} 行, {size_mb:.1f} MB")
        except Exception as e:
            logger.error(f"[{i}] 读取失败 {file_path}: {e}")
            continue

    if not valid_files:
        logger.error("没有有效的输入文件")
        return False

    logger.info(f"\n总计: {len(valid_files)} 个文件, {total_rows:,} 行")

    if dry_run:
        logger.info(f"\n[DRY RUN] 将输出到: {output_file}")
        return True

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

    # 合并文件（流式写入 + 分批读取）
    logger.info(f"\n=== 开始合并（流式写入 + 分批读取）===")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        writer = None
        total_rows_written = 0
        batch_size = 500000  # 每批读取 50 万行，减少内存占用

        for i, file_path in enumerate(valid_files, 1):
            logger.info(f"[{i}/{len(valid_files)}] 处理 {Path(file_path).name}")

            # 打开 parquet 文件
            parquet_file = pq.ParquetFile(file_path)
            file_rows = 0

            # 第一次创建 writer（需要读取第一批数据获取 schema）
            if writer is None:
                # 创建迭代器
                batch_iter = parquet_file.iter_batches(batch_size=batch_size)
                # 读取第一批获取 schema
                first_batch = next(batch_iter)
                target_schema = first_batch.schema
                writer = pq.ParquetWriter(output_file, target_schema, compression='snappy')
                writer.write_batch(first_batch)
                file_rows += len(first_batch)
                total_rows_written += len(first_batch)
                logger.info(f"  已写入第 1 批: {len(first_batch):,} 行")

                # 继续处理剩余批次（使用同一个迭代器）
                batch_num = 2
                for batch in batch_iter:
                    writer.write_batch(batch)
                    file_rows += len(batch)
                    total_rows_written += len(batch)
                    logger.info(f"  已写入第 {batch_num} 批: {len(batch):,} 行（累计 {total_rows_written:,} 行）")
                    batch_num += 1
            else:
                # 后续文件：统一 schema 后分批写入
                batch_num = 1
                for batch in parquet_file.iter_batches(batch_size=batch_size):
                    # 将 batch 转换为目标 schema
                    table = pa.Table.from_batches([batch])
                    # 尝试转换到目标 schema（会自动处理类型转换）
                    try:
                        table = table.cast(target_schema)
                    except Exception as e:
                        # 如果自动转换失败，使用 pandas 转换
                        import pandas as pd
                        df = table.to_pandas()
                        # 转换类型
                        for field in target_schema:
                            if field.name in df.columns:
                                if pa.types.is_string(field.type):
                                    df[field.name] = df[field.name].astype(str)
                                elif pa.types.is_integer(field.type):
                                    df[field.name] = pd.to_numeric(df[field.name], errors='coerce').fillna(0).astype('int64')
                        table = pa.Table.from_pandas(df, schema=target_schema)

                    batch = table.to_batches()[0]
                    writer.write_batch(batch)
                    file_rows += len(batch)
                    total_rows_written += len(batch)
                    if batch_num % 10 == 0 or len(batch) < batch_size:  # 每 10 批或最后一批输出
                        logger.info(f"  已写入第 {batch_num} 批: {len(batch):,} 行（累计 {total_rows_written:,} 行）")
                    batch_num += 1

            logger.info(f"  ✓ 文件完成，共 {file_rows:,} 行")

        # 关闭 writer
        if writer:
            writer.close()

        output_size_mb = output_path.stat().st_size / 1024 / 1024
        logger.info(f"\n=== 合并完成 ===")
        logger.info(f"输出文件: {output_file}")
        logger.info(f"总行数: {total_rows_written:,}")
        logger.info(f"文件大小: {output_size_mb:.1f} MB")

        return True

    except Exception as e:
        logger.error(f"合并失败: {e}")
        if writer:
            writer.close()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='合并多个 parquet 文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 合并三个文件
  python scripts/merge_parquet.py \\
    data/dataset/orderfilled.parquet \\
    data/dataset/orderfilled_session_*.parquet \\
    data/dataset/orderfilled_refetched_*.parquet \\
    -o data/dataset/orderfilled_merged.parquet

  # 先查看信息不实际合并
  python scripts/merge_parquet.py file1.parquet file2.parquet -o output.parquet --dry-run
        """
    )

    parser.add_argument(
        'input_files',
        nargs='+',
        help='输入 parquet 文件（按顺序合并）'
    )

    parser.add_argument(
        '-o', '--output',
        required=True,
        help='输出文件路径'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='只显示信息，不实际合并'
    )

    parser.add_argument(
        '--log-file',
        help='日志文件路径（用于 nohup 运行）'
    )

    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='自动确认覆盖，不询问（用于 nohup 运行）'
    )

    args = parser.parse_args()

    # 如果指定了日志文件，重新配置 logging
    if args.log_file:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(args.log_file),
                logging.StreamHandler()  # 同时输出到终端
            ],
            force=True
        )

    # 展开 glob pattern
    import glob
    input_files = []
    for pattern in args.input_files:
        matched = glob.glob(pattern)
        if matched:
            input_files.extend(sorted(matched))
        else:
            # 不是 pattern，直接添加
            input_files.append(pattern)

    if not input_files:
        logger.error("没有输入文件")
        sys.exit(1)

    success = merge_parquet_files(input_files, args.output, args.dry_run, args.yes)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
