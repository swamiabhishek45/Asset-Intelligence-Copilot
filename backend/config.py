import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database configurations
    POSTGRES_DSN: str = "postgresql://aic_user:aic_password@localhost:5432/asset_intelligence"
    SQLITE_PATH: str = str(Path(__file__).resolve().parent.parent / "asset_intelligence.db")
    USE_SQLITE_FALLBACK: bool = True

    # Graph & Cache
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "aic_graph_password"
    REDIS_URL: str = "redis://localhost:6379/0"

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
    SAMPLE_DATA_PATH: str = str(
        (Path(__file__).resolve().parent.parent / "sample-data")
        if (Path(__file__).resolve().parent.parent / "sample-data").exists()
        else (Path(__file__).resolve().parent.parent.parent / "flytbase-ahc-swe-asset-intelligence-dataset" / "sample-data")
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

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

