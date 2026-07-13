# -*- coding: utf-8 -*-
"""把金标准里的英文变量名 / 枚举值映射为中文，用于评分报告展示。"""

VAR_CN = {
    # 临床变量
    "age": "年龄",
    "skeletal_maturity": "骨骼成熟度",
    "tear_completeness": "撕裂完整性（完全/部分）",
    "tear_location": "撕裂部位",
    "time_since_injury_weeks": "受伤时长（周）",
    "concomitant_meniscal_tear": "合并半月板损伤",
    "concomitant_cartilage_injury": "合并软骨损伤",
    "concomitant_ligament_injury": "合并韧带损伤（是否多韧带）",
    "pivot_shift_grade": "轴移试验分级",
    "preinjury_tegner_activity_score": "伤前 Tegner 活动评分",
    "occupational_demand": "职业体力需求",
    "current_functional_instability": "当前功能性不稳（打软腿）",
    "knee_range_of_motion": "膝关节活动度",
    "bmi": "体重指数 BMI",
    "smoking_status": "吸烟状况",
    "diabetes_or_immune_compromise": "糖尿病/免疫抑制",
    "rehabilitation_access": "康复可及性",
    "surgical_risk_class": "手术风险分级（ASA）",
    "prior_contralateral_ACL_injury": "对侧 ACL 既往损伤史",
    "graft_choice_preference": "移植物选择偏好",
    # 偏好变量
    "return_to_pivoting_sport_priority": "重返旋转类运动的优先级",
    "surgical_risk_aversion": "对手术风险的规避程度",
    "rehabilitation_burden_tolerance": "对康复负担的耐受度",
    "activity_modification_acceptance": "对活动方式调整的接受度",
    "timeline_pressure": "时间/进度压力",
    "long_term_arthritis_concern": "对远期关节炎的担忧",
    "financial_or_insurance_constraint": "经济/医保限制",
    "sport_history": "运动史",
    "specific_giving_way_episodes": "具体打软腿发作",
    "support_system": "支持系统",
}


def cn_var(name: str) -> str:
    """带原始括号后缀的变量名也能匹配，如 'concomitant_ligament_injury (multiligament)'。"""
    base = name.split(" (")[0].strip()
    label = VAR_CN.get(base)
    if not label:
        return name
    # 保留原括号里的取值提示
    if " (" in name:
        return f"{label}（{name.split(' (',1)[1].rstrip(')')}）"
    return label


def cn_var_list(names):
    return [cn_var(n) for n in (names or [])]
