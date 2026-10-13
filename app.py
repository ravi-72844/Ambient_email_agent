"""Streamlit UI for the Ambient Email Agent.

  streamlit run app.py

Pages: Inbox (run the agent) · Pending approvals (HITL) · History (+ triage corrections) ·
Memory (learned preferences) · Evaluation (milestone results) · About (graph + settings)
"""
import glob
import json
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent.llm import using_real_llm  # noqa: E402
from agent.runner import AgentRunner  # noqa: E402
from agent.services import get_backend  # noqa: E402

st.set_page_config(page_title="Ambient Email Agent", page_icon="📬", layout="wide")

BADGE = {"ignore": "⚪ ignore", "notify_human": "🟠 notify_human", "respond": "🟢 respond"}
STATUS = {"waiting_approval": "⏸ waiting for approval", "done": "✅ done", "denied": "⛔ denied",
          "ignored": "🗄 archived", "notified": "🔔 flagged for you", "running": "… running"}


@st.cache_resource
def get_runner() -> AgentRunner:
    return AgentRunner()


@st.cache_data
def sample_emails() -> list[dict]:
    with open("data/eval_dataset.json", encoding="utf-8") as f:
        return json.load(f)


runner = get_runner()
backend = get_backend()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("📬 Ambient Email Agent")
st.sidebar.caption("LangGraph · Gemini · Human-in-the-loop · Memory")
pending_runs = runner.memory.get_runs("waiting_approval")
page = st.sidebar.radio("Go to", ["📥 Inbox", "⏸ Pending approvals", "📜 History",
                                  "🧠 Memory", "📊 Evaluation", "ℹ️ About"])
if pending_runs:
    st.sidebar.warning(f"⏸ {len(pending_runs)} action(s) waiting for your approval")
st.sidebar.divider()
st.sidebar.write("**LLM:**", "Gemini " + os.getenv("GEMINI_MODEL", "gemini-3.8-flash") if using_real_llm()
                 else "FAKE LLM (add GOOGLE_API_KEY)")
st.sidebar.write("**Email backend:**", backend.name)
st.sidebar.write("**LangSmith tracing:**", os.getenv("LANGSMITH_TRACING", "false"))


# ------------------------------------------------------------------ approval card (HITL)
def approval_card(run: dict, key: str) -> None:
    p = run["pending"]
    email = run["email"]
    with st.container(border=True):
        st.markdown(f"**Agent wants to run `{p['tool']}`** for *{email['subject']}* (from {email['from']})")
        args = dict(p["args"])
        edited = {}
        for field, value in args.items():
            if field == "body":
                edited[field] = st.text_area("body", value, height=180, key=f"{key}-{field}")
            elif isinstance(value, list):
                edited[field] = [x.strip() for x in st.text_input(
                    field, ", ".join(map(str, value)), key=f"{key}-{field}").split(",") if x.strip()]
            else:
                edited[field] = st.text_input(field, str(value), key=f"{key}-{field}")
        if "duration_minutes" in edited:
            try:
                edited["duration_minutes"] = int(edited["duration_minutes"])
            except ValueError:
                edited["duration_minutes"] = 30
        feedback = st.text_input("Feedback for the agent to remember (optional)",
                                 placeholder='e.g. Call him "Robert", not "Bob"', key=f"{key}-fb")
        c1, c2, c3 = st.columns(3)
        changed = {k: v for k, v in edited.items() if v != args.get(k)}
        decision = None
        if c1.button("✅ Approve", key=f"{key}-ok", use_container_width=True, disabled=bool(changed)):
            decision = {"action": "approve"}
        if c2.button("✏️ Save edits & run", key=f"{key}-edit", use_container_width=True,
                     disabled=not (changed or feedback)):
            decision = {"action": "edit", "args": changed, "feedback": feedback}
        if c3.button("⛔ Deny", key=f"{key}-deny", use_container_width=True):
            decision = {"action": "deny", "feedback": feedback}
        if changed:
            st.caption("You changed the draft - use **Save edits & run** so the agent can learn from it.")
        if decision:
            with st.spinner("Resuming the agent ..."):
                res = runner.resume(run["thread_id"], decision)
            st.session_state["last_result"] = res
            st.rerun()


def show_result(res: dict) -> None:
    st.markdown(f"**Triage:** {BADGE.get(res['triage'], res['triage'])} &nbsp; **Status:** "
                f"{STATUS.get(res['status'], res['status'])}")
    for m in res.get("messages", []):
        for tc in getattr(m, "tool_calls", None) or []:
            st.markdown(f"🛠 `{tc['name']}` → `{json.dumps(tc['args'])[:200]}`")
        if m.type == "tool":
            st.markdown(f"↩️ {m.content}")
    for pref in res.get("learned", []):
        st.success(f"🧠 Learned: {pref}")


# ------------------------------------------------------------------ pages
if page == "📥 Inbox":
    st.header("📥 Inbox")
    sources = ["Sample emails (dataset)", "Write an email"] + (["Live Gmail inbox"] if backend.name == "google" else [])
    source = st.radio("Source", sources, horizontal=True)

    email = None
    if source == "Sample emails (dataset)":
        emails = sample_emails()
        label_filter = st.multiselect("Filter by human label", ["ignore", "notify_human", "respond"])
        shown = [e for e in emails if not label_filter or e["label"] in label_filter]
        choice = st.selectbox("Pick an email", shown,
                              format_func=lambda e: f"{e['id']} · {e['subject']} — {e['from']}")
        if choice:
            email = choice
            with st.container(border=True):
                st.markdown(f"**From:** {email['from']}  \n**Subject:** {email['subject']}")
                st.write(email["body"])
                st.caption(f"Human label: {email['label']}")
    elif source == "Write an email":
        with st.form("compose"):
            frm = st.text_input("From", "bob.sharma@company.com")
            subj = st.text_input("Subject", "Quick call on Wednesday?")
            body = st.text_area("Body", "Hi Ravi, are you free for a 30 minute call on Wednesday? Let me know.")
            if st.form_submit_button("Use this email"):
                st.session_state["custom_email"] = {"id": f"custom-{abs(hash(frm + subj + body)) % 10**6}",
                                                    "from": frm, "subject": subj, "body": body}
        email = st.session_state.get("custom_email")
    else:
        if st.button("🔄 Fetch unread emails"):
            st.session_state["gmail"] = backend.fetch_unread(10)
        gm = st.session_state.get("gmail", [])
        if gm:
            choice = st.selectbox("Pick an email", gm, format_func=lambda e: f"{e['subject']} — {e['from']}")
            email = {**choice, "gmail_id": choice["id"]}
            st.write(choice["body"][:1500])

    if email and st.button("▶️ Run agent on this email", type="primary"):
        with st.spinner("Agent is thinking ..."):
            st.session_state["last_result"] = runner.process(email)
        st.rerun()

    res = st.session_state.get("last_result")
    if res:
        st.subheader("Result")
        show_result(res)
        if res["status"] == "waiting_approval":
            approval_card(res, key=f"inbox-{res['thread_id']}")

elif page.startswith("⏸"):
    st.header("⏸ Pending approvals")
    st.caption("Dangerous actions (send_email, create_calendar_invite) wait here until you decide.")
    if not pending_runs:
        st.info("Nothing is waiting for you. 🎉")
    for run in pending_runs:
        approval_card(run, key=f"pending-{run['thread_id']}")

elif page == "📜 History":
    st.header("📜 History")
    runs = runner.memory.get_runs()
    if not runs:
        st.info("No emails processed yet.")
    for run in runs:
        e = run["email"]
        with st.expander(f"{STATUS.get(run['status'], run['status'])} · {BADGE.get(run['triage'], run['triage'])} · "
                         f"{e['subject']} — {e['from']}"):
            st.write(e["body"])
            st.caption(f"thread {run['thread_id']} · updated {run['updated_at']}")
            c1, c2 = st.columns([3, 1])
            correct = c1.selectbox("Was the triage wrong? Correct label:", ["ignore", "notify_human", "respond"],
                                   index=["ignore", "notify_human", "respond"].index(run["triage"])
                                   if run["triage"] in ("ignore", "notify_human", "respond") else 0,
                                   key=f"fix-{run['thread_id']}")
            if c2.button("Teach agent", key=f"teach-{run['thread_id']}", disabled=correct == run["triage"]):
                runner.correct_triage(e, correct)
                st.success(f"Saved: emails from {e['from']} -> {correct}")
    if backend.name == "mock" and (backend.sent or backend.events):
        st.subheader("Mock outbox (nothing really sent)")
        st.json({"sent_emails": backend.sent, "calendar_events": backend.events})

elif page == "🧠 Memory":
    st.header("🧠 Learned memory")
    st.caption("Stored in SQLite (data/memory.db) and injected into every prompt.")
    for kind, title in [("response", "Reply preferences"), ("triage", "Triage rules")]:
        st.subheader(title)
        prefs = runner.memory.get_preferences(kind)
        if not prefs:
            st.write("_none yet_")
        for pr in prefs:
            c1, c2 = st.columns([6, 1])
            c1.markdown(f"- {pr['text']}  \n  <small>{pr['source']} · {pr['created_at']}</small>",
                        unsafe_allow_html=True)
            if c2.button("🗑", key=f"del-{pr['id']}"):
                runner.memory.delete_preference(pr["id"])
                st.rerun()
    with st.form("add_pref"):
        txt = st.text_input("Add a preference manually", placeholder='Sign emails as "Ravi Kumawat"')
        kind = st.selectbox("Type", ["response", "triage"])
        if st.form_submit_button("Add") and txt:
            runner.memory.add_preference(txt, kind=kind, source="manual")
            st.rerun()

elif page == "📊 Evaluation":
    st.header("📊 Evaluation results")
    st.caption("Generate them with the scripts in evals/ (see README). Files are read from results/.")
    files = {os.path.basename(f): f for f in glob.glob("results/*.json")}
    if not files:
        st.info("No results yet. Run e.g. `python -m evals.triage_accuracy`.")
    names = {"triage_results.json": "M1 · Triage accuracy", "quality_results.json": "M2 · LLM-as-a-judge quality",
             "hitl_results.json": "M3 · HITL trajectory", "memory_results.json": "M4 · Memory & adaptation"}
    for fname, title in names.items():
        if fname not in files:
            continue
        data = json.load(open(files[fname], encoding="utf-8"))
        st.subheader(title)
        if fname == "triage_results.json":
            st.metric("Accuracy", f"{data['accuracy']:.1%}", help="target > 80%")
            st.dataframe([r for r in data["rows"] if not r["ok"]] or [{"result": "no misses"}])
        elif fname == "quality_results.json":
            s = data["summary"]
            cols = st.columns(5)
            for col, k in zip(cols, ["triage_accuracy", "avg_helpfulness", "avg_tone", "avg_correctness",
                                     "quality_score_0_1"]):
                col.metric(k, s.get(k))
        elif fname == "hitl_results.json":
            st.metric("Trajectory accuracy", f"{data['accuracy']:.1%}", help="target 100%")
        else:
            st.metric("Bob → Robert", "PASS" if data["passed"] else "FAIL")
            st.write("2nd draft:", data["draft_2"])

else:
    st.header("ℹ️ About")
    st.markdown("""
**Workflow:** Gmail → load memory → **triage** (ignore / notify_human / respond) → **ReAct agent** →
safe tools run automatically, dangerous tools **pause for you** → approve / edit (agent learns) / deny.
""")
    try:
        st.code(runner.graph.get_graph().draw_mermaid(), language="mermaid")
    except Exception as exc:  # pragma: no cover
        st.write(exc)
