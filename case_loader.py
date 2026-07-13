# -*- coding: utf-8 -*-
"""发现并加载 cases_cn/ 下已中文化的 (script, gt) 病例对。"""

import glob
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
CASES_DIR = os.path.join(BASE, "cases_cn")

_COMPLETE = {"full": "信息完整", "partial": "信息不全"}
_CONSIST = {"consistent": "前后一致", "conflict": "存在矛盾", "inconsistent": "存在矛盾"}
_CLARITY = {"clear": "表述清晰", "vague": "表述含糊", "ambiguous": "表述含糊"}


def _difficulty(meta: dict) -> str:
    comp, cons, clar = meta.get("info_completeness"), meta.get("info_consistency"), meta.get("expression_clarity")
    stars = 1 + (comp == "partial") + (cons not in (None, "consistent")) + (clar not in (None, "clear"))
    parts = [_COMPLETE.get(comp, comp or "?"), _CONSIST.get(cons, cons or "?"), _CLARITY.get(clar, clar or "?")]
    return f"{'★' * min(stars, 4)}（{'、'.join(parts)}）"


def discover_cases() -> list:
    cases = []
    for case_dir in sorted(glob.glob(os.path.join(CASES_DIR, "case*"))):
        for script_path in sorted(glob.glob(os.path.join(case_dir, "*_script.json"))):
            gt_path = script_path.replace("_script.json", "_gt.json")
            if not os.path.exists(gt_path):
                continue
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    script = json.load(f)
            except Exception:
                continue
            meta = script.get("variant_metadata", {})
            item_id = script.get("item_id", os.path.basename(script_path))
            m = re.search(r"case(\d+)_ver(\d+)", os.path.basename(script_path))
            label = f"病例 {int(m.group(1))} · 版本 {m.group(2)}" if m else item_id
            demo = script.get("patient_profile_for_simulator", {}).get("demographic_profile", {})
            sex = {"male": "男", "female": "女"}.get(demo.get("sex"), "")
            cases.append({
                "id": item_id,
                "label": label,
                "difficulty": _difficulty(meta),
                "case_type": script.get("case_type", "nogray"),
                "patient_brief": f"{demo.get('age_years','?')}岁{sex} · {demo.get('occupation','')}",
                "script_path": script_path,
                "gt_path": gt_path,
            })
    return cases


def load_pair(script_path: str, gt_path: str):
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)
    return script, gt
