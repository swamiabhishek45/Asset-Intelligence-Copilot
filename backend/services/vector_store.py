import os
import re
import json
import math
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from backend.config import settings
from backend.db.postgres import get_db_connection

def deterministic_local_embedding(text_content: str, dim: int = 1536) -> List[float]:
    """
    Generates a deterministic 1536-dimensional normalized embedding vector
    using multi-hash character/token n-gram projections.
    Provides an offline fallback when OpenAI API key is unavailable or network is offline.
    """
    vec = [0.0] * dim
    words = re.findall(r'\b\w+\b', text_content.lower())
    if not words:
        return vec
    
    for i, w in enumerate(words):
        # Unigram hash
        h1 = int(hashlib.md5(w.encode('utf-8')).hexdigest()[:8], 16) % dim
        vec[h1] += 1.0
        # Bigram hash
        if i > 0:
            bi = f"{words[i-1]}_{w}"
            h2 = int(hashlib.sha256(bi.encode('utf-8')).hexdigest()[:8], 16) % dim
            vec[h2] += 1.5

    # Normalize vector to unit length
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [round(v / norm, 6) for v in vec]
    return vec

def get_embedding(text_content: str) -> List[float]:
    """Generates embedding via OpenAI text-embedding-3-small or falls back to local vector."""
    if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=text_content
            )
            return resp.data[0].embedding
        except Exception:
            pass
    return deterministic_local_embedding(text_content)

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

class VectorStoreService:
    """Manages document chunking, embeddings storage, and vector retrieval."""
    
    def chunk_document(self, file_path: Path, doc_type: str) -> List[Dict[str, Any]]:
        if not file_path.exists():
            return []
        text = file_path.read_text(encoding="utf-8")
        chunks = []
        doc_id = file_path.stem

        # Split by Markdown headers (## or #)
        sections = re.split(r'\n(?=#{1,3}\s+)', text)
        for idx, sec in enumerate(sections):
            clean_sec = sec.strip()
            if not clean_sec:
                continue
            first_line = clean_sec.split('\n')[0]
            sec_title = first_line.lstrip('#').strip() if first_line.startswith('#') else f"Section {idx+1}"
            chunks.append({
                "doc_id": doc_id,
                "doc_type": doc_type,
                "file_path": str(file_path),
                "section_title": sec_title,
                "chunk_text": clean_sec
            })
        return chunks

    def index_all_documents(self, data_root: str = settings.SAMPLE_DATA_PATH) -> int:
        root = Path(data_root)
        all_chunks = []

        # 1. fleet/well-types/*.md
        well_types_dir = root / "fleet" / "well-types"
        if well_types_dir.exists():
            for f in well_types_dir.glob("*.md"):
                all_chunks.extend(self.chunk_document(f, "manual"))

        # 2. fleet/sops/*.md
        sops_dir = root / "fleet" / "sops"
        if sops_dir.exists():
            for f in sops_dir.glob("*.md"):
                all_chunks.extend(self.chunk_document(f, "sop"))

        # 3. reports/*.md across assets or in maintenance-reports
        reports_dir = root / "maintenance-reports"
        if reports_dir.exists():
            for f in reports_dir.glob("*.md"):
                all_chunks.extend(self.chunk_document(f, "maintenance_report"))

        # Also search asset subdirectories for reports
        assets_dir = root / "assets"
        if assets_dir.exists():
            for f in assets_dir.glob("*/reports/*.md"):
                all_chunks.extend(self.chunk_document(f, "maintenance_report"))

        if not all_chunks:
            return 0

        with get_db_connection() as conn:
            cur = conn.cursor()
            # Clear previous embeddings
            cur.execute("DELETE FROM document_embeddings")
            
            for chk in all_chunks:
                emb = get_embedding(chk["chunk_text"][:2000])
                emb_val = json.dumps(emb) if conn.is_sqlite else f"[{','.join(str(x) for x in emb)}]"
                cur.execute(
                    """
                    INSERT INTO document_embeddings (doc_id, doc_type, file_path, section_title, chunk_text, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (chk["doc_id"], chk["doc_type"], chk["file_path"], chk["section_title"], chk["chunk_text"], emb_val)
                )
            conn.commit()
        return len(all_chunks)

    def search_documents(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        query_emb = get_embedding(query)
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, doc_id, doc_type, file_path, section_title, chunk_text, embedding FROM document_embeddings")
            rows = cur.fetchall()

        if not rows:
            return []

        scored = []
        for r in rows:
            raw_emb = r.get("embedding")
            if not raw_emb:
                continue
            if isinstance(raw_emb, str):
                try:
                    vec = json.loads(raw_emb) if raw_emb.startswith("[") else [float(x) for x in raw_emb.strip("[]").split(",")]
                except Exception:
                    continue
            else:
                vec = raw_emb

            sim = cosine_similarity(query_emb, vec)
            fname = Path(r["file_path"]).name
            sec = r.get("section_title") or "General"
            scored.append({
                "doc_id": r["doc_id"],
                "doc_type": r["doc_type"],
                "file_path": r["file_path"],
                "section_title": sec,
                "chunk_text": r["chunk_text"],
                "citation": f"{fname} (Section: {sec})",
                "similarity": round(sim, 4)
            })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def count_chunks(self) -> int:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS c FROM document_embeddings")
                row = cur.fetchone()
                return int(row["c"]) if row else 0
        except Exception:
            return 0

    index_documents = index_all_documents

vector_store = VectorStoreService()
