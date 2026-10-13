"""Offline tests (FakeLLM + mock Gmail). Run with:  pytest -q"""
import json

from agent.graph import parse_label
from agent.services import get_backend

SPAM = {"id": "t1", "from": "deals@shopnow.biz", "subject": "WIN a FREE iPhone!!!", "body": "Click now!"}
ALERT = {"id": "t2", "from": "alerts@monitoring.com", "subject": "URGENT: Production server down",
         "body": "The production API is unreachable."}
MEETING = {"id": "t3", "from": "lead@company.com", "subject": "Sync call",
           "body": "Can we have a call on Wednesday? What time works for you?"}
BOB = {"id": "t4", "from": "bob.sharma@company.com", "subject": "Report",
       "body": "Hi Ravi, can you send me the report by tomorrow?"}


def test_parse_label_defaults_to_human():
    assert parse_label("I am not sure") == "notify_human"
    assert parse_label("respond") == "respond"


def test_dataset_has_100_plus_examples():
    data = json.load(open("data/eval_dataset.json", encoding="utf-8"))
    assert len(data) >= 100
    assert all(e["label"] in {"ignore", "notify_human", "respond"} for e in data)
    assert all("ideal_reply" in e for e in data if e["label"] == "respond")


def test_ignore_and_notify_end_without_tools(runner):
    assert runner.process(SPAM)["status"] == "ignored"
    assert runner.process(ALERT)["status"] == "notified"


def test_safe_tool_runs_but_send_email_pauses(runner):
    res = runner.process(MEETING)
    assert res["status"] == "waiting_approval"
    assert res["pending"]["tool"] == "send_email"
    assert any(m.type == "tool" and "wednesday" in m.content.lower() for m in res["messages"])  # calendar ran
    assert get_backend().sent == []                                                          # nothing sent yet


def test_approve_sends(runner):
    res = runner.process(MEETING)
    res = runner.resume(res["thread_id"], {"action": "approve"})
    assert res["status"] == "done"
    assert len(get_backend().sent) == 1


def test_deny_stops_and_sends_nothing(runner):
    res = runner.process(MEETING)
    res = runner.resume(res["thread_id"], {"action": "deny"})
    assert res["status"] == "denied"
    assert get_backend().sent == []


def test_edit_sends_edited_text_and_learns(runner):
    res = runner.process(BOB)
    draft = res["pending"]["args"]["body"]
    assert "Bob" in draft
    res = runner.resume(res["thread_id"], {"action": "edit", "args": {"body": draft.replace("Bob", "Robert")}})
    assert "Robert" in get_backend().sent[-1]["body"]
    assert res["learned"]
    # memory is used on the next email from Bob
    res2 = runner.process({**BOB, "id": "t5", "subject": "Notes", "body": "Could you share the notes?"})
    assert "Robert" in res2["pending"]["args"]["body"]


def test_triage_correction_is_remembered(runner):
    assert runner.process({**ALERT, "id": "t6"})["triage"] == "notify_human"
    runner.correct_triage(ALERT, "ignore")
    assert runner.process({**ALERT, "id": "t7"})["triage"] == "ignore"


def test_trajectory(runner):
    res = runner.process(MEETING)
    assert runner.trajectory(res["thread_id"]) == ["load_memory", "triage", "agent", "act", "agent", "act"]
