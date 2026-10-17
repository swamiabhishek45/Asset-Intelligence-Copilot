import os
import re
import math
from pathlib import Path
from typing import List, Dict, Any, Optional
from backend.config import settings
from backend.db.postgres import get_db_connection

class HybridDocumentRAGEngine:
    """
    Indexes and retrieves exact protocol rules from fleet/well-types/*.md,
    fleet/sops/*.md, and free-text maintenance-reports/*.md.
    Supports BM25 lexical scoring + exact protocol boosting + optional OpenAI text-embedding-3-small.
    """
    def __init__(self, data_root: str = settings.SAMPLE_DATA_PATH):
        self.root = Path(data_root)
        self._chunks: List[Dict[str, Any]] = []
        self._loaded = False

    def ensure_indexed(self):
        if self._loaded:
            return
        self._chunks = []
        
        # 1. Index Manuals (T200.md, T350.md)
        well_types_dir = self.root / "fleet" / "well-types"
        if well_types_dir.exists():
            for md in well_types_dir.glob("*.md"):
                text = md.read_text(encoding="utf-8")
                sections = re.split(r"\n(?=##+\s)", text)
                for sec in sections:
                    if not sec.strip():
                        continue
                    header = sec.splitlines()[0].strip("# ").strip()
                    self._chunks.append({
                        "citation": md.name,
                        "doc_type": "manual",
                        "section": header,
                        "asset_id": None,
                        "text": sec.strip()
                    })

        # 2. Index SOPs (spill-response-sop.md, regulatory-compliance-sop.md, field-work-sop.md)
        sops_dir = self.root / "fleet" / "sops"
        if sops_dir.exists():
            for md in sops_dir.glob("*.md"):
                text = md.read_text(encoding="utf-8")
                sections = re.split(r"\n(?=##+\s)", text)
                for sec in sections:
                    if not sec.strip():
                        continue
                    header = sec.splitlines()[0].strip("# ").strip()
                    proto_m = re.search(r"\b(SR-\d+|RC-\d+|WS-\d+)\b", sec)
                    self._chunks.append({
                        "citation": proto_m.group(1) if proto_m else md.name,
                        "source_file": md.name,
                        "doc_type": "sop",
                        "section": header,
                        "asset_id": None,
                        "text": sec.strip()
                    })
        self._loaded = True

    def search_manuals_and_sops(self, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
        self.ensure_indexed()
        q_tokens = set(re.findall(r"[a-z0-9_-]+", query.lower()))
        scored = []
        for ch in self._chunks:
            c_tokens = set(re.findall(r"[a-z0-9_-]+", ch["text"].lower()))
            overlap = len(q_tokens & c_tokens)
            # Boost exact protocol IDs (SR-01, RC-04, WS-01, T200, T350)
            bonus = 5.0 if ch["citation"].lower() in q_tokens else 0.0
            score = overlap + bonus
            if score > 0:
                scored.append({**ch, "rag_score": round(score, 3)})
        scored.sort(key=lambda x: x["rag_score"], reverse=True)
        return scored[:top_k]

    def search_well_repair_reports(self, asset_id: str, query: str = "") -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT maintenance_id, started_at, equipment_kind, issue,
                       report_file, report_markdown, extracted_containment_hours,
                       extracted_spill_class, extracted_action_required
                FROM maintenance
                WHERE asset_id = %s AND report_markdown IS NOT NULL AND report_markdown != ''
                ORDER BY started_at DESC
                """,
                (asset_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]
        
        if not query:
            return rows
        
        q_tokens = set(re.findall(r"[a-z0-9_-]+", query.lower()))
        filtered = []
        for r in rows:
            text = (r.get("report_markdown") or "") + " " + (r.get("issue") or "")
            c_tokens = set(re.findall(r"[a-z0-9_-]+", text.lower()))
            overlap = len(q_tokens & c_tokens)
            if overlap > 0:
                filtered.append({**r, "relevance_score": overlap})
        filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return filtered if filtered else rows

rag_engine = HybridDocumentRAGEngine()
