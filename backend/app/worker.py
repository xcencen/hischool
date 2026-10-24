"""RQ worker for the future knowledge ingestion queue (Linux container)."""

from redis import Redis
from rq import Worker


def main() -> None:
    from app.config import load_settings
    from app.knowledge.logging import configure_knowledge_logging

    configure_knowledge_logging()
    settings = load_settings()
    connection = Redis.from_url(settings.redis_url, socket_connect_timeout=5)
    try:
        Worker(["knowledge"], connection=connection).work()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
