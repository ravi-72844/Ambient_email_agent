"""Tools the ReAct agent can call.

SAFE tools       -> run automatically (they only READ).
DANGEROUS tools  -> change the real world (send mail / create invites). The graph PAUSES with
                    interrupt() before running them and waits for the human (Approve / Edit / Deny).

The actual work is done by the back-end in agent/services.py (mock or real Google APIs).
"""
from langchain_core.tools import tool

from .services import get_backend


@tool
def check_calendar_availability(day: str) -> str:
    """Check the user's calendar for a day (weekday name like 'wednesday' or a date 'YYYY-MM-DD')
    and return the busy slots."""
    return get_backend().check_availability(day)


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email reply. DANGEROUS: requires human approval before it runs."""
    return get_backend().send_email(to, subject, body)


@tool
def create_calendar_invite(title: str, day: str, start_time: str, duration_minutes: int = 30,
                           attendees: list[str] | None = None) -> str:
    """Create a calendar event and invite attendees. day = weekday name or YYYY-MM-DD,
    start_time = 'HH:MM' (24h). DANGEROUS: requires human approval before it runs."""
    return get_backend().create_event(title, day, start_time, duration_minutes, attendees)


SAFE_TOOLS = [check_calendar_availability]
DANGEROUS_TOOLS = [send_email, create_calendar_invite]
ALL_TOOLS = SAFE_TOOLS + DANGEROUS_TOOLS

SAFE_TOOL_NAMES = {t.name for t in SAFE_TOOLS}
DANGEROUS_TOOL_NAMES = {t.name for t in DANGEROUS_TOOLS}


def run_tool(name: str, args: dict, email: dict | None = None) -> str:
    """Execute a tool. For send_email we pass the Gmail thread info so the reply lands in the same thread."""
    backend = get_backend()
    if name == "send_email" and email:
        return backend.send_email(args.get("to"), args.get("subject"), args.get("body"),
                                  thread_id=email.get("thread_id"), message_id=email.get("message_id"))
    tool_map = {t.name: t for t in ALL_TOOLS}
    if name not in tool_map:
        return f"Unknown tool '{name}'."
    try:
        return str(tool_map[name].invoke(args))
    except Exception as exc:          # tool errors go back to the LLM instead of crashing the graph
        return f"Tool error: {exc}"
