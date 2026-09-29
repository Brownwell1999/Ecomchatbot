"""Agent mode loop: tools chosen by the (scripted) LLM are run and recorded; loops are stopped."""

from itertools import repeat

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from services.chat_service.app.agent import ShopAgent
from services.chat_service.app.graph import Trace
from shared.config import Settings


class FakeStore:
    async def search_products(self, **params):
        return {"items": [{"id": 1, "name": "Sonix Pro Wireless Earbuds", "price": 123.95}]}


class FakeKB:
    async def search(self, query, k):
        return []


class ScriptedLLM:
    """Stands in for LLM: with_tools() returns a model that replies from a script."""

    def __init__(self, replies):
        self.replies = iter(replies)

    def with_tools(self, tools):
        return RunnableLambda(lambda _: next(self.replies))


def search_call(call_id: str) -> AIMessage:
    return AIMessage(content="Let me search the catalog.", tool_calls=[
        {"name": "search_products", "args": {"query": "earbuds"}, "id": call_id}])


def make_agent(replies, max_steps=3) -> ShopAgent:
    settings = Settings(agent_max_steps=max_steps)
    return ShopAgent(ScriptedLLM(replies), FakeStore(), FakeKB(), settings)


async def test_agent_calls_chosen_tool_then_answers():
    agent = make_agent([search_call("1"), AIMessage(content="The Sonix Pro earbuds cost $123.95.")])
    trace = Trace()
    result = await agent.run("cheapest earbuds?", [], None, trace)

    assert result["stopped_reason"] == "final_answer"
    assert result["reply"] == "The Sonix Pro earbuds cost $123.95."
    assert [c.name for c in trace.tool_calls] == ["search_products"]  # recorded via call_tool
    assert [s.tool for s in result["steps"]] == ["search_products", None]


async def test_agent_stops_an_endless_tool_loop():
    agent = make_agent((search_call(str(i)) for i in repeat(0)), max_steps=3)
    result = await agent.run("loop forever", [], None, Trace())

    assert result["stopped_reason"] == "max_steps"
    assert len(result["steps"]) == 3


async def test_agent_unavailable_without_a_tool_calling_model():
    class FakeOnlyLLM:
        def with_tools(self, tools):
            return None

    agent = ShopAgent(FakeOnlyLLM(), FakeStore(), FakeKB(), Settings())
    result = await agent.run("hi", [], None, Trace())
    assert result["stopped_reason"] == "unavailable"
