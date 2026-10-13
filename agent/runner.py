"""High-level helpers shared by the CLI (main.py), the UI (app.py), the ambient loop (ambient.py)
and the evaluation scripts.

    runner = AgentRunner()
    res = runner.process(email)              # -> status 'waiting_approval' + res['pending'] if it paused
    res = runner.resume(res['thread_id'], {'action': 'approve'})
"""
import uuid

from langgraph.types import Command

from .graph import build_graph, get_checkpointer
from .llm import get_llm
from .memory import MemoryStore


class AgentRunner:
    def __init__(self, llm=None, memory: MemoryStore | None = None, checkpointer=None):
        self.llm = llm or get_llm()
        self.memory = memory or MemoryStore()
        self.checkpointer = checkpointer or get_checkpointer()
        self.graph = build_graph(self.llm, self.memory, self.checkpointer)

    @staticmethod
    def config(thread_id: str, email: dict | None = None) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 40,
            "run_name": "ambient-email-agent",
            "tags": ["email-agent"],
            "metadata": {"email_id": (email or {}).get("id"), "thread_id": thread_id},
        }

    def process(self, email: dict, thread_id: str | None = None) -> dict:
        thread_id = thread_id or f"{email.get('id', 'email')}-{uuid.uuid4().hex[:8]}"
        self.memory.upsert_run(thread_id, email, status="running")
        result = self.graph.invoke({"email": email}, self.config(thread_id, email))
        return self._summarise(thread_id, email, result)

    def resume(self, thread_id: str, decision) -> dict:
        state = self.graph.get_state(self.config(thread_id))
        email = state.values.get("email", {})
        result = self.graph.invoke(Command(resume=decision), self.config(thread_id, email))
        return self._summarise(thread_id, email, result)

    def _summarise(self, thread_id: str, email: dict, result: dict) -> dict:
        interrupts = result.get("__interrupt__") or []
        pending = interrupts[0].value if interrupts else None
        status = "waiting_approval" if pending else result.get("status", "done")
        self.memory.upsert_run(thread_id, email, triage=result.get("triage"), status=status, pending=pending)
        return {
            "thread_id": thread_id,
            "email": email,
            "triage": result.get("triage"),
            "status": status,
            "pending": pending,
            "messages": result.get("messages", []),
            "learned": result.get("learned", []),
        }

    def trajectory(self, thread_id: str) -> list[str]:
        """Node names visited so far (oldest first) - used by the HITL trajectory evaluation."""
        nodes = []
        for snap in reversed(list(self.graph.get_state_history(self.config(thread_id)))):
            for name in snap.next:              # nodes scheduled to run after this checkpoint
                # the paused checkpoint repeats the node it is waiting in -> skip consecutive duplicates
                if name != "__start__" and (not nodes or nodes[-1] != name):
                    nodes.append(name)
        return nodes

    def correct_triage(self, email: dict, correct_label: str) -> None:
        """Human says the triage was wrong -> store a triage rule for this sender."""
        sender = email.get("from", "").strip()
        self.memory.add_preference(f"Emails from {sender} should be classified as {correct_label}",
                                   kind="triage", source="triage_correction")


def tool_calls_of(messages) -> list[dict]:
    return [tc for m in messages for tc in (getattr(m, "tool_calls", None) or [])]
