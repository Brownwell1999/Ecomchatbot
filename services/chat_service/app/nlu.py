"""Natural Language Understanding: intent + entities.

Primary: LLM structured output (Pydantic schema -> function calling / JSON schema).
Fallback: regex rules, used with the fake LLM and whenever the LLM output can't be parsed.
"""

import re
from typing import Literal

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from .llm import LLM, LLMUnavailableError
from .prompts import NLU_PROMPT
from .schemas import LLMCall

Intent = Literal["product_search", "order_status", "order_list", "return_request",
                 "policy_question", "human_handoff", "small_talk", "out_of_scope"]
Category = Literal["electronics", "fashion", "footwear", "home_kitchen", "beauty", "sports"]
ReturnReason = Literal["changed_mind", "defective", "damaged", "wrong_item", "other"]


class NLUResult(BaseModel):
    """Intent and entities of the customer's latest message."""

    intent: Intent
    confidence: float = Field(ge=0, le=1, description="0..1 confidence in the intent")
    order_id: int | None = Field(None, description="order number mentioned, e.g. 1042")
    product_query: str | None = Field(None, description="product keywords, e.g. 'running shoes'")
    category: Category | None = None
    brand: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    return_reason: ReturnReason | None = None

    def entities(self) -> dict:
        return self.model_dump(exclude={"intent", "confidence"}, exclude_none=True)


ORDER_ID_RE = re.compile(r"#?\b(\d{4,6})\b")
YES_RE = re.compile(r"^\s*(y|yes|yeah|yep|sure|ok|okay|confirm|please do|go ahead|do it|"
                    r"yes,? (please|start|go ahead).*)\s*[.!]*\s*$", re.I)
NO_RE = re.compile(r"^\s*(n|no|nope|cancel|don'?t|never ?mind|no,? .*|keep it)\s*[.!]*\s*$", re.I)

CATEGORY_WORDS = {
    "electronics": r"earbud|headphone|speaker|smartwatch|monitor|keyboard|charger|webcam|"
                   r"electronic|gadget",
    "fashion": r"shirt|jacket|jeans|sweater|sweatshirt|hoodie|pants|chino|clothes|clothing",
    "footwear": r"shoe|sneaker|boot|loafer|sandal|footwear",
    "home_kitchen": r"coffee|fryer|pan|blender|kettle|knife|mixer|kitchen|container",
    "beauty": r"moisturi[sz]er|serum|sunscreen|dryer|shampoo|lip balm|trimmer|perfume|beauty|skin",
    "sports": r"yoga|dumbbell|resistance band|helmet|bottle|tracker|tent|racket|fitness|sport",
}

RULES: list[tuple[Intent, str]] = [
    ("human_handoff", r"\b(human|agent|real person|representative|talk to someone)\b"),
    ("out_of_scope", r"\b(poem|joke|code|python|javascript|homework|weather|politic|recipe|"
                     r"capital of|president)\b"),
    ("return_request", r"\b(return|refund|send (it )?back)\b.*\b(order|#?\d{4,6}|it|this)\b|"
                       r"\b(return|refund)\b.*\d{4,6}|^i want to return"),
    ("policy_question", r"\b(policy|policies|how long|how many days|shipping (cost|option|time)|"
                        r"warranty|payment|pay with|promo|coupon|membership|plus|gift card|"
                        r"exchange|international|support hours|password|delivery time)\b"),
    ("order_list", r"\b(my orders|recent orders|order history|past orders|all orders)\b"),
    ("order_status", r"\b(order|track|tracking|package|parcel|shipment|delivery)\b"),
    ("small_talk", r"^\s*(hi|hello|hey|thanks|thank you|bye|good (morning|evening))\b|"
                   r"\bwho are you\b|\bwhat can you do\b"),
    ("product_search", r"\b(show|looking for|recommend|buy|need|want|price|cheap|best|"
                       r"under|in stock)\b"),
]


def rule_based_nlu(message: str) -> NLUResult:
    text = message.lower()
    order_id = ORDER_ID_RE.search(text)
    category = next((c for c, pat in CATEGORY_WORDS.items() if re.search(pat, text)), None)
    intent: Intent = next((i for i, pat in RULES if re.search(pat, text)),
                          "product_search" if category else "small_talk")
    max_price = re.search(r"\b(?:under|below|less than|max|up to)\s*\$?(\d+)", text)
    min_price = re.search(r"\b(?:over|above|more than|at least)\s*\$?(\d+)", text)
    reason = ("defective" if re.search(r"broken|defect|not working|faulty", text)
              else "damaged" if "damaged" in text
              else "wrong_item" if re.search(r"wrong (item|size|product)", text) else None)
    return NLUResult(
        intent=intent,
        confidence=0.6,
        order_id=int(order_id.group(1)) if order_id and intent != "product_search" else None,
        product_query=message if intent == "product_search" else None,
        category=category if intent == "product_search" else None,
        max_price=float(max_price.group(1)) if max_price else None,
        min_price=float(min_price.group(1)) if min_price else None,
        return_reason=reason,
    )


async def classify(chain: Runnable | None, message: str, history: list[BaseMessage],
                   calls: list[LLMCall], dialog_hint: str = "") -> tuple[NLUResult, str]:
    """LLM structured-output NLU with rule fallback. Returns (result, source: llm | rules).

    Standalone on purpose: intent-accuracy evals can call this without the dialog graph.
    """
    result, source = rule_based_nlu(message), "rules"
    if chain is not None:
        value = NLU_PROMPT.invoke({"history": history[-4:], "message": message,
                                   "dialog_hint": dialog_hint})
        try:
            out = await LLM.run(chain, value, "nlu", calls)
            if out["parsed"] is not None:
                result, source = out["parsed"], "llm"
        except LLMUnavailableError:
            pass  # degrade to rules; generation may still work on a fallback model

    # Safety net: an order number in the text beats a missed entity
    if result.order_id is None and result.intent in ("order_status", "return_request"):
        if m := ORDER_ID_RE.search(message):
            result.order_id = int(m.group(1))
    return result, source
