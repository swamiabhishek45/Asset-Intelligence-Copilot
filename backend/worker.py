import logging
from backend.ingest.celery_worker import celery_app

logger = logging.getLogger(__name__)

app = celery_app

if __name__ == "__main__":
    if celery_app:
        celery_app.start()
    else:
        logger.error("Celery is not available in current environment.")
