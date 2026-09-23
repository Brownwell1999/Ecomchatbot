"""Conversation memory. Redis in production; in-memory implementation for unit tests."""

import json
from typing import Protocol

from redis.asyncio import Redis

from .schemas import DialogState, MessageOut

MAX_STORED_MESSAGES = 200


class ConversationStore(Protocol):
    async def append(self, conversation_id: str, *messages: MessageOut) -> None: ...
    async def history(self, conversation_id: str, limit: int | None = None) -> list[MessageOut]: ...
    async def exists(self, conversation_id: str) -> bool: ...
    async def delete(self, conversation_id: str) -> bool: ...
    async def get_state(self, conversation_id: str) -> DialogState: ...
    async def set_state(self, conversation_id: str, state: DialogState) -> None: ...
    async def ping(self) -> bool: ...


class RedisConversationStore:
    def __init__(self, redis: Redis, ttl_seconds: int):
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"conv:{conversation_id}:messages"

    async def append(self, conversation_id: str, *messages: MessageOut) -> None:
        key = self._key(conversation_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *(m.model_dump_json() for m in messages))
            pipe.ltrim(key, -MAX_STORED_MESSAGES, -1)
            pipe.expire(key, self._ttl)
            await pipe.execute()

    async def history(self, conversation_id: str, limit: int | None = None) -> list[MessageOut]:
        start = -limit if limit else 0
        raw = await self._redis.lrange(self._key(conversation_id), start, -1)
        return [MessageOut.model_validate(json.loads(item)) for item in raw]

    async def exists(self, conversation_id: str) -> bool:
        return bool(await self._redis.exists(self._key(conversation_id)))

    async def delete(self, conversation_id: str) -> bool:
        keys = (self._key(conversation_id), self._state_key(conversation_id))
        return bool(await self._redis.delete(*keys))

    @staticmethod
    def _state_key(conversation_id: str) -> str:
        return f"conv:{conversation_id}:state"

    async def get_state(self, conversation_id: str) -> DialogState:
        raw = await self._redis.get(self._state_key(conversation_id))
        return DialogState.model_validate_json(raw) if raw else DialogState()

    async def set_state(self, conversation_id: str, state: DialogState) -> None:
        await self._redis.set(self._state_key(conversation_id), state.model_dump_json(),
                              ex=self._ttl)

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False


class InMemoryConversationStore:
    def __init__(self):
        self._data: dict[str, list[MessageOut]] = {}
        self._state: dict[str, DialogState] = {}

    async def append(self, conversation_id: str, *messages: MessageOut) -> None:
        stored = self._data.setdefault(conversation_id, [])
        stored.extend(messages)
        del stored[:-MAX_STORED_MESSAGES]

    async def history(self, conversation_id: str, limit: int | None = None) -> list[MessageOut]:
        stored = self._data.get(conversation_id, [])
        return list(stored[-limit:] if limit else stored)

    async def exists(self, conversation_id: str) -> bool:
        return conversation_id in self._data

    async def delete(self, conversation_id: str) -> bool:
        self._state.pop(conversation_id, None)
        return self._data.pop(conversation_id, None) is not None

    async def get_state(self, conversation_id: str) -> DialogState:
        return self._state.get(conversation_id, DialogState())

    async def set_state(self, conversation_id: str, state: DialogState) -> None:
        self._state[conversation_id] = state

    async def ping(self) -> bool:
        return True
