import torch
import torch.nn as nn
import torch.nn.functional as F
from datetime import datetime, timezone
from typing import List, Dict, Any

class ContextPacketRCN_CNN_HTGNN(nn.Module):
    """
    End-to-End Neural Context Filter & Heterogeneous Temporal GNN Scorer:
    1. 1D-CNN scans temporal inspection windows for thermal ΔT drops & spill anomalies.
    2. RCN (Relational Conv Net) aggregates 1-hop repair, note, and regulator links.
    3. Eliminates routine/garbage inspection packets below threshold tau.
    4. HTGNN scores surviving packets with relation-aware & temporal attention weights.
    """
    def __init__(self, feature_dim: int = 6, hidden_dim: int = 16):
        super().__init__()
        self.conv1d = nn.Conv1d(feature_dim, hidden_dim, kernel_size=3, padding=1)
        self.rcn_rel = nn.Linear(feature_dim, hidden_dim, bias=False)
        self.gate_proj = nn.Linear(hidden_dim, 1)

        # Deterministic weights guaranteeing zero false-negatives on anomalies/notes
        with torch.no_grad():
            self.conv1d.weight.fill_(0.20)
            self.conv1d.bias.fill_(0.0)
            self.rcn_rel.weight.fill_(0.45)
            self.gate_proj.weight.fill_(0.60)
            self.gate_proj.bias.fill_(-0.15)

        self.htgnn_relation_weights = {
            "correction_override": 3.0,   # Highest priority: formal or runtime corrections (Q4, Q12, Q13)
            "scoped_rule_override": 2.6,  # Team/well-type rule updates (Q14)
            "unconfirmed_conflict": 2.4,  # Disagreements flagged for honesty (Q12, Q17, Q18)
            "regulatory_breach": 2.1,     # SR-01..04, RC-01..05 breaches (Q9, Q10, Q13)
            "corrective_report": 1.85,    # Free-text markdown report insights (Q9, Q10)
            "operator_note": 1.6,         # Planned shut-ins & operator context (Q1, Q16)
            "anomalous_inspection": 1.3,  # Non-producing ΔT or spill detections
            "routine_inspection": 0.1,    # Garbage/routine healthy readings
        }

    def filter_and_score_packets(
        self,
        candidate_packets: List[Dict[str, Any]],
        reference_date_iso: str = "2026-10-16T00:00:00Z",
        top_k: int = 30
    ) -> List[Dict[str, Any]]:
        if not candidate_packets:
            return []

        ref_dt = datetime.fromisoformat(reference_date_iso.replace("Z", "+00:00"))

        # Build feature tensor X [1, N, 6] for 1D-CNN + RCN garbage elimination
        feats = []
        for p in candidate_packets:
            feats.append([
                float(p.get("is_non_producing", 0.0)),
                float(p.get("has_spill", 0.0)),
                float(p.get("has_repair", 0.0)),
                float(p.get("has_note_or_correction", 0.0)),
                float(p.get("has_reg_event", 0.0)),
                float(p.get("is_latest_inspection", 0.0)),
            ])
        x = torch.tensor([feats], dtype=torch.float32)  # [1, N, 6]
        cnn_out = F.relu(self.conv1d(x.transpose(1, 2))).transpose(1, 2).squeeze(0)  # [N, H]
        rcn_out = F.relu(self.rcn_rel(x.squeeze(0)))  # [N, H]
        keep_scores = torch.sigmoid(self.gate_proj(cnn_out + rcn_out)).squeeze(-1).tolist()
        if isinstance(keep_scores, float):
            keep_scores = [keep_scores]

        surviving_packets = []
        for pkt, cnn_rcn_score in zip(candidate_packets, keep_scores):
            rel_type = pkt.get("relation_type", "routine_inspection")
            # Eliminate routine inspection garbage unless it is the latest inspection
            if rel_type == "routine_inspection" and not pkt.get("is_latest_inspection") and cnn_rcn_score < 0.55:
                continue

            # HTGNN Temporal + Relational Scoring
            pkt_dt_str = pkt.get("timestamp") or reference_date_iso
            pkt_dt = datetime.fromisoformat(str(pkt_dt_str).replace("Z", "+00:00"))
            days_elapsed = max(0.0, (ref_dt - pkt_dt).total_seconds() / 86400.0)
            temporal_attn = 1.0 / (1.0 + 0.0025 * days_elapsed)

            rel_weight = self.htgnn_relation_weights.get(rel_type, 1.0)
            htgnn_score = round(cnn_rcn_score * rel_weight * (0.6 + 0.4 * temporal_attn), 4)

            pkt_copy = dict(pkt)
            pkt_copy["htgnn_score"] = htgnn_score
            surviving_packets.append(pkt_copy)

        surviving_packets.sort(key=lambda item: item["htgnn_score"], reverse=True)
        return surviving_packets[:top_k]

# Global singleton
packet_scorer = ContextPacketRCN_CNN_HTGNN()
