import os
import re
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database configurations
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "asset_intelligence"
    POSTGRES_USER: str = "aic_user"
    POSTGRES_PASSWORD: str = "aic_password"
    POSTGRES_DSN: str = "postgresql://aic_user:aic_password@localhost:5432/asset_intelligence"
    
    SQLITE_PATH: str = str(Path(__file__).resolve().parent.parent / "asset_intelligence.db")
    USE_SQLITE_FALLBACK: bool = True

    # Graph configurations
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "aic_graph_password"
    NEO4J_DATABASE: str = "neo4j"

    # Cache & Task Queue
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # AI & Embeddings
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    THESYS_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    
    # Gemma 4 via OpenRouter, Ollama, or Google AI Studio
    COPILOT_BASE_URL: str = "https://openrouter.ai/api/v1"
    COPILOT_API_KEY: str = ""
    COPILOT_MODEL: str = "google/gemma-4-31b-it:free"

    # Benchmark reference date ("Today" is latest inspection date or overridable by AS_OF_DATE)
    BENCHMARK_TODAY: str = "2026-10-16"
    AS_OF_DATE: Optional[str] = None
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://frontend:3000"]

    # In-memory data version counter
    DATA_VERSION: int = 1

    SAMPLE_DATA_PATH: str = str(
        (Path(__file__).resolve().parent.parent / "sample-data")
        if (Path(__file__).resolve().parent.parent / "sample-data").exists()
        else (Path(__file__).resolve().parent.parent.parent / "flytbase-ahc-swe-asset-intelligence-dataset" / "sample-data")
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Sync POSTGRES_DSN if individual components are passed in env
if "POSTGRES_HOST" in os.environ or "POSTGRES_USER" in os.environ:
    user = os.getenv("POSTGRES_USER", settings.POSTGRES_USER)
    pw = os.getenv("POSTGRES_PASSWORD", settings.POSTGRES_PASSWORD)
    host = os.getenv("POSTGRES_HOST", settings.POSTGRES_HOST)
    port = os.getenv("POSTGRES_PORT", str(settings.POSTGRES_PORT))
    db = os.getenv("POSTGRES_DB", settings.POSTGRES_DB)
    settings.POSTGRES_DSN = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

def mask_secret(val: Optional[str]) -> str:
    if not val:
        return "<not set>"
    if len(val) <= 6:
        return "***"
    return f"{val[:3]}...{val[-3:]}"

def print_masked_config():
    print("\n" + "=" * 80)
    print("FLYTEBASE ASSET INTELLIGENCE CONFIGURATION")
    print("=" * 80)
    print(f"PostgreSQL DSN:    {re.sub(r':([^/@]+)@', ':****@', settings.POSTGRES_DSN)}")
    print(f"SQLite Fallback:   {settings.SQLITE_PATH}")
    print(f"Neo4j URI:         {settings.NEO4J_URI} (User: {settings.NEO4J_USER}, DB: {settings.NEO4J_DATABASE})")
    print(f"Redis URL:         {settings.REDIS_URL}")
    print(f"Celery Broker:     {settings.CELERY_BROKER_URL}")
    print(f"OpenAI API Key:    {mask_secret(settings.OPENAI_API_KEY)}")
    print(f"Gemini API Key:    {mask_secret(settings.GEMINI_API_KEY)}")
    print(f"Thesys API Key:    {mask_secret(settings.THESYS_API_KEY)}")
    print(f"Sample Data Path:  {settings.SAMPLE_DATA_PATH}")
    print(f"Data Version:      v{settings.DATA_VERSION}")
    print("=" * 80 + "\n")

def get_as_of_date(conn=None) -> str:
    """
    Returns 'Today' dynamically:
    1. Environment variable AS_OF_DATE if set.
    2. Latest inspection date in the loaded dataset.
    3. Default to 2026-10-17 if empty.
    """
    env_date = os.getenv("AS_OF_DATE") or getattr(settings, "AS_OF_DATE", None)
    if env_date:
        return str(env_date).strip()
    try:
        if conn is not None:
            cur = conn.cursor()
            cur.execute("SELECT MAX(substr(inspected_at, 1, 10)) AS max_date FROM inspections")
            row = cur.fetchone()
            if row and row.get("max_date"):
                return str(row["max_date"])
        else:
            from backend.db.postgres import get_db_connection
            with get_db_connection() as c:
                cur = c.cursor()
                cur.execute("SELECT MAX(substr(inspected_at, 1, 10)) AS max_date FROM inspections")
                row = cur.fetchone()
                if row and row.get("max_date"):
                    return str(row["max_date"])
    except Exception:
        pass
    return "2026-10-17"
