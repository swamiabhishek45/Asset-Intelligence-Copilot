import os
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

class DatasetParser:
    def __init__(self, data_root: str):
        self.root = Path(data_root)

    def parse_well_type_manuals(self) -> Dict[str, Dict[str, float]]:
        """
        Dynamically extracts temperature differential threshold (wellhead_temp_c - ambient_temp_c)
        and RCA corrective repair threshold from fleet/well-types/*.md.
        """
        word_to_num = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}
        rules = {
            "T200": {"min_temp_delta_c": 15.0, "rca_repairs_12m": 3.0},
            "T350": {"min_temp_delta_c": 20.0, "rca_repairs_12m": 3.0},
        }
        well_types_dir = self.root / "fleet" / "well-types"
        if not well_types_dir.exists():
            return rules

        for md_file in well_types_dir.glob("*.md"):
            wtype = md_file.stem.upper()
            text = md_file.read_text(encoding="utf-8")
            clean_text = text.replace("**", "").replace("*", "")

            # 1. Temperature differential threshold (e.g., "15 °C above ambient" or "at least 20 °C above ambient")
            temp_match = re.search(
                r'(\d+(?:\.\d+)?)\s*(?:°|\xc2\xb0)?C\s*above\s*ambient',
                clean_text, flags=re.IGNORECASE
            )
            if not temp_match:
                temp_match = re.search(
                    r'(?:at least|minimum of|exceeds?|warmer by|threshold[^\d]{0,25})\s*(\d+(?:\.\d+)?)\s*(?:°|\xc2\xb0)?C',
                    clean_text, flags=re.IGNORECASE
                )
            if temp_match:
                rules.setdefault(wtype, {})["min_temp_delta_c"] = float(temp_match.group(1))

            # 2. RCA repair count threshold (e.g., "three or more corrective maintenance events" or "3 repairs in 12 months")
            rca_match = re.search(
                r'(three|two|one|\d+)\s+(?:or\s+more\s+)?corrective\s+(?:maintenance\s+events?|repairs?|events?)',
                clean_text, flags=re.IGNORECASE
            )
            if rca_match:
                raw_rca = rca_match.group(1).lower()
                rules.setdefault(wtype, {})["rca_repairs_12m"] = float(word_to_num.get(raw_rca, raw_rca))

        return rules

    def parse_maintenance_report_md(self, well_dir: Path, report_rel_path: Optional[str]) -> Dict[str, Any]:
        """
        Extracts hidden facts that live in free-text maintenance-reports/*.md:
        1. Containment duration in hours (e.g., 'contained after 7.1 hours' for Q9, Q10, Q13)
        2. Spill classification ('minor', 'moderate', 'reportable', 'major')
        3. Compliance / RCA 'Action required' flags
        """
        result = {
            "report_markdown": "",
            "extracted_containment_hours": None,
            "extracted_spill_class": None,
            "extracted_action_required": False,
        }
        if not report_rel_path:
            return result

        # Resolve candidate paths
        candidate_paths = [
            well_dir / report_rel_path,
            well_dir / "maintenance-reports" / Path(report_rel_path).name,
            self.root / report_rel_path,
        ]
        report_path = next((p for p in candidate_paths if p.exists() and p.is_file()), None)
        if not report_path:
            return result

        text = report_path.read_text(encoding="utf-8")
        result["report_markdown"] = text

        # 1. Extract containment hours
        containment_patterns = [
            r'contain(?:ed|ment)[^\n\d]{0,40}?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b)',
            r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s+to\s+contain',
            r'containment\s+time[:\s]+(?:about\s+|approx\.?\s+|~)?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)',
        ]
        for pat in containment_patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                result["extracted_containment_hours"] = float(m.group(1))
                break

        # 2. Extract spill classification
        class_match = re.search(
            r'(?:spill\s+class(?:ification)?|classed\s+as|classified\s+as)[:\s\"\']*([a-zA-Z0-9_-]+)',
            text, flags=re.IGNORECASE
        )
        if class_match:
            result["extracted_spill_class"] = class_match.group(1).lower()

        # 3. Extract 'Action required' compliance flag
        if re.search(r'action\s+required', text, flags=re.IGNORECASE):
            result["extracted_action_required"] = True

        return result

    def iter_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
