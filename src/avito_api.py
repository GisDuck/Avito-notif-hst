from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    chat_id: str
    author_name: str
    created_at: datetime
    text: str


@dataclass(frozen=True)
class AvitoPollResult:
    total_chats: int
    unread_chats: int
    new_messages: list[IncomingMessage]


class AvitoClient:
    def __init__(self, client_id: str, client_secret: str, user_id: str | None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._client = httpx.AsyncClient(base_url="https://api.avito.ru", timeout=20)

    async def close(self) -> None:
        await self._client.aclose()

    async def unread_incoming_messages(self, processed_ids: set[str]) -> AvitoPollResult:
        user_id = await self.get_user_id()
        chats = await self._get_chats(user_id)
        unread_chats = 0
        result: list[IncomingMessage] = []
        for chat in chats:
            unread_count = self._int(chat.get("unread_count") or chat.get("unreadCount"))
            if unread_count <= 0:
                continue
            unread_chats += 1

            chat_id = str(chat.get("id") or chat.get("chat_id") or "")
            if not chat_id:
                continue

            messages = await self._get_messages(user_id, chat_id)
            for raw in messages:
                message = self._parse_message(raw, chat, chat_id, user_id)
                if not message or message.id in processed_ids:
                    continue
                result.append(message)

        result.sort(key=lambda item: item.created_at)
        return AvitoPollResult(
            total_chats=len(chats),
            unread_chats=unread_chats,
            new_messages=result,
        )

    async def get_user_id(self) -> str:
        if self.user_id:
            return self.user_id

        token = await self._access_token()
        response = await self._client.get(
            "/core/v1/accounts/self",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        data = response.json()
        user_id = data.get("id") or data.get("user_id")
        if not user_id:
            raise RuntimeError("Avito did not return current account id. Set AVITO_USER_ID manually.")
        self.user_id = str(user_id)
        return self.user_id

    async def _get_chats(self, user_id: str) -> list[dict[str, Any]]:
        token = await self._access_token()
        response = await self._client.get(
            f"/messenger/v2/accounts/{user_id}/chats",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            chats = data.get("chats") or data.get("items") or data.get("result") or []
        else:
            chats = data
        return chats if isinstance(chats, list) else []

    async def _get_messages(self, user_id: str, chat_id: str) -> list[dict[str, Any]]:
        token = await self._access_token()
        response = await self._client.get(
            f"/messenger/v3/accounts/{user_id}/chats/{chat_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            messages = data.get("messages") or data.get("items") or data.get("result") or []
        else:
            messages = data
        return messages if isinstance(messages, list) else []

    async def _access_token(self) -> str:
        now = datetime.now(timezone.utc).timestamp()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        response = await self._client.post(
            "/token/",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("Avito did not return access_token.")
        self._token = token
        self._token_expires_at = now + self._int(data.get("expires_in"), default=3600)
        return token

    def _parse_message(
        self,
        raw: dict[str, Any],
        chat: dict[str, Any],
        chat_id: str,
        own_user_id: str,
    ) -> IncomingMessage | None:
        message_id = str(raw.get("id") or raw.get("message_id") or "")
        if not message_id:
            return None

        direction = str(raw.get("direction") or raw.get("type") or "").lower()
        author_id = str(raw.get("author_id") or raw.get("user_id") or raw.get("sender_id") or "")
        if direction in {"out", "outgoing", "sent"} or author_id == str(own_user_id):
            return None

        text = self._extract_text(raw)
        if not text:
            return None

        created_at = self._parse_datetime(
            raw.get("created") or raw.get("created_at") or raw.get("timestamp")
        )
        author_name = self._author_name(raw, chat)
        return IncomingMessage(message_id, chat_id, author_name, created_at, text)

    def _extract_text(self, raw: dict[str, Any]) -> str:
        content = raw.get("content")
        if isinstance(content, dict):
            for key in ("text", "value", "message"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        for key in ("text", "message", "body"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    def _author_name(self, raw: dict[str, Any], chat: dict[str, Any]) -> str:
        author = raw.get("author") or raw.get("user") or {}
        if isinstance(author, dict):
            for key in ("name", "public_name", "username"):
                value = author.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        users = chat.get("users")
        if isinstance(users, list):
            for user in users:
                if not isinstance(user, dict):
                    continue
                if str(user.get("id")) == str(raw.get("author_id")):
                    name = user.get("name") or user.get("public_name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()

        return "Клиент"

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
