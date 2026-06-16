"""Run the RQ worker that processes deferred document parsing jobs.

Start from the project root:

    python -m app.workers.document_processing_worker
"""

from __future__ import annotations

from loguru import logger

from app.config import config


def main() -> None:
    try:
        from redis import Redis
        from rq import Queue, Worker
    except ImportError as exc:
        raise RuntimeError("缺少 RQ/Redis 依赖，请先安装项目依赖") from exc

    redis_conn = Redis.from_url(config.document_processing_redis_url)
    queue = Queue(config.document_processing_queue_name, connection=redis_conn)
    logger.info(
        "启动文档处理 RQ worker: queue={}, redis={}",
        config.document_processing_queue_name,
        config.document_processing_redis_url,
    )
    Worker([queue], connection=redis_conn).work()


if __name__ == "__main__":
    main()
