"""Shared helpers for the evaluation scripts."""
import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from agent.llm import using_real_llm  # noqa: E402
from agent.memory import MemoryStore  # noqa: E402
from agent.runner import AgentRunner  # noqa: E402
from agent.services import MockBackend, set_backend  # noqa: E402

GOLDEN = "data/golden_set.json"
DATASET = "data/eval_dataset.json"


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fresh_runner(llm=None) -> AgentRunner:
    """Isolated runner: in-memory checkpoints, empty memory, mock email/calendar (evals never send real mail)."""
    set_backend(MockBackend())
    return AgentRunner(llm=llm, memory=MemoryStore(":memory:"), checkpointer=InMemorySaver())


def banner() -> None:
    print("LLM:", "Gemini (" + os.getenv("GEMINI_MODEL", "gemini-3.8-flash") + ")" if using_real_llm()
          else "FAKE LLM - pipeline test only, numbers are NOT a real benchmark")
    if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
        print("LangSmith tracing ON -> project:", os.getenv("LANGSMITH_PROJECT", "default"))


def save(name: str, data) -> str:
    os.makedirs("results", exist_ok=True)
    path = f"results/{name}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    return path


def pause(seconds: float) -> None:
    if seconds:
        time.sleep(seconds)


def proposed_reply(res: dict) -> str:
    """Body of the send_email the agent wants to send (the graph is paused waiting for approval)."""
    p = res.get("pending") or {}
    return (p.get("args") or {}).get("body", "") if p.get("tool") == "send_email" else ""


def run_until_reply(runner: AgentRunner, email: dict, max_interrupts: int = 4) -> dict:
    """Run the agent; auto-approve calendar invites until it proposes a send_email (then stop, still paused)."""
    res = runner.process(email)
    for _ in range(max_interrupts):
        p = res.get("pending")
        if not p or p.get("tool") == "send_email":
            break
        res = runner.resume(res["thread_id"], {"action": "approve"})
    return res
