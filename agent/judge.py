"""LLM-as-a-judge (Milestone 2).

Scores a drafted reply on 3 criteria (1-5):
  helpfulness  - does it actually answer / move the sender's request forward?
  tone         - polite, professional, appropriate length, signed by Ravi?
  correctness  - does it keep the key facts (dates, times, names) right and invent nothing?
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import text_of

JUDGE_PROMPT = """JUDGE. You are a strict evaluator of email replies written by an AI assistant for Ravi.
Score the AGENT REPLY from 1 (very bad) to 5 (excellent) on:
- helpfulness: Does it directly address what the sender asked and move it forward?
- tone: Is it polite, professional, concise and signed 'Ravi'?
- correctness: Does it keep the KEY POINTS (dates, times, names, items) correct and avoid invented facts?
Use the IDEAL REPLY only as a reference, not as the only correct answer.
Return ONLY a JSON object: {"helpfulness": int, "tone": int, "correctness": int, "reasoning": "one sentence"}"""

CRITERIA = ["helpfulness", "tone", "correctness"]


def judge_reply(llm, email: dict, reply: str, ideal: str = "", key_points: list | None = None) -> dict:
    if not reply:
        return {**{c: 1 for c in CRITERIA}, "reasoning": "The agent produced no reply.", "score": 0.2}
    prompt = (
        f"EMAIL:\nFrom: {email['from']}\nSubject: {email['subject']}\nBody: {email['body']}\n\n"
        f"KEY POINTS: {'; '.join(key_points or [])}\n"
        f"IDEAL REPLY: {ideal}\n\n"
        f"AGENT REPLY:\n{reply}"
    )
    raw = text_of(llm.invoke([SystemMessage(content=JUDGE_PROMPT), HumanMessage(content=prompt)]))
    scores = _parse(raw)
    scores["score"] = round(sum(scores[c] for c in CRITERIA) / (5 * len(CRITERIA)), 3)   # 0..1
    return scores


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    out = {c: max(1, min(5, int(data.get(c, 1)))) for c in CRITERIA}
    out["reasoning"] = str(data.get("reasoning", raw[:200]))
    return out
