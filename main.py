"""Command-line demo: run emails from the dataset through the agent and answer the HITL prompts.

  python main.py              -> runs e23 (interview confirmation)
  python main.py e29          -> runs one email
  python main.py --all        -> runs every email in the golden set
  python main.py e29 --auto approve|deny   -> no prompts (useful for quick demos)
"""
import argparse
import json

from dotenv import load_dotenv

load_dotenv()

from agent.llm import using_real_llm  # noqa: E402
from agent.runner import AgentRunner  # noqa: E402
from agent.services import get_backend  # noqa: E402


def ask_human(pending: dict) -> dict:
    print("\n   ⏸  HUMAN APPROVAL NEEDED")
    print(f"   tool : {pending['tool']}")
    for k, v in pending["args"].items():
        print(f"   {k:5}: " + str(v).replace("\n", "\n          "))
    while True:
        choice = input("   [a]pprove / [e]dit / [d]eny > ").strip().lower()[:1]
        if choice == "a":
            return {"action": "approve"}
        if choice == "d":
            return {"action": "deny", "feedback": input("   why? (optional) > ").strip()}
        if choice == "e":
            field = "body" if "body" in pending["args"] else input("   field to edit > ").strip()
            print(f"   type the new {field}. Finish with an empty line:")
            lines = []
            while (line := input("   | ")) != "":
                lines.append(line)
            feedback = input("   feedback for the agent to remember (optional) > ").strip()
            return {"action": "edit", "args": {field: "\n".join(lines)}, "feedback": feedback}


def show(res: dict) -> None:
    for m in res["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            print(f"   -> tool call  : {tc['name']}({json.dumps(tc['args'])[:150]})")
        if m.type == "tool":
            print(f"   <- tool result: {m.content}")


def run(runner: AgentRunner, email: dict, auto: str | None) -> None:
    print(f"\n[{email['id']}] {email['subject']}  (from {email['from']})")
    res = runner.process(email)
    print(f"   triage = {res['triage']}" + (f"   (human label: {email['label']})" if "label" in email else ""))
    while res["status"] == "waiting_approval":
        decision = {"action": auto} if auto else ask_human(res["pending"])
        res = runner.resume(res["thread_id"], decision)
    show(res)
    if res["learned"]:
        print(f"   🧠 learned: {res['learned']}")
    print(f"   status = {res['status']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("email_id", nargs="?", default="e23")
    p.add_argument("--all", action="store_true")
    p.add_argument("--dataset", default="data/golden_set.json")
    p.add_argument("--auto", choices=["approve", "deny"])
    args = p.parse_args()

    print("LLM:", "Gemini" if using_real_llm() else "FAKE LLM (no GOOGLE_API_KEY found)",
          "| email backend:", get_backend().name)
    emails = json.load(open(args.dataset, encoding="utf-8"))
    runner = AgentRunner()
    selected = emails if args.all else [e for e in emails if e["id"] == args.email_id]
    if not selected:
        raise SystemExit(f"No email with id {args.email_id} in {args.dataset}")
    for e in selected:
        run(runner, e, args.auto)


if __name__ == "__main__":
    main()
