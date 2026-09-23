"""Small checks for the non-trivial chatbot logic (the full test framework is Phase 6)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from services.chat_service.app.graph import ChatGraph, Trace
from services.chat_service.app.llm import LLM
from services.chat_service.app.nlu import rule_based_nlu
from services.chat_service.app.rag import load_kb_documents, split_documents
from services.chat_service.app.schemas import DialogState
from services.order_service.app.main import check_eligibility
from shared.config import Settings

NOW = datetime(2026, 9, 1, 12)


def order(status="delivered", days_ago=5, category="fashion"):
    item = SimpleNamespace(product=SimpleNamespace(category=category))
    return SimpleNamespace(id=1042, status=status, items=[item],
                           delivered_at=NOW - timedelta(days=days_ago) if days_ago else None)


def test_return_eligibility_rules():
    assert check_eligibility(order(), False, NOW).reason_code == "ELIGIBLE"
    assert check_eligibility(order(days_ago=31), False, NOW).reason_code == "WINDOW_EXPIRED"
    assert check_eligibility(order(days_ago=16, category="electronics"), False,
                             NOW).reason_code == "WINDOW_EXPIRED"
    assert check_eligibility(order(status="shipped", days_ago=None), False,
                             NOW).reason_code == "NOT_DELIVERED"
    assert check_eligibility(order(), True, NOW).reason_code == "ALREADY_RETURNED"


def test_rule_based_nlu():
    assert rule_based_nlu("Where is my order 1042?").intent == "order_status"
    assert rule_based_nlu("Where is my order 1042?").order_id == 1042
    shoes = rule_based_nlu("show me running shoes under $100")
    assert (shoes.intent, shoes.category, shoes.max_price) == ("product_search", "footwear", 100)
    assert rule_based_nlu("I want to return order 1042").intent == "return_request"
    assert rule_based_nlu("what is your warranty policy?").intent == "policy_question"
    assert rule_based_nlu("let me talk to a human").intent == "human_handoff"


def test_chunks_have_ids_sections_and_titles():
    chunks = split_documents(load_kb_documents("data/knowledge_base"))
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(c.page_content.startswith("# ") for c in chunks)  # contextual header
    assert all(len(c.page_content) <= 700 for c in chunks)
    window = next(c for c in chunks if c.metadata["section"] == "Return window")
    assert "15 days" in window.page_content


class StubStore:
    """Fake order/catalog backend for dialog tests."""

    def __init__(self):
        self.created = []

    async def _order_get(self, path, user_id):
        if "return-eligibility" in path:
            return {"eligible": True, "message": "Eligible: delivered 5 days ago."}
        return []

    async def create_return(self, user_id, order_id, reason):
        self.created.append(order_id)
        return {"id": 7, "refund_amount": "94.01"}


async def run_turns(*messages, user_id=1):
    store = StubStore()
    graph = ChatGraph(LLM(Settings(llm_provider="fake")), store, None, None, Settings())
    dialog, results = DialogState(), []
    for msg in messages:
        result = await graph.run({"message": msg, "user_id": user_id, "history": [],
                                  "dialog": dialog, "trace": Trace()})
        dialog = result.get("next_dialog", DialogState())
        results.append(result)
    return results, store


async def test_return_flow_asks_order_id_then_confirms():
    results, store = await run_turns("I want to return something", "1042", "yes")
    assert results[0]["next_dialog"].awaiting == "order_id"
    assert "Shall I start the return" in results[1]["reply"]
    assert "Return **#7**" in results[2]["reply"] and store.created == [1042]


async def test_orders_need_login():
    results, _ = await run_turns("where is my order 1042", user_id=None)
    assert "sign in" in results[0]["reply"].lower()

