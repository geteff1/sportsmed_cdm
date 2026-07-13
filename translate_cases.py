# -*- coding: utf-8 -*-
"""
一次性工具：把 AgentDemo/case01~case10 下的 *_script.json 与 *_gt.json 中的
【自由文本字段】用 Qwen 翻译成简体中文，输出到 SportsMed-CDM/cases_cn/。

保留结构、枚举值（snake_case 变量名与取值）不译，只译人类可读的叙述性文本。
用法：python translate_cases.py
"""

import copy
import glob
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(BASE), "AgentDemo")
OUT = os.path.join(BASE, "cases_cn")

with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
    CFG = json.load(f)["teacher_llm_config"]

CLIENT = OpenAI(api_key=CFG["api_key"], base_url=CFG["base_url"])
MODEL = CFG["model"]

# 需要翻译的字段（相对各自根对象的点路径）
SCRIPT_STR = [
    "patient_profile_for_simulator.demographic_profile.occupation",
    "patient_profile_for_simulator.demographic_profile.living_situation",
    "patient_profile_for_simulator.demographic_profile.insurance_or_payer_context",
    "patient_profile_for_simulator.objective_findings_in_chart.history_of_present_illness",
    "patient_profile_for_simulator.persona.freeform_persona_notes",
    "patient_profile_for_simulator.narrative_context.how_problem_started",
    "patient_profile_for_simulator.narrative_context.what_has_been_tried",
    "patient_profile_for_simulator.narrative_context.what_brought_them_in_today",
    "patient_profile_for_simulator.narrative_context.support_system_present",
    "patient_profile_for_simulator.initial_presentation",
    "interaction_rules.interaction_style_notes",
    "interaction_rules.out_of_scope_handling",
]
SCRIPT_LIST = [
    "patient_profile_for_simulator.objective_findings_in_chart.past_medical_history",
    "patient_profile_for_simulator.objective_findings_in_chart.medications_and_allergies",
    "patient_profile_for_simulator.objective_findings_in_chart.physical_examination",
    "patient_profile_for_simulator.objective_findings_in_chart.imaging",
    "patient_profile_for_simulator.objective_findings_in_chart.laboratory",
    "patient_profile_for_simulator.objective_findings_in_chart.pathology_or_biopsy",
    "patient_profile_for_simulator.objective_findings_in_chart.prior_treatments_attempted",
    "patient_profile_for_simulator.objective_findings_in_chart.functional_assessments_or_scores",
    "patient_profile_for_simulator.patient_self_knowledge.items_patient_can_recall_accurately",
    "patient_profile_for_simulator.patient_self_knowledge.items_patient_can_recall_partially",
    "patient_profile_for_simulator.patient_self_knowledge.items_patient_does_not_know",
    "patient_profile_for_simulator.patient_self_knowledge.items_patient_misremembers",
    "interaction_rules.ambiguity_behaviors",
    "interaction_rules.conflict_behaviors",
    "interaction_rules.missing_info_behaviors",
]
GT_STR = ["S3_decision.decision_rationale"]
# 对象数组里的文本字段：(数组路径, 对象内的键)
GT_OBJLIST = [
    ("S3_decision.unacceptable_options", "reason"),
    ("S3_decision.conditional_recommendation_ranking", "condition"),
]
GT_LIST = [
    "S1_information_gathering.recommended_question_phrasings",
    "S2_representation.key_abstractions",
    "S2_representation.ambiguity_resolution_required",
    "S2_representation.expected_uncertainty_acknowledgements",
    "S2_representation.conflict_resolution_required",
    "S3_decision.minimum_disclosure_to_patient",
    "capability_checks.biases_to_correct",
    "capability_checks.ambiguities_to_handle",
    "capability_checks.preferences_to_integrate",
]


def get_path(obj, path):
    cur = obj
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def set_path(obj, path, value):
    cur = obj
    parts = path.split(".")
    for p in parts[:-1]:
        cur = cur[p]
    cur[parts[-1]] = value


def collect(obj, str_paths, list_paths, objlist_paths=None):
    """返回 [(kind, path, idx_or_key, text)] 待译项。"""
    items = []
    for p in str_paths:
        v = get_path(obj, p)
        if isinstance(v, str) and v.strip():
            items.append(("s", p, None, v))
    for p in list_paths:
        v = get_path(obj, p)
        if isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, str) and x.strip():
                    items.append(("l", p, i, x))
    for p, key in (objlist_paths or []):
        v = get_path(obj, p)
        if isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, dict) and isinstance(x.get(key), str) and x[key].strip():
                    items.append(("o", p, (i, key), x[key]))
    return items


def translate_texts(texts, tries=4):
    if not texts:
        return []
    payload = json.dumps({str(i): t for i, t in enumerate(texts)}, ensure_ascii=False)
    sys_p = (
        "你是运动医学领域的专业医学翻译。把用户给的 JSON 里每个值翻译成简体中文，"
        "要求：医学术语准确规范；患者第一人称的口语保留口语化、自然；"
        "不要增删信息，不要解释。保持键完全不变，只把值翻成中文。"
        "只输出 JSON 对象，不要任何多余文字或代码块标记。"
    )
    for attempt in range(tries):
        try:
            r = CLIENT.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": sys_p},
                          {"role": "user", "content": payload}],
                temperature=0.2, max_tokens=4096, timeout=120,
            )
            txt = r.choices[0].message.content.strip()
            if txt.startswith("```"):
                txt = txt.split("```", 2)[1]
                if txt.startswith("json"):
                    txt = txt[4:]
                txt = txt.strip().rstrip("`").strip()
            d = json.loads(txt)
            out = [d[str(i)] for i in range(len(texts))]
            if all(isinstance(x, str) and x.strip() for x in out):
                return out
        except Exception as e:  # noqa
            sys.stderr.write(f"    translate retry {attempt+1}: {e}\n")
        time.sleep(1.5)
    raise RuntimeError("翻译失败")


def translate_file(path, str_paths, list_paths, objlist_paths=None):
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    out = copy.deepcopy(obj)
    items = collect(out, str_paths, list_paths, objlist_paths)
    if items:
        translated = translate_texts([it[3] for it in items])
        for (kind, p, idx, _), zh in zip(items, translated):
            if kind == "s":
                set_path(out, p, zh)
            elif kind == "l":
                get_path(out, p)[idx] = zh
            else:  # "o": (i, key)
                i, key = idx
                get_path(out, p)[i][key] = zh
    return out


def process_case_dir(case_dir):
    name = os.path.basename(case_dir)
    dst = os.path.join(OUT, name)
    os.makedirs(dst, exist_ok=True)
    done = 0
    for script_path in sorted(glob.glob(os.path.join(case_dir, "*_script.json"))):
        gt_path = script_path.replace("_script.json", "_gt.json")
        if not os.path.exists(gt_path):
            continue
        base = os.path.basename(script_path).replace("_script.json", "")
        out_script = os.path.join(dst, base + "_script.json")
        out_gt = os.path.join(dst, base + "_gt.json")
        if os.path.exists(out_script) and os.path.exists(out_gt):
            print(f"SKIP {name}/{base} (exists)", flush=True)
            done += 1
            continue
        try:
            s = translate_file(script_path, SCRIPT_STR, SCRIPT_LIST)
            g = translate_file(gt_path, GT_STR, GT_LIST, GT_OBJLIST)
            with open(out_script, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
            with open(out_gt, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False, indent=2)
            print(f"OK   {name}/{base}", flush=True)
            done += 1
        except Exception as e:  # noqa
            print(f"FAIL {name}/{base}: {e}", flush=True)
    return name, done


def main():
    os.makedirs(OUT, exist_ok=True)
    case_dirs = sorted(glob.glob(os.path.join(SRC, "case*")))
    print(f"翻译 {len(case_dirs)} 个 case 目录 -> {OUT}", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(process_case_dir, d) for d in case_dirs]
        for fu in as_completed(futs):
            name, done = fu.result()
            print(f"== {name} 完成 {done} 个版本 ==", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
