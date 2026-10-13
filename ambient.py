"""The 'ambient' part: run the agent in the background on a REAL Gmail inbox.

Every POLL_SECONDS it fetches unread inbox emails and runs each one through the graph:
  ignore        -> archived in Gmail
  notify_human  -> starred + marked important
  respond       -> agent drafts the reply and PAUSES; the approval appears in the UI
                   (streamlit run app.py -> 'Pending approvals'), where you Approve / Edit / Deny.

  EMAIL_BACKEND=google python ambient.py            # needs credentials.json, see docs/GMAIL_SETUP.md
  python ambient.py --once                          # single pass, then exit
"""
import argparse
import os
import time

from dotenv import load_dotenv

load_dotenv()

from agent.runner import AgentRunner  # noqa: E402
from agent.services import get_backend  # noqa: E402


def poll_once(runner: AgentRunner, max_emails: int) -> int:
    backend = get_backend()
    emails = backend.fetch_unread(max_results=max_emails)
    new = 0
    for g in emails:
        thread_id = f"gmail-{g['id']}"
        if runner.memory.has_run(thread_id):
            continue                       # already processed (maybe still waiting for approval)
        email = {**g, "gmail_id": g["id"]}
        res = runner.process(email, thread_id=thread_id)
        if hasattr(backend, "mark_read") and res["triage"] != "ignore":
            backend.mark_read(g["id"])
        print(f"  {g['subject'][:60]:60} -> {res['triage']:13} {res['status']}")
        new += 1
    return new


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int, default=int(os.getenv("POLL_SECONDS", "60")))
    p.add_argument("--max", type=int, default=10)
    args = p.parse_args()

    backend = get_backend()
    if backend.name != "google":
        print("EMAIL_BACKEND is 'mock' -> there is no real inbox to watch. Set EMAIL_BACKEND=google in .env.")
        return
    runner = AgentRunner()
    print(f"Ambient agent watching Gmail every {args.interval}s. Ctrl+C to stop.")
    while True:
        print(time.strftime("[%H:%M:%S]"), "checking inbox ...")
        n = poll_once(runner, args.max)
        if n == 0:
            print("  no new emails")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
