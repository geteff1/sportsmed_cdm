# -*- coding: utf-8 -*-
"""
SportsMed-CDM 学生接诊模拟器 —— 后端

按 PRD 会话生命周期实现：
  初始化 → 动态信息采集 → 病历表征(结构化) → 诊断 → 治疗决策 → (训练模式)分步即时反馈
  → 会话结束四段评分与塌陷定位 + 揭示 GT + 轨迹记录

两种运行模式：
  · training   训练模式：每步可获 teacher 即时形成性反馈；末尾揭示金标准 + 完整报告
  · assessment 测评模式：全程无反馈、无中途揭示；末尾出四段报告（纯测量用途）
"""

import datetime
import json
import os
import uuid

from flask import (Flask, request, jsonify, render_template,
                   render_template_string, redirect, session)

from case_loader import discover_cases, load_pair
from options import ACL_OPTIONS
from sim_agents import PatientAgent, AssistantAgent, TeacherAgent
from variable_labels import cn_var_list

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# LLM 配置：优先读 config.json（本地）；没有该文件时用内置默认值（线上部署，
# 密钥只从环境变量 LLM_API_KEY 注入，不进代码库）
_CFG_PATH = os.path.join(BASE, "config.json")
if os.path.exists(_CFG_PATH):
    with open(_CFG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
else:
    _BASE_URL = os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    _MODEL = os.environ.get("LLM_MODEL", "qwen3.6-27b")
    CONFIG = {
        "patient_llm_config":   {"api_key": "", "base_url": _BASE_URL, "model": _MODEL,
                                 "temperature": 0.7, "max_tokens": 1024, "timeout": 40},
        "assistant_llm_config": {"api_key": "", "base_url": _BASE_URL, "model": _MODEL,
                                 "temperature": 0.4, "max_tokens": 1024, "timeout": 40},
        "teacher_llm_config":   {"api_key": "", "base_url": _BASE_URL, "model": _MODEL,
                                 "temperature": 0.3, "max_tokens": 3072, "timeout": 90},
    }

# 环境变量 LLM_API_KEY 存在时覆盖一切来源的密钥
_ENV_KEY = os.environ.get("LLM_API_KEY", "").strip()
if _ENV_KEY:
    for _k in ("patient_llm_config", "assistant_llm_config", "teacher_llm_config"):
        CONFIG[_k]["api_key"] = _ENV_KEY

# 访问口令：环境变量 ACCESS_CODE 可覆盖；置空字符串则关闭门禁
ACCESS_CODE = os.environ.get("ACCESS_CODE", "WestChinaHospital")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or uuid.uuid4().hex
SESSIONS = {}
CASES = discover_cases()
CASE_BY_ID = {c["id"]: c for c in CASES}

_LOGIN_PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SportsMed-CDM · 访问验证</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:"Microsoft YaHei",system-ui,sans-serif;
       background:linear-gradient(135deg,#0f2b46 0%,#1c4d7a 100%);}
  .card{background:#fff;border-radius:14px;padding:40px 44px;width:320px;
        box-shadow:0 12px 40px rgba(0,0,0,.35);text-align:center;}
  h1{font-size:19px;margin:0 0 6px;color:#15385c;}
  p.sub{font-size:13px;color:#7a8a99;margin:0 0 24px;}
  input{width:100%;box-sizing:border-box;padding:11px 12px;font-size:15px;
        border:1px solid #c9d4de;border-radius:8px;outline:none;}
  input:focus{border-color:#2c6cb0;box-shadow:0 0 0 3px rgba(44,108,176,.15);}
  button{width:100%;margin-top:14px;padding:11px;font-size:15px;border:none;border-radius:8px;
         background:#2c6cb0;color:#fff;cursor:pointer;}
  button:hover{background:#255c97;}
  .err{color:#c0392b;font-size:13px;margin-top:12px;min-height:18px;}
</style></head><body>
<form class="card" method="post" action="/login">
  <h1>运动损伤接诊模拟器</h1>
  <p class="sub">SportsMed-CDM 教学系统 · 请输入访问口令</p>
  <input type="password" name="code" placeholder="访问口令" autofocus autocomplete="off">
  <button type="submit">进入系统</button>
  <div class="err">{{ error }}</div>
</form></body></html>"""


@app.before_request
def _require_access_code():
    if not ACCESS_CODE or request.endpoint in ("login", "static"):
        return None
    if session.get("authed"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "未通过访问验证，请刷新页面输入口令"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if (request.form.get("code") or "").strip() == ACCESS_CODE:
            session["authed"] = True
            session.permanent = True
            return redirect("/")
        error = "口令不正确，请重试"
    return render_template_string(_LOGIN_PAGE, error=error)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cases")
def api_cases():
    return jsonify([{k: c[k] for k in ("id", "label", "difficulty", "case_type", "patient_brief")} for c in CASES])


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(force=True)
    case = CASE_BY_ID.get(data.get("case_id"))
    if not case:
        return jsonify({"error": "找不到该病例"}), 400
    mode = data.get("mode", "training")
    if mode not in ("training", "assessment"):
        mode = "training"

    script, gt = load_pair(case["script_path"], case["gt_path"])
    patient = PatientAgent(script, CONFIG["patient_llm_config"])
    assistant = AssistantAgent(script, CONFIG["assistant_llm_config"])

    sid = uuid.uuid4().hex
    SESSIONS[sid] = {
        "case": case, "mode": mode, "script": script, "gt": gt,
        "patient": patient, "assistant": assistant,
        "patient_history": [], "assistant_history": [], "transcript": [],
        "submissions": {},
    }
    # stem：主诉 + 人口学 + 就诊情境（不含答案）
    demo = script.get("patient_profile_for_simulator", {}).get("demographic_profile", {})
    return jsonify({
        "session_id": sid, "mode": mode,
        "case_label": case["label"], "patient_brief": case["patient_brief"],
        "opening": patient.opening, "options": ACL_OPTIONS,
        "stem": {
            "age": demo.get("age_years"), "sex": {"male": "男", "female": "女"}.get(demo.get("sex"), ""),
            "occupation": demo.get("occupation", ""),
        },
    })


def _transcript_text(sess):
    return "\n".join(
        f"[第{t['turn']}轮·对{'助理' if t['target']=='assistant' else '患者'}] 医生：{t['query']}\n    → {t['reply']}"
        for t in sess["transcript"]
    )


@app.route("/api/message", methods=["POST"])
def api_message():
    data = request.get_json(force=True)
    sess = SESSIONS.get(data.get("session_id"))
    if not sess:
        return jsonify({"error": "会话已过期，请重新开始"}), 400
    target = data.get("target", "patient")
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "请输入内容"}), 400
    try:
        if target == "assistant":
            reply = sess["assistant"].respond(text, sess["assistant_history"])
            sess["assistant_history"] += [{"role": "user", "content": f"医生：{text}"},
                                          {"role": "assistant", "content": reply}]
        else:
            target = "patient"
            reply = sess["patient"].respond(text, sess["patient_history"])
            sess["patient_history"] += [{"role": "user", "content": f"医生：{text}"},
                                        {"role": "assistant", "content": reply}]
    except Exception as e:  # noqa
        return jsonify({"error": f"智能体调用失败：{e}"}), 502
    sess["transcript"].append({"turn": len(sess["transcript"]) + 1, "target": target, "query": text, "reply": reply})
    return jsonify({"reply": reply, "target": target})


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """训练模式：对某一步给即时形成性反馈。"""
    data = request.get_json(force=True)
    sess = SESSIONS.get(data.get("session_id"))
    if not sess:
        return jsonify({"error": "会话已过期，请重新开始"}), 400
    if sess["mode"] != "training":
        return jsonify({"error": "测评模式不提供分步反馈"}), 400
    stage = data.get("stage", "")
    payload = data.get("payload", {})
    sess["submissions"][stage] = payload  # 记录该步提交
    teacher = TeacherAgent(CONFIG["teacher_llm_config"])
    try:
        fb = teacher.feedback(stage, sess["gt"], ACL_OPTIONS, _transcript_text(sess), payload)
    except Exception as e:  # noqa
        return jsonify({"error": f"反馈生成失败：{e}"}), 502
    return jsonify({"feedback": fb})


@app.route("/api/finish", methods=["POST"])
def api_finish():
    data = request.get_json(force=True)
    sess = SESSIONS.get(data.get("session_id"))
    if not sess:
        return jsonify({"error": "会话已过期，请重新开始"}), 400
    representation = data.get("representation", {})
    diagnosis = data.get("diagnosis", {})
    decision = data.get("decision", {})
    sess["submissions"].update({"represent": representation, "diagnose": diagnosis, "decide": decision})

    teacher = TeacherAgent(CONFIG["teacher_llm_config"])
    try:
        result = teacher.grade(sess["gt"], ACL_OPTIONS, _transcript_text(sess),
                               representation, diagnosis, decision)
    except Exception as e:  # noqa
        return jsonify({"error": f"评分失败：{e}"}), 502

    gt_s3 = sess["gt"].get("S3_decision", {})
    gt_s1 = sess["gt"].get("S1_information_gathering", {})
    acceptable = gt_s3.get("acceptable_options", [])
    chosen = decision.get("options", [])
    chosen_hit = bool(chosen) and all(o in acceptable for o in chosen)
    is_gray = gt_s3.get("is_gray_zone", False)
    # 灰区识别是否正确（确定性锚点）
    student_gray = str(decision.get("is_gray_judgment", "")).strip()
    gray_ok = None
    if student_gray in ("是", "否"):
        gray_ok = (student_gray == "是") == bool(is_gray)

    # 完整报告（含 GT），始终存档到 output/ 供带教/研究使用
    full_report = {
        "mode": sess["mode"],
        "scoring": result,
        "decision_hit": chosen_hit,
        "gray_recognition_ok": gray_ok,
        "turns": len(sess["transcript"]),
        "ground_truth": {
            "is_gray_zone": is_gray,
            "acceptable_options": acceptable,
            "unacceptable_options": gt_s3.get("unacceptable_options", []),
            "expert_decision_distribution": gt_s3.get("expert_decision_distribution", {}),
            "decision_rationale": gt_s3.get("decision_rationale", ""),
            "minimum_disclosure_to_patient": gt_s3.get("minimum_disclosure_to_patient", []),
            "essential_clinical_variables_cn": cn_var_list(gt_s1.get("essential_clinical_variables", [])),
            "essential_preference_variables_cn": cn_var_list(gt_s1.get("essential_preference_variables", [])),
            "minimum_set_cn": cn_var_list(gt_s1.get("minimum_set_for_safe_decision", [])),
        },
    }
    _save_trajectory(sess, full_report)

    # 训练模式：披露 GT + 完整反馈；测评模式：仅返回四段得分与塌陷定位（PRD：无 GT 披露）
    if sess["mode"] == "training":
        return jsonify({**full_report, "disclose_gt": True})
    stages = result.get("stages", {})
    slim = {k: {kk: v.get(kk) for kk in ("score", "collapsed") if kk in v} for k, v in stages.items()}
    return jsonify({
        "mode": "assessment", "disclose_gt": False,
        "turns": len(sess["transcript"]),
        "scoring": {"collapse_stage": result.get("collapse_stage"), "stages": slim},
    })


def _save_trajectory(sess, report):
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        cid = sess["case"]["id"]
        path = os.path.join(OUTPUT_DIR, f"traj_{cid}_{sess['mode']}_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "case_id": cid, "mode": sess["mode"], "timestamp": ts,
                "transcript": sess["transcript"], "submissions": sess["submissions"],
                "scoring": report.get("scoring"), "decision_hit": report.get("decision_hit"),
                "gray_recognition_ok": report.get("gray_recognition_ok"),
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print("=" * 56)
    print("  SportsMed-CDM 运动损伤接诊模拟器（训练/测评双模式）")
    print(f"  已加载 {len(CASES)} 个中文病例")
    print(f"  打开浏览器访问：http://127.0.0.1:{port}")
    print("=" * 56)
    app.run(host=host, port=port, debug=False, threaded=True)
