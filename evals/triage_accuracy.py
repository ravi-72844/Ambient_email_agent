"""Milestone 1 evaluation: TRIAGE ACCURACY (target > 80%).

  python -m evals.triage_accuracy                         # 35-email golden set
  python -m evals.triage_accuracy --dataset data/eval_dataset.json --delay 4
"""
import argparse
from collections import Counter, defaultdict

from evals.common import DATASET, GOLDEN, banner, load, pause, save  # noqa: F401  (loads .env first)
from agent.graph import LABELS, triage_email
from agent.llm import get_llm


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default=GOLDEN)
    p.add_argument("--delay", type=float, default=0, help="seconds between LLM calls (free-tier rate limits)")
    args = p.parse_args()

    banner()
    emails, llm = load(args.dataset), get_llm()
    rows, confusion = [], defaultdict(Counter)
    for e in emails:
        pred = triage_email(e, llm)
        ok = pred == e["label"]
        rows.append({"id": e["id"], "subject": e["subject"], "label": e["label"], "pred": pred, "ok": ok})
        confusion[e["label"]][pred] += 1
        if not ok:
            print(f"MISS {e['id']}: '{e['subject']}'  human={e['label']}  agent={pred}")
        pause(args.delay)

    correct = sum(r["ok"] for r in rows)
    acc = correct / len(rows)
    print(f"\nTriage accuracy: {acc:.1%}  ({correct}/{len(rows)})   target > 80%: {'PASS' if acc > 0.8 else 'NOT YET'}")
    print("\nConfusion matrix (rows = human label, cols = agent):")
    print(f"{'':14}" + "".join(f"{lab:>14}" for lab in LABELS))
    for lab in LABELS:
        print(f"{lab:14}" + "".join(f"{confusion[lab][c]:>14}" for c in LABELS))
    print("saved ->", save("triage_results.json", {"dataset": args.dataset, "accuracy": acc, "rows": rows}))


if __name__ == "__main__":
    main()
