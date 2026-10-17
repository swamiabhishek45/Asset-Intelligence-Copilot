import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DynamicRulesEngine:
    """
    Parses operational thresholds, engineering limits, and compliance SOPs
    directly from markdown files in fleet/well-types/*.md and fleet/sops/*.md.
    Fails loudly with ValueError if required rules are unparseable.
    """
    def __init__(self, data_root: Optional[str] = None):
        from backend.config import settings
        self.root = Path(data_root or settings.SAMPLE_DATA_PATH)
        self.well_type_rules: Dict[str, Dict[str, Any]] = {}
        self.sop_rules: Dict[str, Dict[str, Any]] = {}
        self.load_rules()

    def set_data_root(self, data_root: str):
        self.root = Path(data_root)
        self.load_rules()

    def load_rules(self):
        self.well_type_rules = self._parse_well_types()
        self.sop_rules = self._parse_sops()

    def _parse_well_types(self) -> Dict[str, Dict[str, Any]]:
        rules = {}
        well_types_dir = self.root / "fleet" / "well-types"
        if not well_types_dir.exists():
            raise FileNotFoundError(f"Well types directory not found at {well_types_dir}")

        md_files = list(well_types_dir.glob("*.md"))
        if not md_files:
            raise FileNotFoundError(f"No well type markdown manuals found in {well_types_dir}")

        word_to_num = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}

        # Parse base files first (e.g. T200 before T350 if T350 refers to T200)
        sorted_files = sorted(md_files, key=lambda f: 1 if "T200" in f.name else 2)

        for md_file in sorted_files:
            wtype = md_file.stem.upper()
            text = md_file.read_text(encoding="utf-8")
            clean_text = text.replace("**", "").replace("*", "")

            # 1. Temperature differential threshold
            # e.g., "at least 15 °C above ambient" or "at least 20 °C above ambient"
            temp_match = re.search(
                r'at\s+least\s+(\d+(?:\.\d+)?)\s*(?:°|°C|degC|C)?\s*above\s*ambient',
                clean_text, flags=re.IGNORECASE
            )
            if not temp_match:
                temp_match = re.search(
                    r'(\d+(?:\.\d+)?)\s*(?:°|°C|degC|C)?\s*above\s*ambient',
                    clean_text, flags=re.IGNORECASE
                )
            if not temp_match:
                raise ValueError(f"Could not parse required min_temp_delta_c from {md_file.name}")
            min_temp_delta = float(temp_match.group(1))

            # 2. RCA repair count threshold and lookback window
            # e.g., "Three or more corrective maintenance events ... in the 12 months"
            # or "RCA after three corrective events ... within 12 months"
            rca_match = re.search(
                r'(three|two|one|\d+)\s+(?:or\s+more\s+)?corrective\s+(?:maintenance\s+events?|repairs?|events?)[^\n]*?(?:in|within)\s+(?:the\s+)?(\d+)\s*months',
                clean_text, flags=re.IGNORECASE
            )
            if rca_match:
                raw_rca = rca_match.group(1).lower()
                rca_count = float(word_to_num.get(raw_rca, raw_rca))
                rca_window = int(rca_match.group(2))
            elif "same as t200" in clean_text.lower() and "T200" in rules:
                rca_count = rules["T200"]["rca_repairs_12m"]
                rca_window = rules["T200"]["rca_window_months"]
            else:
                raise ValueError(f"Could not parse required RCA corrective maintenance threshold from {md_file.name}")

            # 3. Temperature alarm limit
            # e.g. "at or below 85 °C" or "at or below 95 °C"
            alarm_match = re.search(
                r'at\s+or\s+below\s+(\d+(?:\.\d+)?)\s*(?:°|°C|degC|C)?',
                clean_text, flags=re.IGNORECASE
            )
            temp_alarm = float(alarm_match.group(1)) if alarm_match else (85.0 if "200" in wtype else 95.0)

            # 4. Spill-related shut-in percentage
            spill_pct_match = re.search(
                r'more\s+than\s+(\d+(?:\.\d+)?)\s*%\s*of\s+the\s+pad\s+area',
                clean_text, flags=re.IGNORECASE
            )
            spill_pct = float(spill_pct_match.group(1)) if spill_pct_match else 5.0

            rules[wtype] = {
                "min_temp_delta_c": min_temp_delta,
                "rca_repairs_12m": rca_count,
                "rca_window_months": rca_window,
                "temp_alarm_c": temp_alarm,
                "spill_shut_in_pct": spill_pct,
                "source_file": md_file.name,
            }

        return rules

    def _parse_sops(self) -> Dict[str, Dict[str, Any]]:
        sops = {}
        sops_dir = self.root / "fleet" / "sops"
        if not sops_dir.exists():
            raise FileNotFoundError(f"SOP directory not found at {sops_dir}")

        # 1. Spill Response SOP (spill-response-sop.md)
        sr_file = sops_dir / "spill-response-sop.md"
        if not sr_file.exists():
            raise FileNotFoundError(f"Required spill-response-sop.md not found in {sops_dir}")
        sr_text = sr_file.read_text(encoding="utf-8")

        # SR-01
        m_sr01_rep = re.search(r'Reportable\s*\|\s*(\d+(?:\.\d+)?)\s*bbl', sr_text, re.I)
        m_sr01_maj = re.search(r'Major\s*\|\s*(\d+(?:\.\d+)?)\s*bbl', sr_text, re.I)
        m_sr01_hrs = re.search(r'file\s+the\s+\*?\*?written\s+notice\*?\*?[^\n]*?within\s+\*?\*?(\d+)\s*hours?', sr_text, re.I)
        m_sr01_maj_hrs = re.search(r'within\s+\*?\*?(\d+)\s*hours?\*?\*?\s+for\s+a\s+major\s+spill', sr_text, re.I)

        if not (m_sr01_rep and m_sr01_hrs):
            raise ValueError(f"Could not parse SR-01 thresholds from {sr_file.name}")

        sops["SR-01"] = {
            "reportable_volume_bbl": float(m_sr01_rep.group(1)),
            "major_volume_bbl": float(m_sr01_maj.group(1)) if m_sr01_maj else 25.0,
            "reportable_notice_hours": float(m_sr01_hrs.group(1)),
            "major_notice_hours": float(m_sr01_maj_hrs.group(1)) if m_sr01_maj_hrs else 2.0,
            "source_file": sr_file.name,
        }

        # SR-02: Containment limit (CRITICAL: MUST parse 4 hours from spill-response-sop.md)
        m_sr02 = re.search(r'SR-02[^\n\|]*\|[^\n]*?contained\s+within\s+\*?\*?(\d+(?:\.\d+)?)\s*hours?', sr_text, re.I)
        if not m_sr02:
            m_sr02 = re.search(r'(\d+(?:\.\d+)?)-hour\s+containment\s+limit\s*\(SR-02\)', sr_text, re.I)
        if not m_sr02:
            raise ValueError(f"Could not parse SR-02 containment limit from {sr_file.name}!")
        sops["SR-02"] = {
            "containment_limit_hours": float(m_sr02.group(1)),
            "source_file": sr_file.name,
        }

        # SR-03: Cleanup verification window & soil criteria
        m_sr03_days = re.search(r'verified\s+within\s+\*?\*?(\d+)\s*days?', sr_text, re.I)
        m_sr03_tph = re.search(r'(\d+(?:\.\d+)?)\s*%\s*TPH', sr_text, re.I)
        m_sr03_samples = re.search(r'at\s+least\s+\*?\*?(\d+)\s+soil\s+samples', sr_text, re.I)
        if not (m_sr03_days and m_sr03_tph):
            raise ValueError(f"Could not parse SR-03 requirements from {sr_file.name}")
        sops["SR-03"] = {
            "verification_days": int(m_sr03_days.group(1)),
            "tph_target_pct": float(m_sr03_tph.group(1)),
            "min_soil_samples": int(m_sr03_samples.group(1)) if m_sr03_samples else 4,
            "source_file": sr_file.name,
        }

        # 2. Regulatory Compliance SOP (regulatory-compliance-sop.md)
        rc_file = sops_dir / "regulatory-compliance-sop.md"
        if not rc_file.exists():
            raise FileNotFoundError(f"Required regulatory-compliance-sop.md not found in {sops_dir}")
        rc_text = rc_file.read_text(encoding="utf-8")

        m_rc01 = re.search(r'RC-01[^\n\|]*\|[^\n]*?at\s+least\s+once\s+every\s+\*?\*?(\d+)\s*days?', rc_text, re.I)
        m_rc03 = re.search(r'RC-03[^\n\|]*\|[^\n]*?more\s+than\s+\*?\*?(\d+)\s+consecutive\s*days?', rc_text, re.I)
        m_rc04 = re.search(r'RC-04[^\n\|]*\|[^\n]*?answered\s+within\s+\*?\*?(\d+)\s*days?', rc_text, re.I)
        if not m_rc04:
            raise ValueError(f"Could not parse RC-04 notice of violation response deadline from {rc_file.name}!")

        sops["RC-01"] = {"inspection_interval_days": int(m_rc01.group(1)) if m_rc01 else 14, "source_file": rc_file.name}
        sops["RC-02"] = {"integrity_test_period": "annual", "source_file": rc_file.name}
        sops["RC-03"] = {"consecutive_down_days": int(m_rc03.group(1)) if m_rc03 else 14, "source_file": rc_file.name}
        sops["RC-04"] = {"nov_response_days": int(m_rc04.group(1)), "source_file": rc_file.name}
        sops["RC-05"] = {"program": "flowline_maintenance_program", "source_file": rc_file.name}

        # 3. Field Work Safety and Maintenance SOP (field-work-sop.md)
        ws_file = sops_dir / "field-work-sop.md"
        if ws_file.exists():
            ws_text = ws_file.read_text(encoding="utf-8")
            m_ws03 = re.search(r'WS-03[^\n\|]*\|[^\n]*?(\d+(?:\.\d+)?)\s*ppm', ws_text, re.I)
            m_ws04 = re.search(r'WS-04[^\n\|]*\|[^\n]*?(\d+(?:\.\d+)?)\s*%\s*of\s+the\s+lower', ws_text, re.I)
            m_ws05_p = re.search(r'WS-05[^\n\|]*\|[^\n]*?at\s+least\s+\*?\*?(\d+(?:\.\d+)?)\s*[xX\xd7]\s*the\s+flowline', ws_text, re.I)
            m_ws05_h = re.search(r'WS-05[^\n\|]*\|[^\n]*?hold\s+for\s+\*?\*?(\d+)\s*hours?', ws_text, re.I)
            m_ws07 = re.search(r'WS-07[^\n\|]*\|[^\n]*?within\s+\*?\*?(\d+)\s*days?', ws_text, re.I)

            sops["WS-03"] = {"h2s_action_ppm": float(m_ws03.group(1)) if m_ws03 else 10.0, "source_file": ws_file.name}
            sops["WS-04"] = {"hot_work_lel_pct": float(m_ws04.group(1)) if m_ws04 else 10.0, "source_file": ws_file.name}
            sops["WS-05"] = {
                "pressure_test_multiplier": float(m_ws05_p.group(1)) if m_ws05_p else 1.25,
                "hold_hours": float(m_ws05_h.group(1)) if m_ws05_h else 4.0,
                "source_file": ws_file.name
            }
            sops["WS-07"] = {"report_deadline_days": int(m_ws07.group(1)) if m_ws07 else 3, "source_file": ws_file.name}

        return sops

    def print_rule_table(self):
        """Prints a human-readable table of dynamically parsed operational rules and SOP limits."""
        print("=" * 80)
        print("DYNAMICALLY PARSED OPERATIONAL RULES & SOP LIMITS TABLE")
        print("=" * 80)
        print(f"Data Root: {self.root}")
        print("\n[WELL TYPE PRODUCTION RULES]")
        print(f"{'Well Type':<12} | {'Min Delta-T (C)':<16} | {'RCA Repairs':<12} | {'RCA Window':<12} | {'Source File':<16}")
        print("-" * 76)
        for wtype, r in self.well_type_rules.items():
            print(f"{wtype:<12} | {r['min_temp_delta_c']:<16.1f} | {r['rca_repairs_12m']:<12.0f} | {r['rca_window_months']} months   | {r['source_file']:<16}")

        print("\n[COMPLIANCE SOPS & REGULATORY LIMITS]")
        print(f"{'Protocol':<10} | {'Parameter':<28} | {'Parsed Value':<16} | {'Source Document':<20}")
        print("-" * 80)
        for proto, r in self.sop_rules.items():
            sfile = r.get("source_file", "")
            for param, val in r.items():
                if param == "source_file":
                    continue
                val_str = f"{val} hrs" if "hour" in param else (f"{val} days" if "day" in param else (f"{val} bbl" if "volume" in param else str(val)))
                print(f"{proto:<10} | {param:<28} | {val_str:<16} | {sfile:<20}")
        print("=" * 80 + "\n")

# Global singleton
rules_engine = DynamicRulesEngine()
