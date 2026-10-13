
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from .llm import get_llm, text_of
from .memory import MemoryStore, format_preferences
from .services import get_backend
from .tools import ALL_TOOLS, DANGEROUS_TOOL_NAMES, run_tool

LABELS = ["ignore", "notify_human", "respond"]
MAX_AGENT_STEPS = 8

TRIAGE_PROMPT = """TRIAGE. You are an email triage assistant for Ravi, a software developer and student.
Classify the email into exactly ONE category:
- ignore: spam, promotions, newsletters, automated notifications, receipts, OTPs, cold sales pitches.
- notify_human: important, urgent or sensitive information Ravi must personally see, but no reply is needed \
from the assistant (alerts, offers, legal, security, results, payments, family emergencies).
- respond: a real person is asking something or expecting a reply (scheduling, questions, requests, confirmations).

Rules learned from Ravi's past corrections (follow them, they override the defaults above):
{triage_prefs}

Reply with ONLY the category name."""

AGENT_PROMPT = """ASSISTANT. You are Ravi's email assistant. Today is {today}.
Handle the email using the tools, ONE tool call at a time:
1. If a meeting/call/time is involved, FIRST call check_calendar_availability for the day mentioned.
2. If Ravi is free and a meeting time is agreed, you may call create_calendar_invite.
3. Then call send_email with a short, polite, professional reply to the sender, signed 'Ravi'.
   Keep the subject as 'Re: <original subject>'. Do not invent facts or attachments; if something is
   needed from Ravi (documents, files), say he will send it shortly.
4. After the email has been sent (or the human denied it), reply with 'Done.' and nothing else.

send_email and create_calendar_invite need human approval; the human may edit them.

Ravi's preferences learned from past feedback (ALWAYS follow them):
{prefs}"""

MEMORY_PROMPT = """MEMORY. The user edited an action proposed by their email assistant.
Compare ORIGINAL and EDITED (and the optional FEEDBACK) and write ONE short, general, reusable
preference the assistant should follow in future emails (e.g. 'Address Bob Sharma as "Robert".' or
'Sign emails as "Ravi Kumawat".'). If the edit is a one-off content change with no reusable lesson,
reply with exactly NONE."""


class AgentState(TypedDict, total=False):
    email: dict
    triage: str
    preferences: str
    triage_preferences: str
    messages: Annotated[list, add_messages]
    status: str                # ignored / notified / done / denied
    learned: list              # preferences learned during this run


def format_email(e: dict) -> str:
    return f"From: {e['from']}\nSubject: {e['subject']}\nBody: {e['body']}"


def parse_label(text: str) -> str:
    t = text.lower()
    for label in ["notify_human", "ignore", "respond"]:
        if label in t:
            return label
    return "notify_human"   # unsure -> safest option: show it to the human


def normalise_decision(decision) -> dict:
    """Accept 'approve' / {'action': 'edit', 'args': {...}, 'feedback': '...'} etc."""
    if isinstance(decision, str):
        decision = {"action": decision}
    action = str(decision.get("action", "deny")).lower()
    if action not in {"approve", "edit", "deny"}:
        action = "deny"
    return {**decision, "action": action}


def build_graph(llm=None, memory: MemoryStore | None = None, checkpointer=None):
    llm = llm or get_llm()
    memory = memory or MemoryStore()
    tool_llm = llm.bind_tools(ALL_TOOLS)

    # ------------------------------------------------------------------ nodes
    def load_memory(state: AgentState):
        return {
            "preferences": format_preferences(memory.get_preferences("response")),
            "triage_preferences": format_preferences(memory.get_preferences("triage")),
            "learned": [],
        }

    def triage_node(state: AgentState):
        prompt = TRIAGE_PROMPT.format(triage_prefs=state.get("triage_preferences", "(none yet)"))
        resp = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=format_email(state["email"]))])
        label = parse_label(text_of(resp))
        out = {"triage": label}
        if label == "respond":
            out["messages"] = [HumanMessage(content=format_email(state["email"]))]
        return out

    def archive_node(state: AgentState):
        if state["email"].get("gmail_id"):
            get_backend().archive(state["email"]["gmail_id"])
        return {"status": "ignored"}

    def notify_node(state: AgentState):
        if state["email"].get("gmail_id"):
            get_backend().flag(state["email"]["gmail_id"])
        return {"status": "notified"}

    def agent_node(state: AgentState):
        prompt = AGENT_PROMPT.format(today=date.today().strftime("%A %Y-%m-%d"),
                                     prefs=state.get("preferences", "(none yet)"))
        resp = tool_llm.invoke([SystemMessage(content=prompt)] + state["messages"])
        for tc in resp.tool_calls or []:          # some models return "\\n" instead of real new lines
            if isinstance(tc["args"].get("body"), str):
                tc["args"]["body"] = tc["args"]["body"].replace("\\n", "\n")
        return {"messages": [resp]}

    def act_node(state: AgentState):
        last: AIMessage = state["messages"][-1]
        calls = last.tool_calls

        # Phase 1: collect a human decision for every dangerous call. interrupt() pauses the graph here.
        # (No side effects happen before this point, so re-running the node on resume is safe.)
        decisions = {}
        for tc in calls:
            if tc["name"] in DANGEROUS_TOOL_NAMES:
                decisions[tc["id"]] = normalise_decision(interrupt({
                    "tool": tc["name"],
                    "args": tc["args"],
                    "email": {k: state["email"].get(k) for k in ("id", "from", "subject")},
                    "options": ["approve", "edit", "deny"],
                }))

        # Phase 2: execute.
        out_msgs, learned, denied = [], list(state.get("learned", [])), False
        for tc in calls:
            d = decisions.get(tc["id"])
            if d is None:                                         # safe tool -> run automatically
                result = run_tool(tc["name"], tc["args"], state["email"])
            elif d["action"] == "deny":
                denied = True
                result = "Action DENIED by the human. Do not retry. Stop." + (
                    f" Feedback: {d['feedback']}" if d.get("feedback") else "")
            elif d["action"] == "edit":
                new_args = {**tc["args"], **(d.get("args") or {})}
                pref = learn_from_edit(tc["name"], tc["args"], new_args, d.get("feedback", ""))
                if pref:
                    learned.append(pref)
                result = run_tool(tc["name"], new_args, state["email"]) + " (sent with the human's edits)"
            else:                                                 # approve
                result = run_tool(tc["name"], tc["args"], state["email"])
            out_msgs.append(ToolMessage(content=result, tool_call_id=tc["id"], name=tc["name"]))

        update = {"messages": out_msgs, "learned": learned}
        if denied:
            update["status"] = "denied"
        return update

    def learn_from_edit(tool_name, old_args, new_args, feedback) -> str | None:
        """Milestone 4 'learning': turn a human edit into a stored preference."""
        def show(a):
            return a.get("body") if tool_name == "send_email" else str(a)
        resp = llm.invoke([
            SystemMessage(content=MEMORY_PROMPT),
            HumanMessage(content=f"TOOL: {tool_name}\nORIGINAL: {show(old_args)}\nEDITED: {show(new_args)}\n"
                                 f"FEEDBACK: {feedback or '(none)'}"),
        ])
        pref = text_of(resp).strip().strip('"').strip()
        if not pref or pref.upper().startswith("NONE"):
            return None
        memory.add_preference(pref, kind="response", source="hitl_edit")
        return pref

    def finish_node(state: AgentState):
        return {"status": state.get("status") or "done"}

    # ------------------------------------------------------------------ routing
    def route_after_triage(state: AgentState) -> str:
        return {"ignore": "archive", "notify_human": "notify"}.get(state["triage"], "agent")

    def route_after_agent(state: AgentState) -> str:
        steps = sum(isinstance(m, AIMessage) for m in state["messages"])
        if state["messages"][-1].tool_calls and steps <= MAX_AGENT_STEPS:
            return "act"
        return "finish"

    def route_after_act(state: AgentState) -> str:
        return "finish" if state.get("status") == "denied" else "agent"

    # ------------------------------------------------------------------ wiring
    g = StateGraph(AgentState)
    g.add_node("load_memory", load_memory)
    g.add_node("triage", triage_node)
    g.add_node("archive", archive_node)
    g.add_node("notify", notify_node)
    g.add_node("agent", agent_node)
    g.add_node("act", act_node)
    g.add_node("finish", finish_node)

    g.add_edge(START, "load_memory")
    g.add_edge("load_memory", "triage")
    g.add_conditional_edges("triage", route_after_triage, ["archive", "notify", "agent"])
    g.add_edge("archive", END)
    g.add_edge("notify", END)
    g.add_conditional_edges("agent", route_after_agent, ["act", "finish"])
    g.add_conditional_edges("act", route_after_act, ["agent", "finish"])
    g.add_edge("finish", END)

    return g.compile(checkpointer=checkpointer)


def triage_email(email: dict, llm=None, triage_prefs: str = "(none yet)") -> str:
    """Triage only, without running the rest of the graph (used by evaluate.py)."""
    llm = llm or get_llm()
    resp = llm.invoke([SystemMessage(content=TRIAGE_PROMPT.format(triage_prefs=triage_prefs)),
                       HumanMessage(content=format_email(email))])
    return parse_label(text_of(resp))


def get_checkpointer(path: str = "data/checkpoints.db"):
    """SQLite checkpointer so paused (interrupted) runs survive restarts of the app."""
    import os
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
