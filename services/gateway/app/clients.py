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
                           user_id: int | None, include_debug: bool = False) -> dict:
        resp = await self._request(self._chat, "POST", "/chat", json={
            "conversation_id": conversation_id, "message": text, "user_id": user_id,
            "include_debug": include_debug})
        if resp.status_code == 503:
            raise UpstreamError("LLM_UNAVAILABLE", "The assistant is temporarily unavailable.", 503)
        if resp.status_code == 422:
            raise UpstreamError("BAD_USER_INPUT", "Invalid message or conversation id.", 422)
        if resp.status_code >= 400:
            raise UpstreamError("UPSTREAM_ERROR", "The assistant hit an error. Please try again.",
                                resp.status_code)
        return resp.json()

    async def stream_message(self, conversation_id: str | None, text: str,
                             user_id: int | None,
                             include_debug: bool = False) -> AsyncIterator[dict]:
        """Relay chat-service server-sent events as dicts (token* then final|error)."""
        body = {"conversation_id": conversation_id, "message": text, "user_id": user_id,
                "include_debug": include_debug}
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

    # ---------- order-service (AI Testing Lab accounts) ----------
    async def lab_register(self, email: str, full_name: str, password: str) -> dict:
        resp = await self._request(self._orders, "POST", "/lab/register",
                                   json={"email": email, "full_name": full_name,
                                         "password": password})
        if resp.status_code == 409:
            raise UpstreamError("CONFLICT", "An account with this email already exists.", 409)
        if resp.status_code == 422:
            raise UpstreamError("BAD_USER_INPUT",
                                "Please check your name, email and password.", 422)
        resp.raise_for_status()
        return resp.json()

    async def lab_verify(self, email: str, password: str) -> dict:
        resp = await self._request(self._orders, "POST", "/lab/verify",
                                   json={"email": email, "password": password})
        if resp.status_code == 403:
            raise UpstreamError("FORBIDDEN",
                                "This account has been disabled. Contact an admin.", 403)
        if resp.status_code in (401, 422):
            raise UpstreamError("UNAUTHENTICATED", "Invalid email or password.", 401)
        resp.raise_for_status()
        return resp.json()

    async def lab_user(self, user_id: int) -> dict | None:
        resp = await self._request(self._orders, "GET", f"/lab/users/{user_id}")
        return resp.json() if resp.status_code == 200 else None

    async def lab_users(self) -> list[dict]:
        resp = await self._request(self._orders, "GET", "/lab/users")
        resp.raise_for_status()
        return resp.json()

    async def lab_update_user(self, user_id: int, changes: dict) -> dict | None:
        resp = await self._request(self._orders, "PATCH", f"/lab/users/{user_id}", json=changes)
        return resp.json() if resp.status_code == 200 else None

    async def lab_progress(self, user_id: int) -> list[dict]:
        resp = await self._request(self._orders, "GET", f"/lab/users/{user_id}/progress")
        return resp.json() if resp.status_code == 200 else []

    async def lab_complete_lesson(self, user_id: int, lesson_id: str) -> list[dict]:
        resp = await self._request(self._orders, "POST", f"/lab/users/{user_id}/progress",
                                   json={"lesson_id": lesson_id})
        if resp.status_code == 422:
            raise UpstreamError("BAD_USER_INPUT", "Unknown lesson id.", 422)
        resp.raise_for_status()
        return resp.json()
