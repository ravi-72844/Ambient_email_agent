"""LLM factory.

Real Google Gemini if GOOGLE_API_KEY is set, otherwise a keyword-based FakeLLM so that the whole
pipeline (graph, HITL, memory, evaluation, UI) can be run and tested WITHOUT an API key.
FakeLLM numbers are NOT a real benchmark - always report results from Gemini.
"""
import json
import os
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def using_real_llm() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY"))


def get_llm() -> BaseChatModel:
    if using_real_llm():
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            max_retries=2,
            timeout=60,
        )
    return FakeLLM()


def text_of(msg) -> str:
    """Gemini may return content as a list of parts; normalise to plain text."""
    c = msg.content
    if isinstance(c, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return c


# ============================================================================ FakeLLM
SCHEDULING_WORDS = ["call", "meeting", "available", "availability", "schedule", "lunch", "time works",
                    "reschedule", "interview", "demo", "sync"]
GENERIC_SENDERS = {"hr", "info", "team", "support", "admin", "noreply", "no-reply", "contact", "office",
                   "pm", "lead", "client", "teammate", "recruiter", "friend", "classmate", "mentor", "manager"}


def sender_name(sender: str) -> str:
    """'bob.sharma@company.com' -> 'Bob', 'hr@x.com' -> 'there'."""
    m = re.search(r"([A-Za-z0-9._%+-]+)@", sender or "")
    local = (m.group(1) if m else sender or "").split(".")[0].split("_")[0]
    local = re.sub(r"\d+", "", local)
    if not local or local.lower() in GENERIC_SENDERS:
        return "there"
    return local.capitalize()


def apply_name_preferences(text: str, prefs_text: str) -> str:
    """Apply learned preferences of the form: Use "Robert" instead of "Bob"."""
    for new, old in re.findall(r'[Uu]se\s+"([^"]+)"\s+instead of\s+"([^"]+)"', prefs_text):
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


class FakeLLM(BaseChatModel):
    """Deterministic keyword model. Lets you run everything offline. Not a real accuracy benchmark."""

    @property
    def _llm_type(self) -> str:
        return "fake-keyword-llm"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = str(messages[0].content)
        if system.startswith("TRIAGE"):
            msg = AIMessage(content=self._triage(str(messages[-1].content).lower(), system))
        elif system.startswith("MEMORY"):
            msg = AIMessage(content=self._memory(str(messages[-1].content)))
        elif system.startswith("JUDGE"):
            msg = AIMessage(content=self._judge(str(messages[-1].content)))
        else:
            msg = self._agent(messages, system)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    # ---- triage
    def _triage(self, text: str, system: str) -> str:
        # learned triage rules look like: Emails from x@y.com should be classified as ignore
        for sender, label in re.findall(r"emails from (\S+) should be classified as (\w+)", system.lower()):
            if sender in text:
                return label
        ignore_words = ["free", "win ", "sale", "webinar", "otp", "digest", "newsletter", "starred", "receipt",
                        "new jobs", "notifications", "update available", "new shows", "demo of our", "unsubscribe",
                        "% off", "cashback", "coupon", "promo", "deal", "subscription renewed", "order has been",
                        "shipped", "delivered", "no-reply", "noreply", "do not reply"]
        notify_words = ["urgent", "security", "alert", "legal", "offer letter", "results", "due", "failed",
                        "outcome", "review feedback", "unwell", "hospital", "deadline", "suspended", "breach",
                        "warning", "overdrawn", "penalty", "accepted", "rejected", "selected"]
        if any(w in text for w in ignore_words + ["demo our", "book 15 minutes"]):
            return "ignore"
        if any(w in text for w in notify_words) and "confirm" not in text:
            return "notify_human"
        if "?" in text or any(w in text for w in ["confirm", "please send", "please reply", "share", "review it",
                                                  "feedback", "let me know", "could you", "can you"]):
            return "respond"
        return "notify_human"

    # ---- ReAct agent
    def _agent(self, messages, system: str) -> AIMessage:
        email_text = str(messages[1].content)
        low = email_text.lower()
        called = [tc["name"] for m in messages if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
        last = messages[-1]
        if isinstance(last, ToolMessage) and "denied" in str(last.content).lower():
            return AIMessage(content="Done. The human denied the action.")

        day = next((d for d in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                    if d in low), "wednesday")
        scheduling = any(w in low for w in SCHEDULING_WORDS)
        if scheduling and "check_calendar_availability" not in called:
            return AIMessage(content="", tool_calls=[{"name": "check_calendar_availability",
                                                      "args": {"day": day}, "id": "call_cal"}])
        if "send_email" not in called:
            sender = re.search(r"from:\s*(\S+)", email_text, re.I)
            subj = re.search(r"subject:\s*(.+)", email_text, re.I)
            to = sender.group(1) if sender else "sender"
            line = (f"{day.capitalize()} works for me, I will be available."
                    if scheduling else "I have noted this and will get back to you shortly.")
            body = f"Hi {sender_name(to)},\n\nThanks for your email. {line}\n\nBest regards,\nRavi"
            body = apply_name_preferences(body, system)
            return AIMessage(content="", tool_calls=[{"name": "send_email", "id": "call_send", "args": {
                "to": to, "subject": "Re: " + (subj.group(1).strip() if subj else ""), "body": body}}])
        return AIMessage(content="Done.")

    # ---- memory extraction
    def _memory(self, text: str) -> str:
        fb = re.search(r"FEEDBACK:\s*(.*)", text)
        if fb and fb.group(1).strip() and fb.group(1).strip().lower() != "(none)":
            return fb.group(1).strip()
        orig = re.search(r"ORIGINAL:\s*(.*?)\nEDITED:", text, re.S)
        edit = re.search(r"EDITED:\s*(.*?)\nFEEDBACK:", text, re.S)
        if orig and edit:
            a, b = re.findall(r"\w+", orig.group(1)), re.findall(r"\w+", edit.group(1))
            for x, y in zip(a, b):
                if x != y:
                    return f'Use "{y}" instead of "{x}" when writing emails.'
        return "NONE"

    # ---- LLM-as-a-judge
    def _judge(self, text: str) -> str:
        reply = text.split("AGENT REPLY:")[-1].lower()
        kp = re.search(r"KEY POINTS:\s*(.*?)\n", text)
        points = [p.strip().lower() for p in (kp.group(1).split(";") if kp else []) if p.strip()]
        hit = sum(any(w in reply for w in p.split()) for p in points) / len(points) if points else 1
        tone = 5 if any(w in reply for w in ["thanks", "thank you", "regards"]) else 3
        correctness = max(1, round(1 + 4 * hit))
        helpful = max(1, round((correctness + tone) / 2) - 1)
        return json.dumps({"helpfulness": helpful, "tone": tone, "correctness": correctness,
                           "reasoning": "fake keyword judge"})
