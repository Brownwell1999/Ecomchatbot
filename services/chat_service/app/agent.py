"""Agent mode (AI Testing Lab, opt-in): the LLM decides which tools to call, in a loop.

The default ShopBot flow is a fixed workflow (graph.py: intent -> node -> fixed tools).
Here the LLM gets the same store tools plus search_policies and chooses for itself:

    loop (max agent_max_steps):
        LLM(prompt + history + scratchpad) -> tool calls?  no  -> final answer
                                              yes -> run each tool, add results to scratchpad

Every step is recorded (thought, tool, args) so agentic metrics can grade it.
"""

import json

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool

from shared.config import Settings

from .llm import LLM
from .prompts import AGENT_PROMPT
from .rag import Retriever
from .schemas import AgentStep
from .tools import StoreClient, build_commerce_tools, build_tools, call_tool

MAX_STEPS_REPLY = ("Sorry, I couldn't finish that request. Could you rephrase it, or ask me one "
                   "thing at a time?")
UNAVAILABLE_REPLY = "Agent mode isn't available right now. Please turn it off and ask again."


class ShopAgent:
    def __init__(self, llm: LLM, store: StoreClient, kb: Retriever, settings: Settings):
        self.llm = llm
        self.store = store
        self.kb = kb
        self.max_steps = settings.agent_max_steps
        self.top_k = settings.rag_top_k

    def tools(self, user_id: int | None, trace) -> dict:
        tools = build_tools(self.store, user_id)  # same tools as the workflow, bound to the user

        @tool
        async def search_policies(query: str) -> str:
            """Search ShopEase store policies (returns, shipping, warranty, payment, account)."""
            hits = await self.kb.search(query, k=self.top_k)
            trace.chunks.extend(hits)
            used = [h for h in hits if h.used]
            return "\n\n".join(f"[{h.source} > {h.section}]\n{h.content}" for h in used) or \
                "No matching policy found."

        # + cart / checkout / place order / cancel (agent mode only)
        return {**tools, **build_commerce_tools(self.store, user_id),
                "search_policies": search_policies}

    async def run(self, message: str, history: list[BaseMessage], user_id: int | None,
                  trace) -> dict:
        tools = self.tools(user_id, trace)
        model = self.llm.with_tools(list(tools.values()))
        if model is None:  # only the fake model is configured: it can't call tools
            return {"reply": UNAVAILABLE_REPLY, "steps": [], "stopped_reason": "unavailable",
                    "grounding": message}

        steps: list[AgentStep] = []
        scratchpad: list[BaseMessage] = []
        for number in range(1, self.max_steps + 1):
            prompt = AGENT_PROMPT.invoke({"history": history, "message": message,
                                          "agent_scratchpad": scratchpad})
            ai: AIMessage = await LLM.run(model, prompt, "agent", trace.llm_calls)
            # Reasoning models (gpt-oss on Groq) put their thinking in a separate field and leave
            # the text empty when they call tools: use it as the step's thought / plan
            thought = (str(ai.content).strip()
                       or str(ai.additional_kwargs.get("reasoning_content", "")).strip())

            if not ai.tool_calls:  # no tool needed -> this is the final answer
                steps.append(AgentStep(step=number, thought=thought))
                return {"reply": thought, "steps": steps, "stopped_reason": "final_answer",
                        "grounding": self._grounding(message, trace)}

            scratchpad.append(ai)
            for call in ai.tool_calls:
                ok, result = True, None
                try:
                    result = await call_tool(tools[call["name"]], call["args"], trace.tool_calls)
                except Exception as exc:  # unknown tool, bad args, not signed in...
                    ok, result = False, f"Tool error: {exc}"
                steps.append(AgentStep(step=number, thought=thought, tool=call["name"],
                                       args=call["args"], ok=ok))
                scratchpad.append(ToolMessage(content=json.dumps(result, default=str),
                                              tool_call_id=call["id"]))

        # Safety stop: the agent kept calling tools without answering
        return {"reply": MAX_STEPS_REPLY, "steps": steps, "stopped_reason": "max_steps",
                "grounding": message}

    @staticmethod
    def _grounding(message: str, trace) -> str:
        """Text the reply may take facts from (tool outputs + used policy chunks)."""
        outputs = [json.dumps(c.output, default=str) for c in trace.tool_calls if c.ok]
        chunks = [c.content for c in trace.chunks if c.used]
        return "\n".join([message, *outputs, *chunks])
