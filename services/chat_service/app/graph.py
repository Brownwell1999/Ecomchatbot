"""Dialog management as a LangGraph state graph.

    START -> understand (NLU) --route--> products | order | my_orders | return | policy (RAG)
                                         | chat | ask_order_id | need_login | handoff
                                         | out_of_scope | return_declined          -> END
"""

import json
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from shared.config import Settings

from .llm import LLM
from .nlu import NO_RE, ORDER_ID_RE, YES_RE, NLUResult, classify
from .prompts import CHAT_PROMPT, RAG_PROMPT, RESPOND_PROMPT, TEMPLATES
from .rag import Retriever
from .schemas import (
    DialogState,
    LLMCall,
    OrderCard,
    ProductCard,
    RetrievedChunk,
    Source,
    ToolCall,
)
from .tools import StoreClient, build_tools, call_tool

FREE_RETURN_REASONS = {"defective", "damaged", "wrong_item"}
INTENT_ROUTES = {
    "product_search": "products", "order_status": "order", "order_list": "my_orders",
    "return_request": "return", "policy_question": "policy", "human_handoff": "handoff",
    "out_of_scope": "out_of_scope", "small_talk": "chat",
}


@dataclass
class Trace:
    llm_calls: list[LLMCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    chunks: list[RetrievedChunk] = field(default_factory=list)


class ChatState(TypedDict, total=False):
    # input
    message: str
    user_id: int | None
    history: list[BaseMessage]
    dialog: DialogState
    trace: Trace
    # set by nodes
    nlu: NLUResult
    nlu_source: str
    confirmed: bool
    declined: bool
    route: str
    reply: str
    products: list[ProductCard]
    order: OrderCard | None
    sources: list[Source]
    suggestions: list[str]
    next_dialog: DialogState
    grounding: str | None  # text the reply may take facts from (output guardrail)
    fallback_reply: str  # safe reply if the output guardrail blocks the LLM text


def _json(data: Any) -> str:
    return json.dumps(data, default=str, indent=1)


class ChatGraph:
    def __init__(self, llm: LLM, store: StoreClient, kb: Retriever, products: Retriever,
                 settings: Settings):
        self.llm = llm
        self.nlu_chain = llm.structured(NLUResult)
        self.store = store
        self.kb = kb
        self.product_index = products
        self.settings = settings
        self.graph = self._build()

    def _build(self):
        g = StateGraph(ChatState)
        g.add_node("understand", self.understand)
        nodes = {
            "products": self.products, "order": self.order, "my_orders": self.my_orders,
            "return": self.return_flow, "policy": self.policy, "chat": self.chat,
            "ask_order_id": self.ask_order_id, "need_login": self.template("need_login"),
            "handoff": self.template("handoff"), "out_of_scope": self.template("out_of_scope"),
            "return_declined": self.template("return_cancelled"),
        }
        for name, fn in nodes.items():
            g.add_node(name, fn)
            g.add_edge(name, END)
        g.add_edge(START, "understand")
        g.add_conditional_edges("understand", self.route, list(nodes))
        return g.compile()

    async def run(self, state: ChatState) -> ChatState:
        return await self.graph.ainvoke(state)

    # ---------- helpers ----------
    def tools(self, state: ChatState):
        return build_tools(self.store, state.get("user_id"))

    async def generate(self, prompt: ChatPromptTemplate, state: ChatState, step: str,
                       **variables) -> str:
        value = prompt.invoke({"history": state["history"], "message": state["message"],
                               **variables})
        message = await LLM.run(self.llm.chat, value, step, state["trace"].llm_calls)
        return str(message.content).strip()

    @staticmethod
    def template(key: str):
        async def node(state: ChatState) -> dict:
            return {"reply": TEMPLATES[key]}
        node.__name__ = key
        return node

    # ---------- NLU ----------
    async def understand(self, state: ChatState) -> dict:
        msg, dialog = state["message"], state["dialog"]

        # Multi-turn: answer to a pending question is resolved without the LLM
        if dialog.awaiting == "return_confirmation":
            pending = NLUResult(intent="return_request", confidence=1.0,
                                order_id=dialog.order_id, return_reason=dialog.return_reason)
            if YES_RE.match(msg):
                return {"nlu": pending, "nlu_source": "dialog", "confirmed": True}
            if NO_RE.match(msg):
                return {"nlu": pending, "nlu_source": "dialog", "declined": True}
        if dialog.awaiting == "order_id" and len(msg) < 40 and (m := ORDER_ID_RE.search(msg)):
            return {"nlu": NLUResult(intent=dialog.intent, confidence=1.0,
                                     order_id=int(m.group(1))), "nlu_source": "dialog"}

        hint = (f"Context: the bot just asked the customer for their {dialog.awaiting} "
                f"(for {dialog.intent})." if dialog.awaiting else "")
        nlu, source = await classify(self.nlu_chain, msg, state["history"],
                                     state["trace"].llm_calls, hint)
        return {"nlu": nlu, "nlu_source": source}

    def route(self, state: ChatState) -> str:
        if state.get("declined"):
            return "return_declined"
        nlu = state["nlu"]
        needs_login = nlu.intent in ("order_status", "order_list", "return_request")
        if needs_login and not state.get("user_id"):
            return "need_login"
        if nlu.intent in ("order_status", "return_request") and not nlu.order_id:
            return "ask_order_id"
        return INTENT_ROUTES[nlu.intent]

    # ---------- products (keyword search, semantic fallback) ----------
    async def products(self, state: ChatState) -> dict:
        nlu, trace, tools = state["nlu"], state["trace"], self.tools(state)
        args = {"query": nlu.product_query, "category": nlu.category, "brand": nlu.brand,
                "min_price": nlu.min_price, "max_price": nlu.max_price}
        items = (await call_tool(tools["search_products"],
                                 {k: v for k, v in args.items() if v is not None},
                                 trace.tool_calls))["items"]

        if not items and nlu.product_query:
            # Keyword search found nothing -> semantic search over product embeddings
            filters = {}
            if nlu.category:
                filters["category"] = nlu.category
            if nlu.max_price is not None:
                filters["price"] = {"$lte": nlu.max_price}
            if nlu.min_price is not None:
                filters.setdefault("price", {})["$gte"] = nlu.min_price
            # The customer's own words embed better than the NLU's keyword rewrite
            hits = await self.product_index.search(state["message"], k=6,
                                                   filter=filters or None)
            trace.chunks.extend(hits)
            ids = [int(h.chunk_id.removeprefix("product-")) for h in hits if h.used]
            if ids:
                items = await call_tool(tools["get_products"], {"ids": ids}, trace.tool_calls)

        if not items:
            return {"reply": TEMPLATES["no_products"]}
        cards = [ProductCard.model_validate(p) for p in items[:6]]
        data = _json([c.model_dump() for c in cards])
        reply = await self.generate(RESPOND_PROMPT, state, "respond", data=data)
        return {"reply": reply, "products": cards, "grounding": data + state["message"],
                "fallback_reply": "Here are the products I found:"}

    # ---------- orders ----------
    async def order(self, state: ChatState) -> dict:
        order_id = state["nlu"].order_id
        data = await call_tool(self.tools(state)["get_order"], {"order_id": order_id},
                               state["trace"].tool_calls)
        if data is None:
            return {"reply": TEMPLATES["order_not_found"].format(order_id=order_id),
                    "suggestions": ["Show my recent orders"]}
        card = OrderCard.model_validate(data)
        reply = await self.generate(RESPOND_PROMPT, state, "respond", data=_json(data))
        suggestions = (["Return this order", "Show my recent orders"]
                       if card.status == "delivered" else ["Show my recent orders"])
        return {"reply": reply, "order": card, "suggestions": suggestions,
                "next_dialog": DialogState(order_id=card.id),
                "grounding": _json(data) + state["message"],
                "fallback_reply": f"Here are the details of order **#{card.id}**:"}

    async def my_orders(self, state: ChatState) -> dict:
        orders = await call_tool(self.tools(state)["list_orders"], {"limit": 5},
                                 state["trace"].tool_calls)
        if not orders:
            return {"reply": TEMPLATES["no_orders"]}
        summary = [{k: o[k] for k in ("id", "status", "total", "placed_at")} |
                   {"items": [i["name"] for i in o["items"]]} for o in orders]
        reply = await self.generate(RESPOND_PROMPT, state, "respond", data=_json(summary))
        return {"reply": reply, "suggestions": [f"Track order #{o['id']}" for o in orders[:3]],
                "grounding": _json(summary) + state["message"],
                "fallback_reply": "Here are your recent orders: " + ", ".join(
                    f"#{o['id']} ({o['status']})" for o in orders)}

    async def ask_order_id(self, state: ChatState) -> dict:
        intent = state["nlu"].intent
        # "Return this order" right after looking at an order -> reuse that order id
        if state["dialog"].order_id and not state["dialog"].awaiting:
            state["nlu"].order_id = state["dialog"].order_id
            return await (self.return_flow(state) if intent == "return_request"
                          else self.order(state))
        recent = await call_tool(self.tools(state)["list_orders"], {"limit": 3},
                                 state["trace"].tool_calls)
        return {"reply": TEMPLATES["ask_order_id"],
                "suggestions": [f"Order #{o['id']}" for o in recent],
                "next_dialog": DialogState(awaiting="order_id", intent=intent)}

    # ---------- returns (eligibility -> confirm -> create) ----------
    async def return_flow(self, state: ChatState) -> dict:
        nlu, tools, calls = state["nlu"], self.tools(state), state["trace"].tool_calls
        if state.get("confirmed"):
            reason = nlu.return_reason or "changed_mind"
            result = await call_tool(tools["create_return"],
                                     {"order_id": nlu.order_id, "reason": reason}, calls)
            if result.get("error"):
                return {"reply": TEMPLATES["return_not_eligible"].format(
                    order_id=nlu.order_id, message=result["message"])}
            fee_note = ("" if reason in FREE_RETURN_REASONS
                        else " (after the $5.99 return shipping fee for change-of-mind returns)")
            return {"reply": TEMPLATES["return_created"].format(
                return_id=result["id"], order_id=nlu.order_id,
                refund=float(result["refund_amount"]), fee_note=fee_note)}

        check = await call_tool(tools["check_return_eligibility"], {"order_id": nlu.order_id},
                                calls)
        if check is None:
            return {"reply": TEMPLATES["order_not_found"].format(order_id=nlu.order_id)}
        if not check["eligible"]:
            return {"reply": TEMPLATES["return_not_eligible"].format(
                order_id=nlu.order_id, message=check["message"])}
        return {
            "reply": TEMPLATES["return_confirm"].format(order_id=nlu.order_id,
                                                        message=check["message"]),
            "suggestions": ["Yes, start the return", "No, keep it"],
            "next_dialog": DialogState(awaiting="return_confirmation", intent="return_request",
                                       order_id=nlu.order_id, return_reason=nlu.return_reason),
        }

    # ---------- policies (RAG) ----------
    async def policy(self, state: ChatState) -> dict:
        # ponytail: retrieves on the raw message; add history-aware query rewriting if
        # follow-ups like "and for electronics?" retrieve poorly
        hits = await self.kb.search(state["message"], k=self.settings.rag_top_k)
        state["trace"].chunks.extend(hits)
        used = [h for h in hits if h.used]
        if not used:
            return {"reply": TEMPLATES["rag_no_answer"], "suggestions": ["Talk to a human"]}
        context = "\n\n---\n\n".join(f"[{h.source} > {h.section}]\n{h.content}" for h in used)
        reply = await self.generate(RAG_PROMPT, state, "rag_answer", context=context)
        sources = [Source(source=h.source, section=h.section, chunk_id=h.chunk_id,
                          score=h.score) for h in used]
        return {"reply": reply, "sources": sources, "grounding": context + state["message"],
                "fallback_reply": TEMPLATES["rag_no_answer"]}

    # ---------- small talk ----------
    async def chat(self, state: ChatState) -> dict:
        # Small talk has no store data, so any number in it (prices, days) is a hallucination
        return {"reply": await self.generate(CHAT_PROMPT, state, "chat"),
                "grounding": state["message"], "fallback_reply": TEMPLATES["chat_fallback"]}
