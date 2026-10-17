import json
import hashlib
import time
import socket
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger(__name__)

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

class CacheService:
    """
    Unified Caching & Job Tracking Service.
    Uses Redis when reachable; falls back to thread-safe in-memory storage.
    Reports active backend ('redis' or 'memory').
    """
    def __init__(self, redis_url: str = settings.REDIS_URL):
        self.redis_url = redis_url
        self._redis_client: Optional[Any] = None
        self._redis_checked = False
        self._redis_available = False
        self._memory_cache: Dict[str, Dict[str, Any]] = {}  # key -> {val, expiry}
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._user_sessions: Dict[str, Dict[str, Any]] = {}

    def _get_client(self):
        if self._redis_checked:
            return self._redis_client if self._redis_available else None

        self._redis_checked = True
        if not HAS_REDIS:
            self._redis_available = False
            return None

        try:
            parsed = urlparse(self.redis_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 6379

            # Quick TCP ping to avoid blocking if Redis is not running
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect((host, port))

            client = redis.from_url(self.redis_url, decode_responses=True, socket_timeout=1.0)
            client.ping()
            self._redis_client = client
            self._redis_available = True
            logger.info(f"Connected to Redis cache at {host}:{port}")
            return self._redis_client
        except Exception as e:
            logger.info(f"Redis not available ({e}). Using in-memory fallback cache.")
            self._redis_available = False
            self._redis_client = None
            return None

    def get_backend_name(self) -> str:
        client = self._get_client()
        return "redis" if client is not None else "memory"

    @staticmethod
    def compute_query_key(question: str, user_id: str, data_version: str) -> str:
        raw = f"{question.strip().lower()}:{user_id.strip()}:{data_version}"
        return f"query:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def get_cached_query(self, question: str, user_id: str, data_version: str) -> Optional[Dict[str, Any]]:
        key = self.compute_query_key(question, user_id, data_version)
        client = self._get_client()
        if client:
            try:
                data = client.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
        else:
            item = self._memory_cache.get(key)
            if item:
                if item["expiry"] > time.time():
                    return item["val"]
                else:
                    self._memory_cache.pop(key, None)
        return None

    def set_cached_query(self, question: str, user_id: str, data_version: str, response: Dict[str, Any], ttl_seconds: int = 300) -> None:
        key = self.compute_query_key(question, user_id, data_version)
        client = self._get_client()
        if client:
            try:
                client.setex(key, ttl_seconds, json.dumps(response))
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
        else:
            self._memory_cache[key] = {
                "val": response,
                "expiry": time.time() + ttl_seconds
            }

    def invalidate_all_queries(self) -> None:
        client = self._get_client()
        if client:
            try:
                keys = client.keys("query:*")
                if keys:
                    client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis invalidate error: {e}")
        self._memory_cache.clear()

    # Session Context Management
    def get_session_context(self, user_id: str) -> Dict[str, Any]:
        key = f"session:{user_id}"
        client = self._get_client()
        if client:
            try:
                data = client.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis session get error: {e}")
        return self._user_sessions.get(user_id, {})

    def set_session_context(self, user_id: str, context: Dict[str, Any], ttl_seconds: int = 86400) -> None:
        key = f"session:{user_id}"
        client = self._get_client()
        if client:
            try:
                client.setex(key, ttl_seconds, json.dumps(context))
            except Exception as e:
                logger.warning(f"Redis session set error: {e}")
        self._user_sessions[user_id] = context

    # Ingest Job Tracking
    def create_job(self, job_id: str, dataset_path: str, status: str = "queued") -> Dict[str, Any]:
        job_info = {
            "job_id": job_id,
            "dataset_path": dataset_path,
            "status": status,
            "started_at": time.time(),
            "completed_at": None,
            "duration_seconds": None,
            "counts": {},
            "errors": []
        }
        client = self._get_client()
        if client:
            try:
                client.setex(f"job:{job_id}", 86400, json.dumps(job_info))
            except Exception as e:
                logger.warning(f"Redis job set error: {e}")
        self._jobs[job_id] = job_info
        return job_info

    def update_job(
        self,
        job_id: str,
        status: str,
        counts: Optional[Dict[str, int]] = None,
        duration_seconds: Optional[float] = None,
        errors: Optional[list] = None
    ) -> Dict[str, Any]:
        job_info = self.get_job(job_id) or {
            "job_id": job_id,
            "started_at": time.time(),
        }
        job_info["status"] = status
        if counts is not None:
            job_info["counts"] = counts
        if duration_seconds is not None:
            job_info["duration_seconds"] = duration_seconds
        if errors is not None:
            job_info["errors"] = errors
        if status in ("completed", "failed"):
            job_info["completed_at"] = time.time()
            if job_info.get("started_at") and not job_info.get("duration_seconds"):
                job_info["duration_seconds"] = round(job_info["completed_at"] - job_info["started_at"], 2)

        client = self._get_client()
        if client:
            try:
                client.setex(f"job:{job_id}", 86400, json.dumps(job_info))
            except Exception as e:
                logger.warning(f"Redis job update error: {e}")
        self._jobs[job_id] = job_info
        return job_info

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        if client:
            try:
                data = client.get(f"job:{job_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis job get error: {e}")
        return self._jobs.get(job_id)

cache_service = CacheService()
