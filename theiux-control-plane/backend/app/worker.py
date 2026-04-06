import threading
import time

from rq import Worker

from app.config import settings
from app.queue import redis_conn


def _heartbeat_loop() -> None:
    while True:
        ttl = max(settings.circuit_worker_lag_seconds * 2, 120) if settings.circuit_worker_lag_seconds else 300
        redis_conn.set('cp:worker:heartbeat', str(time.time()), ex=ttl)
        time.sleep(30)


if __name__ == '__main__':
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    Worker(['deployments'], connection=redis_conn).work(with_scheduler=False)
