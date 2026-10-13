"""Milestones 1 + 2 in LangSmith: upload the 105-email dataset and run an experiment with
code evaluators (triage correctness) + LLM-as-a-judge evaluators (helpfulness / tone / correctness).

Needs in .env:  LANGSMITH_API_KEY=...   LANGSMITH_TRACING=true   (and GOOGLE_API_KEY for real numbers)

  python -m evals.langsmith_eval                  # upload dataset (first time) + run experiment
  python -m evals.langsmith_eval --limit 20       # smaller experiment
Then open https://smith.langchain.com -> Datasets & Experiments -> 'ambient-email-agent-eval'.
"""
import argparse
import os

from evals.common import DATASET, banner, fresh_runner, load, proposed_reply, run_until_reply
from agent.judge import CRITERIA, judge_reply

DATASET_NAME = "ambient-email-agent-eval"


def upload_dataset(client, emails: list[dict]) -> None:
    if client.has_dataset(dataset_name=DATASET_NAME):
        print(f"Dataset '{DATASET_NAME}' already exists in LangSmith - reusing it.")
        return
    ds = client.create_dataset(DATASET_NAME, description="105 emails with human triage labels and ideal replies")
    client.create_examples(dataset_id=ds.id, examples=[{
        "inputs": {"email": {k: e[k] for k in ("id", "from", "subject", "body")}},
        "outputs": {"label": e["label"], "ideal_reply": e.get("ideal_reply", ""),
                    "key_points": e.get("key_points", []), "expected_tools": e.get("expected_tools", [])},
    } for e in emails])
    print(f"Uploaded {len(emails)} examples to dataset '{DATASET_NAME}'.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--concurrency", type=int, default=1, help="keep 1 on the Gemini free tier")
    args = p.parse_args()

    if not os.getenv("LANGSMITH_API_KEY"):
        raise SystemExit("Set LANGSMITH_API_KEY in .env first (https://smith.langchain.com -> Settings -> API Keys).")
    from langsmith import Client, evaluate

    banner()
    client = Client()
    upload_dataset(client, load(DATASET))
    runner = fresh_runner()

    # ---------------- target: what we evaluate
    def target(inputs: dict) -> dict:
        res = run_until_reply(runner, inputs["email"])
        return {"triage": res["triage"], "reply": proposed_reply(res),
                "paused_for_approval": res["status"] == "waiting_approval"}

    # ---------------- evaluators
    def triage_correct(outputs: dict, reference_outputs: dict) -> dict:
        return {"key": "triage_correct", "score": int(outputs["triage"] == reference_outputs["label"])}

    def hitl_paused(outputs: dict, reference_outputs: dict) -> dict:
        if reference_outputs["label"] != "respond" or outputs["triage"] != "respond":
            return {"key": "hitl_paused", "score": None}
        return {"key": "hitl_paused", "score": int(outputs["paused_for_approval"])}

    def llm_judge(inputs: dict, outputs: dict, reference_outputs: dict) -> list[dict] | dict:
        if reference_outputs["label"] != "respond":
            return {"key": "quality", "score": None}
        s = judge_reply(runner.llm, inputs["email"], outputs["reply"],
                        reference_outputs.get("ideal_reply", ""), reference_outputs.get("key_points"))
        return {"results": [{"key": c, "score": s[c] / 5} for c in CRITERIA] +
                           [{"key": "quality", "score": s["score"], "comment": s["reasoning"]}]}

    data = client.list_examples(dataset_name=DATASET_NAME, limit=args.limit or None)
    results = evaluate(target, data=data, evaluators=[triage_correct, hitl_paused, llm_judge],
                       experiment_prefix="gemini-agent", max_concurrency=args.concurrency)
    print("\nExperiment finished. Open the link above (or LangSmith -> Datasets & Experiments) to see the scores.")
    return results


if __name__ == "__main__":
    main()
