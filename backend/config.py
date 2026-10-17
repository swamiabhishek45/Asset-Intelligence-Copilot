import os
from pathlib import Path
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

    # Benchmark reference date ("Today" is 16 Oct 2026 per evaluation guide)
    BENCHMARK_TODAY: str = "2026-10-16"
    SAMPLE_DATA_PATH: str = str(
        (Path(__file__).resolve().parent.parent / "sample-data")
        if (Path(__file__).resolve().parent.parent / "sample-data").exists()
        else (Path(__file__).resolve().parent.parent.parent / "flytbase-ahc-swe-asset-intelligence-dataset" / "sample-data")
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
