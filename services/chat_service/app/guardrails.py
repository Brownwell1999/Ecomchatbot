"""Input and output guardrails.

Input  (before NLU):  PII detection/masking -> prompt-injection heuristics -> ML classifier
Output (after LLM):   system-prompt leak, sensitive-data requests, ungrounded numbers, PII masking

Every check returns a GuardrailResult that goes into the debug trace, so tests can assert exactly
which guardrail fired and what it did.
"""

import logging
import re

from langchain_groq import ChatGroq

from shared.config import Settings

from .schemas import GuardrailResult

logger = logging.getLogger("chat_service.guardrails")

# ---------- PII ----------
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?<![\w])(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CVV_RE = re.compile(r"\b(cvv|cvc|security code)\b\D{0,10}\d{3,4}\b", re.I)


def luhn_valid(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def mask_pii(text: str, allow: str = "") -> tuple[str, list[str]]:
    """Replace PII with typed placeholders. Returns (masked_text, pii_types_found).

    Values that also appear in `allow` (e.g. the store's support email in the policy docs)
    are kept.
    """
    found: list[str] = []

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            found.append("credit_card")
            return f"[CARD ****{digits[-4:]}]"
        return m.group()  # order numbers, tracking numbers etc. are not cards

    text = CARD_RE.sub(card, text)
    for name, pattern, placeholder in (
        ("cvv", CVV_RE, "[CVV]"),
        ("ssn", SSN_RE, "[SSN]"),
        ("email", EMAIL_RE, "[EMAIL]"),
        ("phone", PHONE_RE, "[PHONE]"),
    ):
        def sub(m: re.Match, name=name, placeholder=placeholder) -> str:
            if allow and m.group() in allow:
                return m.group()
            found.append(name)
            return placeholder

        text = pattern.sub(sub, text)
    return text, found


# ---------- prompt injection / jailbreak ----------
INJECTION_PATTERNS = [
    r"ignore (all |any )?(the |your )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any )?(the |your )?(previous|prior|above|system) "
    r"(instructions|prompts?|rules)",
    r"(reveal|show|print|repeat|output|tell me) (me )?(your|the) (system prompt|instructions|"
    r"initial prompt|hidden prompt|rules)",
    r"\byou are now\b.{0,40}\b(dan|jailbroken|unrestricted|evil|developer mode)\b",
    r"\b(dan|developer) mode\b",
    r"\bjailbreak",
    r"\bpretend (you are|to be) (an? )?(unrestricted|unfiltered|different) ",
    r"\b(new|updated) (system )?instructions?:",
    r"<\s*/?\s*(system|assistant)\s*>",
    r"\bact as (an? )?(admin|administrator|system|root)\b",
    r"(give|apply|issue) (me )?(a )?(100%|free|full) (discount|refund) (code|now)",
]
INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.I)

# ---------- output checks ----------
SENSITIVE_REQUEST_RE = re.compile(
    r"(share|provide|send|enter|give|tell) (me )?(your |the )?(full )?(card number|credit card"
    r"|cvv|cvc|password|pin\b|social security)", re.I)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Numbers normalised for comparison: '$1,134.88' -> '1134.88', '12.0' -> '12'."""
    out = set()
    for n in NUMBER_RE.findall(text.replace(",", "")):
        out.add(n.rstrip("0").rstrip(".") if "." in n else n.lstrip("0") or "0")
    return out


def ungrounded_numbers(reply: str, grounding: str) -> list[str]:
    # ponytail: integers <= 10 pass (counts, list numbering, "4 PM"); a claim-level LLM
    # faithfulness check (Phase 6 evals) catches what this cheap check can't
    return sorted(n for n in _numbers(reply) - _numbers(grounding)
                  if not (n.isdigit() and int(n) <= 10))


class Guardrails:
    def __init__(self, settings: Settings, system_prompts: list[str]):
        self.threshold = settings.guardrail_injection_threshold
        self.classifier = None
        if settings.guardrail_classifier == "groq" and settings.groq_api_key:
            self.classifier = ChatGroq(model_name=settings.guardrail_classifier_model,
                                       api_key=settings.groq_api_key, max_retries=1,
                                       request_timeout=5)
        # Distinctive sentences of our system prompts; seeing one in a reply = prompt leak
        self.leak_markers = [s.strip(" -").lower() for p in system_prompts
                             for s in re.split(r"[.\n]", p) if len(s.strip(" -")) > 40]

    # ---------- input ----------
    async def check_input(self, message: str) -> tuple[str, list[GuardrailResult]]:
        """Returns (message safe to send to the LLM, results). A result with action 'block'
        means the message must not reach the LLM."""
        results = []
        masked, pii = mask_pii(message)
        if pii:
            action = "block" if {"credit_card", "cvv", "ssn"} & set(pii) else "mask"
            results.append(GuardrailResult(name="pii", stage="input", passed=False, action=action,
                                           detail=",".join(sorted(set(pii)))))

        if m := INJECTION_RE.search(message):
            results.append(GuardrailResult(name="prompt_injection", stage="input", passed=False,
                                           action="block", detail=f"pattern: {m.group()[:60]}"))
        elif self.classifier is not None and not results:  # nothing blocked yet
            score = await self._injection_score(masked)
            if score is not None:
                blocked = score >= self.threshold
                results.append(GuardrailResult(
                    name="prompt_guard", stage="input", passed=not blocked,
                    action="block" if blocked else "allow", score=round(score, 4),
                    detail=f"threshold {self.threshold}"))
        return masked, results

    async def _injection_score(self, text: str) -> float | None:
        try:
            msg = await self.classifier.ainvoke([("user", text)])
            return float(str(msg.content).strip())
        except Exception as exc:  # classifier down -> fail open, heuristics still apply
            logger.warning("Prompt guard unavailable: %s", exc)
            return None

    # ---------- output ----------
    def check_output(self, reply: str, grounding: str | None) -> tuple[str, list[GuardrailResult]]:
        """grounding: all text the reply may take facts from (tool data / RAG context / user
        message). None = no factual grounding required (small talk, templates)."""
        results = []
        lowered = reply.lower()
        if any(marker in lowered for marker in self.leak_markers):
            results.append(GuardrailResult(name="prompt_leak", stage="output", passed=False,
                                           action="block", detail="system prompt text in reply"))
        if SENSITIVE_REQUEST_RE.search(reply):
            results.append(GuardrailResult(name="sensitive_request", stage="output",
                                           passed=False, action="block",
                                           detail="reply asks for sensitive data"))
        if grounding is not None:
            if ungrounded := ungrounded_numbers(reply, grounding):
                results.append(GuardrailResult(name="grounding", stage="output", passed=False,
                                               action="block",
                                               detail="ungrounded numbers: " +
                                                      ", ".join(ungrounded[:5])))
        masked, pii = mask_pii(reply, allow=grounding or "")
        if pii:
            results.append(GuardrailResult(name="pii", stage="output", passed=False,
                                           action="mask", detail=",".join(sorted(set(pii)))))
        return masked, results
