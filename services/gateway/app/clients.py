"""HTTP clients for downstream microservices. Propagates X-Request-ID for end-to-end tracing."""

import json
from collections.abc import AsyncIterator

import httpx

from shared.logging import REQUEST_ID_HEADER, request_id_var


class UpstreamError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class ServiceClients:
    def __init__(self, chat: httpx.AsyncClient, orders: httpx.AsyncClient):
        self._chat = chat
        self._orders = orders

    @staticmethod
    async def _request(http: httpx.AsyncClient, method: str, path: str, **kwargs):
        try:
            return await http.request(method, path,
                                      headers={REQUEST_ID_HEADER: request_id_var.get()}, **kwargs)
        except httpx.TimeoutException as exc:
            raise UpstreamError("UPSTREAM_TIMEOUT", "A backend service timed out") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError("UPSTREAM_UNAVAILABLE", "A backend service is unreachable") from exc

    # ---------- chat-service ----------
    async def send_message(self, conversation_id: str | None, text: str,
                           user_id: int | None) -> dict:
        resp = await self._request(self._chat, "POST", "/chat", json={
            "conversation_id": conversation_id, "message": text, "user_id": user_id})
        if resp.status_code == 503:
            raise UpstreamError("LLM_UNAVAILABLE", "The assistant is temporarily unavailable.", 503)
        if resp.status_code == 422:
            raise UpstreamError("BAD_USER_INPUT", "Invalid message or conversation id.", 422)
        if resp.status_code >= 400:
            raise UpstreamError("UPSTREAM_ERROR", "The assistant hit an error. Please try again.",
                                resp.status_code)
        return resp.json()

    async def stream_message(self, conversation_id: str | None, text: str,
                             user_id: int | None) -> AsyncIterator[dict]:
        """Relay chat-service server-sent events as dicts (token* then final|error)."""
        body = {"conversation_id": conversation_id, "message": text, "user_id": user_id}
        try:
            async with self._chat.stream("POST", "/chat/stream", json=body,
                                         headers={REQUEST_ID_HEADER: request_id_var.get()}) as r:
                if r.status_code >= 400:
                    yield {"type": "error", "code": "BAD_USER_INPUT" if r.status_code == 422
                           else "UPSTREAM_ERROR", "message": "The message couldn't be sent."}
                    return
                async for line in r.aiter_lines():
                    if line.startswith("data: "):
                        yield json.loads(line[6:])
        except httpx.HTTPError:
            yield {"type": "error", "code": "UPSTREAM_UNAVAILABLE",
                   "message": "The assistant is unreachable."}

    async def send_feedback(self, payload: dict) -> bool:
        resp = await self._request(self._chat, "POST", "/feedback", json=payload)
        return resp.status_code == 201

    async def get_conversation(self, conversation_id: str) -> dict | None:
        resp = await self._request(self._chat, "GET", f"/conversations/{conversation_id}")
        if resp.status_code in (404, 422):
            return None
        resp.raise_for_status()
        return resp.json()

    async def delete_conversation(self, conversation_id: str) -> bool:
        resp = await self._request(self._chat, "DELETE", f"/conversations/{conversation_id}")
        return resp.status_code == 204

    # ---------- order-service (users / auth) ----------
    async def verify_credentials(self, email: str, password: str) -> dict | None:
        resp = await self._request(self._orders, "POST", "/auth/verify",
                                   json={"email": email, "password": password})
        return resp.json() if resp.status_code == 200 else None

    async def get_user(self, user_id: int) -> dict | None:
        resp = await self._request(self._orders, "GET", f"/users/{user_id}")
        return resp.json() if resp.status_code == 200 else None

    async def demo_users(self) -> list[dict]:
        resp = await self._request(self._orders, "GET", "/users/demo")
        return resp.json() if resp.status_code == 200 else []
