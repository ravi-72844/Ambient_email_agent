import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GOOGLE_API_KEY"] = ""          # tests always use the offline FakeLLM
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["EMAIL_BACKEND"] = "mock"


@pytest.fixture
def runner():
    from langgraph.checkpoint.memory import InMemorySaver
    from agent.llm import FakeLLM
    from agent.memory import MemoryStore
    from agent.runner import AgentRunner
    from agent.services import MockBackend, set_backend
    set_backend(MockBackend())
    return AgentRunner(llm=FakeLLM(), memory=MemoryStore(":memory:"), checkpointer=InMemorySaver())
