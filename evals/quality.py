"""Milestone 2 evaluation: AGENT QUALITY SCORE with LLM-as-a-judge (local version).

For every email in the 105-email dataset:
  * triage is checked against the human label
  * for 'respond' emails the agent drafts a reply (graph pauses at the send_email approval)
  * the judge scores helpfulness / tone / correctness (1-5) against the ideal reply + key points

  python -m evals.quality --delay 4
  python -m evals.quality --limit 10          # quick run
(The LangSmith version of the same evaluation is evals/langsmith_eval.py)
"""
import argparse
from statistics import mean

from evals.common import DATASET, banner, fresh_runner, load, pause, proposed_reply, run_until_reply, save
from agent.judge import CRITERIA, judge_reply


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default=DATASET)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--delay", type=float, default=0)
    args = p.parse_args()

    banner()
    emails = load(args.dataset)
    if args.limit:
        emails = emails[: args.limit]
    runner = fresh_runner()
    rows = []
    for i, e in enumerate(emails, 1):
        res = run_until_reply(runner, e)
        row = {"id": e["id"], "label": e["label"], "triage": res["triage"], "triage_ok": res["triage"] == e["label"]}
        if e["label"] == "respond":
            reply = proposed_reply(res)
            row["reply"] = reply
            row.update(judge_reply(runner.llm, e, reply, e.get("ideal_reply", ""), e.get("key_points")))
        rows.append(row)
        status = f"score={row['score']:.2f}" if "score" in row else ""
        print(f"[{i:3}/{len(emails)}] {e['id']} triage={res['triage']:<13} {'OK ' if row['triage_ok'] else 'MISS'} {status}")
        pause(args.delay)

    judged = [r for r in rows if "score" in r]
    summary = {
        "cases_run": len(rows),
        "triage_accuracy": round(mean(r["triage_ok"] for r in rows), 3),
        "judged_replies": len(judged),
        **({f"avg_{c}": round(mean(r[c] for r in judged), 2) for c in CRITERIA} if judged else {}),
        "quality_score_0_1": round(mean(r["score"] for r in judged), 3) if judged else None,
    }
    print("\n=== Agent Quality Report ===")
    for k, v in summary.items():
        print(f"{k:20}: {v}")
    print("saved ->", save("quality_results.json", {"summary": summary, "rows": rows}))


if __name__ == "__main__":
    main()
