"""Milestone 4 evaluation: MEMORY & ADAPTATION (the 'Bob -> Robert' test from the project brief).

  1. Run 'Email Bob' -> the agent drafts 'Hi Bob, ...'
  2. Human EDITS the draft: 'Hi Robert, ...' (+ feedback 'Call him Robert, not Bob')
     -> the agent stores a preference in SQLite memory
  3. Run a NEW email from Bob -> the agent should write 'Robert' on the FIRST try.

  python -m evals.memory_adaptation
Uses a temporary SQLite file so you can also open it and see the stored preference.
"""
import os
import re

from evals.common import banner, save
from langgraph.checkpoint.memory import InMemorySaver

from agent.memory import MemoryStore
from agent.runner import AgentRunner
from agent.services import MockBackend, set_backend

DB = "results/memory_test.db"

EMAIL_1 = {"id": "bob-1", "from": "bob.sharma@company.com", "subject": "Weekly report",
           "body": "Hi Ravi, can you send me the weekly progress report by tomorrow?"}
EMAIL_2 = {"id": "bob-2", "from": "bob.sharma@company.com", "subject": "Sprint retro notes",
           "body": "Hi Ravi, could you share your notes from the sprint retro?"}


def main():
    banner()
    os.makedirs("results", exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    set_backend(MockBackend())
    runner = AgentRunner(memory=MemoryStore(DB), checkpointer=InMemorySaver())

    print("\n[1] First email from Bob")
    r1 = runner.process(EMAIL_1)
    draft1 = (r1["pending"] or {}).get("args", {}).get("body", "")
    print("    draft:", draft1.replace("\n", " | "))

    print("\n[2] Human edits: Bob -> Robert")
    edited = re.sub(r"\bBob\b", "Robert", draft1) if "Bob" in draft1 else "Hi Robert,\n\n" + draft1
    r1 = runner.resume(r1["thread_id"], {"action": "edit", "args": {"body": edited},
                                         "feedback": 'Call him Robert, not Bob. Use "Robert" instead of "Bob".'})
    print("    learned:", r1["learned"])
    print("    memory  :", [p["text"] for p in runner.memory.get_preferences()])

    print("\n[3] Second email from Bob (new run, preferences loaded from SQLite)")
    runner2 = AgentRunner(memory=MemoryStore(DB), checkpointer=InMemorySaver())   # fresh process, same DB
    r2 = runner2.process(EMAIL_2)
    draft2 = (r2["pending"] or {}).get("args", {}).get("body", "")
    print("    draft:", draft2.replace("\n", " | "))

    passed = "Robert" in draft2 and not re.search(r"\bBob\b", draft2)
    print(f"\nMemory & adaptation: {'PASS' if passed else 'FAIL'} - second draft "
          f"{'uses' if passed else 'does NOT use'} 'Robert' on the first try")
    print("saved ->", save("memory_results.json", {"draft_1": draft1, "edited": edited, "learned": r1["learned"],
                                                    "draft_2": draft2, "passed": passed}))


if __name__ == "__main__":
    main()
