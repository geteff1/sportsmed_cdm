# -*- coding: utf-8 -*-
"""
每日用量限额（防止恶意访问耗尽大模型额度）

  · DAILY_LOGIN_LIMIT  每天最多允许多少次成功登录（默认 100）
  · DAILY_LLM_LIMIT    每天最多发出多少次大模型请求（默认 200，重试也计数）

两个数值都可用同名环境变量覆盖；设为 0 表示不限制。
按北京时间每天 0 点清零。计数保存在进程内存，并尽力写入一个本地文件；
注意：免费版 Render 休眠或重新部署后本地文件会丢失，计数会从 0 重新开始，
所以真正兜底的额度上限应同时在大模型平台（阿里云百炼）一侧设置。
"""
import datetime
import json
import os
import threading

_BASE = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_BASE, "output", "_quota_state.json")
_LOCK = threading.Lock()
_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间


def _limit(name, default):
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


LIMITS = {
    "login": _limit("DAILY_LOGIN_LIMIT", 100),
    "llm": _limit("DAILY_LLM_LIMIT", 200),
}
_MESSAGES = {
    "login": "今日访问次数已达上限，请明天再试。",
    "llm": "今日智能体调用次数已达上限，请明天再试。",
}
_state = {"date": "", "login": 0, "llm": 0}


class QuotaExceeded(Exception):
    """当日限额已用完。"""


def _today():
    return datetime.datetime.now(_TZ).strftime("%Y-%m-%d")


def _load():
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("date") == _today():
            _state.update({k: saved.get(k, _state[k]) for k in _state})
    except Exception:  # noqa  文件不存在或损坏都按 0 开始
        pass


def _save():
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except Exception:  # noqa  写不了不影响主流程
        pass


def consume(kind):
    """占用一次名额；超限时抛出 QuotaExceeded。"""
    with _LOCK:
        today = _today()
        if _state["date"] != today:
            _state.update({"date": today, "login": 0, "llm": 0})
        limit = LIMITS[kind]
        if limit and _state[kind] >= limit:
            raise QuotaExceeded(_MESSAGES[kind])
        _state[kind] += 1
        _save()


def snapshot():
    with _LOCK:
        return dict(_state, limits=dict(LIMITS))


_load()
