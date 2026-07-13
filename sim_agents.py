# -*- coding: utf-8 -*-
"""
三个 LLM 智能体：
  - PatientAgent  患者：只讲主观感受/个人史/症状/偏好，按病例披露规则回答，不主动泄题。
  - AssistantAgent 助理：只提供客观资料（查体、影像、化验、评分），按需返回。
  - TeacherAgent  带教老师：
       · feedback()  训练模式下对某一步给"即时形成性反馈"（改进导向，不打分）
       · grade()     会话结束按 CCR 四段链路（采集/表征/诊断/决策）打分 + 塌陷定位
统一走 OpenAI 兼容接口（本产品指向阿里云百炼 Qwen）。
"""

import json
import re
import time
from openai import OpenAI


class LLMClient:
    def __init__(self, cfg: dict):
        self.model = cfg.get("model", "qwen3.6-27b")
        self.temperature = cfg.get("temperature", 0.7)
        self.max_tokens = cfg.get("max_tokens", 1024)
        self.timeout = cfg.get("timeout", 40)
        self.client = OpenAI(api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""))

    def chat(self, messages, max_retries=3, temperature=None, max_tokens=None):
        last = ""
        for i in range(max_retries):
            try:
                r = self.client.chat.completions.create(
                    model=self.model, messages=messages,
                    temperature=self.temperature if temperature is None else temperature,
                    max_tokens=self.max_tokens if max_tokens is None else max_tokens,
                    timeout=self.timeout,
                )
                c = r.choices[0].message.content
                if c and c.strip():
                    return c.strip()
            except Exception as e:  # noqa
                last = f"{type(e).__name__}: {e}"
            time.sleep(1.2)
        raise RuntimeError(f"LLM 调用失败：{last}")


def _fmt(items, b="  · "):
    return "\n".join(f"{b}{x}" for x in items) if items else "（无）"


# --------------------------------------------------------------------------- #
#  患者
# --------------------------------------------------------------------------- #
def build_patient_prompt(script: dict) -> str:
    p = script.get("patient_profile_for_simulator", {})
    demo, persona = p.get("demographic_profile", {}), p.get("persona", {})
    nar, chart = p.get("narrative_context", {}), p.get("objective_findings_in_chart", {})
    sk, rr = p.get("patient_self_knowledge", {}), script.get("interaction_rules", {}).get("release_rules", {})
    return f"""你正在参与一个【虚构的医患对话教学模拟】（无真实患者）。你扮演患者本人，用第一人称、口语化中文回答医生。

## 基本情况
- 年龄：{demo.get('age_years','未知')}，性别：{demo.get('sex','未知')}
- 职业：{demo.get('occupation','未知')}
- 生活/家庭：{demo.get('living_situation','未知')}
- 医保/费用：{demo.get('insurance_or_payer_context','未知')}

## 你为什么来看病
{nar.get('how_problem_started','')}
{nar.get('what_has_been_tried','')}
{nar.get('what_brought_them_in_today','')}

## 你准确知道的事
{_fmt(sk.get('items_patient_can_recall_accurately', []))}
## 你只模糊记得的（用大白话，别用术语）
{_fmt(sk.get('items_patient_can_recall_partially', []))}
## 你会记错的
{_fmt(sk.get('items_patient_misremembers', []))}
## 你不知道/记不清的（被问就说"不太清楚"，别编）
{_fmt(sk.get('items_patient_does_not_know', []))}
## 既往史 / 用药 / 已试过的治疗
{_fmt(chart.get('past_medical_history', []))}
{_fmt(chart.get('medications_and_allergies', []))}
{_fmt(chart.get('prior_treatments_attempted', []))}

## 性格与沟通
- 风格：{persona.get('communication_style','自然')}；健康素养：{persona.get('health_literacy','中等')}；情绪：{persona.get('emotional_state','平静')}
- 决策风格：{persona.get('decision_making_style','自主')}；对医生信任：{persona.get('trust_in_clinician','中等')}
- 补充：{persona.get('freeform_persona_notes','')}

## 信息披露规则
- 可主动说：{', '.join(rr.get('spontaneous', [])) or '无'}
- 被直接问才说：{', '.join(rr.get('on_direct_question', [])) or '无'}
- 被温和追问才说（敏感）：{', '.join(rr.get('on_sensitive_probe', [])) or '无'}

## 铁律
1. 客观检查（影像/化验/病理/查体数值）不由你答，那是"助理"的事；被问到就说"这个得看报告/让助手查"。
2. 只答你知道的，不知道就说不知道，绝不编造。
3. 只回答被问到的，别主动倒出没被问的偏好或线索；回答自然但让医生靠追问来挖。
4. 永不跳出角色，不提"金标准/剧本/模拟/专家决策"。
5. 你不是医生，不给自己下诊断或开方案；可表达担心、偏好、顾虑。

## 开场白（对话开始时用这句）
"{p.get('initial_presentation','')}"
"""


class PatientAgent:
    def __init__(self, script, cfg):
        self.llm = LLMClient(cfg)
        self.system = build_patient_prompt(script)
        self.opening = script.get("patient_profile_for_simulator", {}).get("initial_presentation", "")

    def respond(self, msg, history):
        m = [{"role": "system", "content": self.system}] + history
        m.append({"role": "user", "content": f"医生说：{msg}\n\n请以患者身份用中文回答。"})
        return self.llm.chat(m)


# --------------------------------------------------------------------------- #
#  助理
# --------------------------------------------------------------------------- #
def build_assistant_prompt(script: dict) -> str:
    p = script.get("patient_profile_for_simulator", {})
    demo, chart = p.get("demographic_profile", {}), p.get("objective_findings_in_chart", {})

    def sec(t, items):
        return f"### {t}\n{_fmt(items)}\n" if items else ""

    body = ""
    if chart.get("history_of_present_illness"):
        body += f"### 现病史\n{chart['history_of_present_illness']}\n\n"
    body += sec("查体", chart.get("physical_examination", []))
    body += sec("影像", chart.get("imaging", []))
    body += sec("化验", chart.get("laboratory", []))
    body += sec("病理/活检", chart.get("pathology_or_biopsy", []))
    body += sec("功能评分", chart.get("functional_assessments_or_scores", []))
    return f"""你是协助医生的【临床助理/技师】，手上有这位患者所有客观检查资料，用中文回答。

## 患者：{demo.get('age_years','未知')}岁，{demo.get('sex','未知')}

## 你掌握的客观资料
{body}

## 规则
1. 只有医生【主动请求】某项查体/影像/化验/病理/功能评分时才提供对应结果。
2. 只报资料里有的；医生问的若资料没有，就说"该项未做/暂无结果"，别编。
3. 一次只答被问的那一项或几项，简洁准确，别一股脑全倒出来。
4. 你只管客观数据；患者的主观感受、偏好、情绪不归你答。
5. 永不跳出角色，不提"金标准/剧本/模拟"。
"""


class AssistantAgent:
    def __init__(self, script, cfg):
        self.llm = LLMClient(cfg)
        self.system = build_assistant_prompt(script)

    def respond(self, msg, history):
        m = [{"role": "system", "content": self.system}] + history
        m.append({"role": "user", "content": f"医生请求：{msg}\n\n请提供相关客观临床资料（中文）。"})
        return self.llm.chat(m)


# --------------------------------------------------------------------------- #
#  带教/评分
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> dict:
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        m = re.search(r"(\{.*\})", text, re.DOTALL)
    return json.loads(m.group(1) if m else text)


def _gt_brief(gt: dict) -> str:
    s1, s2, s3 = gt.get("S1_information_gathering", {}), gt.get("S2_representation", {}), gt.get("S3_decision", {})
    return f"""【S1 应采集】必须临床变量：{s1.get('essential_clinical_variables', [])}
重要临床变量：{s1.get('important_clinical_variables', [])}
必须偏好变量：{s1.get('essential_preference_variables', [])}
安全决策最小信息集：{s1.get('minimum_set_for_safe_decision', [])}
【S2 目标表征】{json.dumps(s2.get('target_representation', {}), ensure_ascii=False)}
关键抽象：{s2.get('key_abstractions', [])}
【S3 决策】是否灰区：{'是' if s3.get('is_gray_zone') else '否'}；可接受选项：{s3.get('acceptable_options', [])}
不可接受选项及原因：{json.dumps(s3.get('unacceptable_options', []), ensure_ascii=False)}
专家决策分布：{json.dumps(s3.get('expert_decision_distribution', {}), ensure_ascii=False)}
决策理由：{s3.get('decision_rationale', '')}"""


STAGE_CN = {"gather": "信息采集", "represent": "病历表征", "diagnose": "诊断", "decide": "治疗决策"}


class TeacherAgent:
    def __init__(self, cfg):
        self.llm = LLMClient(cfg)

    # -- 训练模式：某一步的即时形成性反馈（不打分，改进导向） -----------------
    def feedback(self, stage: str, gt: dict, options: list, transcript_text: str, payload: dict) -> str:
        opt_lines = "\n".join(f"- {o['id']}. {o['title']}：{o['desc']}" for o in options)
        sys_p = f"""你是运动医学带教老师，正在训练模式下对医学生接诊的【{STAGE_CN.get(stage, stage)}】这一步给"即时形成性反馈"。
要求：用中文，2-4 句，以改进为目的、鼓励而具体；指出这一步做得好的地方 + 最该补的 1-2 点。
【不要打分、不要直接公布金标准答案或最终该选哪个】，只给能帮学生自己改进的提示。

## 候选治疗方案
{opt_lines}

## 本病例金标准（仅你可见，用于判断方向，不可照抄给学生）
{_gt_brief(gt)}"""
        user = f"""## 学生到目前为止的问诊记录
{transcript_text or '（尚无问诊）'}

## 学生在【{STAGE_CN.get(stage, stage)}】这一步提交的内容
{json.dumps(payload, ensure_ascii=False, indent=2)}

请给出针对这一步的即时形成性反馈（2-4 句中文）。"""
        return self.llm.chat(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user}],
            temperature=0.4, max_tokens=600,
        )

    # -- 会话结束：四段评分 + 塌陷定位 --------------------------------------
    def grade(self, gt: dict, options: list, transcript_text: str,
              representation: dict, diagnosis: dict, decision: dict) -> dict:
        opt_lines = "\n".join(f"- {o['id']}. {o['title']}：{o['desc']}" for o in options)
        sys_p = f"""你是运动医学带教老师，给医学生一次完整接诊打分并给中文反馈。
沿"信息采集 → 病历表征 → 诊断 → 治疗决策"四段分别量化（每段 0–100，<60 记为塌陷 collapsed=true），
并定位最先塌陷的环节。

## 候选治疗方案
{opt_lines}

## 金标准（仅你可见）
{_gt_brief(gt)}

## 各段评分要点
- 信息采集：①必须临床/偏好变量覆盖率、是否覆盖安全决策最小信息集；②【查体请求恰当性】——该请求的关键体征（如 Lachman、轴移、前抽屉、活动度）是否向助理请求、有无漏查；③【检查开立经济性】——必要检查（如 MRI）是否开立、有无无关或过度的检查请求；④问诊序贯效率（是否用尽量少的轮次覆盖关键项）。
- 病历表征：现病史/查体/辅助检查/初步印象是否把【已采集到】的关键信息正确纳入、是否正确抽象、有无曲解遗漏、鉴别假设是否合理。
- 诊断：主诊断是否正确、鉴别是否合理、置信度是否校准（过度自信/不足）。
- 治疗决策：①所选是否落在可接受集合、是否避开不可接受选项；②【决策安全性】——有无危险/明显有害的建议；③对灰区病例还要看"是否正确识别灰区""是否触发医患共同决策/征询偏好"。

只输出如下 JSON（不要多余文字）：
```json
{{
  "overall_comment": "总体点评 2-4 句",
  "collapse_stage": "最先塌陷环节：信息采集/病历表征/诊断/治疗决策/无",
  "stages": {{
    "gathering":     {{"score":0-100,"collapsed":false,"covered":["问到的关键变量"],"missed":["漏问的必须变量"],"exam_requests":"查体请求恰当性：充分/有漏项/未查体","test_economy":"检查开立：恰当/有过度检查/必要检查缺失","comment":"1-3句"}},
    "representation":{{"score":0-100,"collapsed":false,"comment":"1-3句，指出纳入/遗漏"}},
    "diagnosis":     {{"score":0-100,"collapsed":false,"comment":"1-3句"}},
    "decision":      {{"score":0-100,"collapsed":false,"chosen_ok":true,"gray_recognition":"正确/错误/不适用","shared_decision":"到位/不足/未做","safety":"安全/存疑/有危险建议","comment":"1-3句，对比专家分布"}}
  }},
  "top_suggestions": ["3条最重要改进建议"]
}}
```"""
        user = f"""## 学生问诊记录（按时间顺序）
{transcript_text or '（未进行问诊）'}

## S2 病历表征（学生填写）
- 现病史：{representation.get('hpi','（空）')}
- 查体：{representation.get('exam','（空）')}
- 辅助检查：{representation.get('workup','（空）')}
- 初步印象/鉴别假设：{representation.get('impression','（空）')}

## S3 诊断（学生填写）
- 主诊断：{diagnosis.get('primary','（空）')}
- 鉴别诊断：{diagnosis.get('differentials','（空）')}
- 置信度：{diagnosis.get('confidence','（空）')}%

## S4 治疗决策（学生填写）
- 选择方案：{', '.join(decision.get('options', [])) or '（未选）'}
- 理由：{decision.get('rationale','（空）')}
- 学生判断本例是否为灰区：{decision.get('is_gray_judgment','（未判断）')}
- 是否已与患者共同决策/征询偏好：{decision.get('shared_decision_done','（未说明）')}；说明：{decision.get('shared_decision_note','')}

请严格按 JSON 格式输出评分。"""
        raw = self.llm.chat(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user}],
            temperature=0.3, max_tokens=3072,
        )
        try:
            return _extract_json(raw)
        except Exception:
            return {"overall_comment": "评分解析失败，以下为原始反馈。", "collapse_stage": "无",
                    "stages": {}, "top_suggestions": [], "_raw": raw}
