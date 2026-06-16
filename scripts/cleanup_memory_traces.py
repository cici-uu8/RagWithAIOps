#!/usr/bin/env python3
"""
Memory Trace 清理脚本

清理过期的 shadow mode trace 文件，避免磁盘占用过大。
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from loguru import logger


def find_trace_files(trace_dir: Path) -> List[Path]:
    """
    查找所有 trace 文件

    Args:
        trace_dir: trace 目录

    Returns:
        trace 文件路径列表
    """
    if not trace_dir.exists():
        logger.warning(f"Trace 目录不存在: {trace_dir}")
        return []

    return list(trace_dir.glob("mem_trace_*.txt"))


def parse_trace_timestamp(file_path: Path) -> datetime:
    """
    从文件名解析时间戳

    Args:
        file_path: trace 文件路径

    Returns:
        时间戳

    Raises:
        ValueError: 无法解析时间戳
    """
    # 文件名格式: mem_trace_20260526_143022.txt
    stem = file_path.stem  # mem_trace_20260526_143022
    parts = stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"无法解析文件名: {file_path.name}")

    date_str = parts[2]  # 20260526
    time_str = parts[3]  # 143022

    return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")


def cleanup_traces(
    trace_dir: Path,
    retention_days: int,
    dry_run: bool = False
) -> tuple[int, int]:
    """
    清理过期的 trace 文件

    Args:
        trace_dir: trace 目录
        retention_days: 保留天数
        dry_run: 是否为试运行（不实际删除）

    Returns:
        (删除文件数, 保留文件数)
    """
    cutoff_time = datetime.now() - timedelta(days=retention_days)
    trace_files = find_trace_files(trace_dir)

    deleted_count = 0
    kept_count = 0
    parse_error_count = 0

    for file_path in trace_files:
        try:
            file_time = parse_trace_timestamp(file_path)

            if file_time < cutoff_time:
                if dry_run:
                    logger.info(f"[DRY-RUN] 将删除: {file_path.name} (时间: {file_time})")
                else:
                    file_path.unlink()
                    logger.info(f"已删除: {file_path.name} (时间: {file_time})")
                deleted_count += 1
            else:
                logger.debug(f"保留: {file_path.name} (时间: {file_time})")
                kept_count += 1

        except ValueError as e:
            logger.warning(f"跳过无法解析的文件: {file_path.name} - {e}")
            parse_error_count += 1
            kept_count += 1

    logger.info(
        f"清理完成: 删除 {deleted_count} 个文件, 保留 {kept_count} 个文件, "
        f"解析错误 {parse_error_count} 个文件"
    )

    return deleted_count, kept_count


def main():
    parser = argparse.ArgumentParser(
        description="清理过期的 memory trace 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 清理 7 天前的 trace（试运行）
  python scripts/cleanup_memory_traces.py --dry-run

  # 实际清理 7 天前的 trace
  python scripts/cleanup_memory_traces.py

  # 清理 30 天前的 trace
  python scripts/cleanup_memory_traces.py --retention-days 30

  # 指定自定义 trace 目录
  python scripts/cleanup_memory_traces.py --trace-dir /path/to/traces
        """
    )

    parser.add_argument(
        "--trace-dir",
        type=str,
        default="traces/memory",
        help="Trace 文件目录 (默认: traces/memory)"
    )

    parser.add_argument(
        "--retention-days",
        type=int,
        default=7,
        help="保留天数 (默认: 7)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行，不实际删除文件"
    )

    args = parser.parse_args()

    trace_dir = Path(args.trace_dir)
    logger.info(f"开始清理 trace 文件: 目录={trace_dir}, 保留天数={args.retention_days}, 试运行={args.dry_run}")

    deleted, kept = cleanup_traces(
        trace_dir=trace_dir,
        retention_days=args.retention_days,
        dry_run=args.dry_run
    )

    if args.dry_run:
        logger.info("试运行完成，未实际删除文件")
    else:
        logger.info(f"清理完成: 删除 {deleted} 个文件, 保留 {kept} 个文件")

    return 0


if __name__ == "__main__":
    sys.exit(main())
