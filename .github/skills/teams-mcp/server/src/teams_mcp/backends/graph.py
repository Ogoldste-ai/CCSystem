from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any

import httpx
import truststore

from ..config import TeamsConfig
from ..models import Chat, Message, strip_html

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
READ_SCOPE = "Chat.Read"
WRITE_SCOPE = "Chat.ReadWrite"

CONSENT_HINT = (
    "Microsoft Graph refused the request. Chat.Read and Chat.ReadWrite each need "
    "administrator consent in this tenant (a user-consent attempt returns AADSTS65001). "
    "Ask IT to register a single-tenant public-client app with delegated Chat.Read - and "
    "Chat.ReadWrite if replying is needed - assigned to your account only, then set "
    "TEAMS_CLIENT_ID to its application id."
)


class GraphAuthError(RuntimeError):
    """Acquiring a Microsoft Graph token failed."""


class GraphApiError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code

    @classmethod
    def from_response(cls, method: str, path: str, response: Any) -> "GraphApiError":
        status = int(getattr(response, "status_code", 0) or 0)
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")[:500]
        except Exception:
            detail = str(getattr(response, "text", "") or "").strip()[:500]
        hint = f" {CONSENT_HINT}" if status in (401, 403) else ""
        return cls(status, f"Graph {method} {path} failed with HTTP {status}: {detail or 'no body'}.{hint}")


class GraphBackend:
    """Microsoft Graph, delegated. Everything runs as the signed-in user, so the
    server can only ever see chats that user can already see."""

    name = "graph"

    def __init__(self, config: TeamsConfig, http: Any | None = None) -> None:
        self.config = config
        self._http = http
        self._app: Any = None
        self._cache: Any = None

    # -- transport -----------------------------------------------------------

    def _client(self) -> Any:
        if self._http is None:
            self._http = httpx.Client(
                base_url=GRAPH_BASE,
                timeout=self.config.timeout_seconds,
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                headers={"User-Agent": self.config.user_agent},
            )
        return self._http

    def _token_cache_path(self) -> Path:
        return self.config.state_file.parent / "graph-token-cache.json"

    def _msal_app(self) -> Any:
        if self._app is not None:
            return self._app
        try:
            import msal
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise GraphAuthError(
                "The 'msal' package is required for the graph backend. Install it with "
                "'pip install -e .[graph]' in the server directory."
            ) from exc
        cache_path = self._token_cache_path()
        cache = msal.SerializableTokenCache()
        if cache_path.exists():
            try:
                cache.deserialize(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        self._cache = cache
        self._app = msal.PublicClientApplication(
            self.config.client_id,
            authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
            token_cache=cache,
        )
        return self._app

    def _persist_cache(self) -> None:
        if self._cache is None or not getattr(self._cache, "has_state_changed", False):
            return
        path = self._token_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._cache.serialize(), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _acquire_token(self, scopes: list[str]) -> str:
        self.config.require_ready()
        app = self._msal_app()
        accounts = app.get_accounts()
        result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
        if not result:
            flow = app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise GraphAuthError(
                    f"Could not start device-code sign-in: {flow.get('error_description') or flow}. "
                    f"{CONSENT_HINT}"
                )
            raise GraphAuthError(
                "Interactive sign-in required. Open "
                f"{flow.get('verification_uri')} and enter code {flow.get('user_code')}, then "
                "run the tool again. (Sign-in cannot be completed inside a tool call because "
                "it would block the MCP server.)"
            )
        self._persist_cache()
        if "access_token" not in result:
            raise GraphAuthError(
                f"Token request failed: {result.get('error_description') or result}. {CONSENT_HINT}"
            )
        return str(result["access_token"])

    def _request(self, method: str, path: str, scopes: list[str], **kwargs: Any) -> Any:
        token = self._acquire_token(scopes)
        headers = {"Authorization": f"Bearer {token}"}
        response = self._client().request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise GraphApiError.from_response(method, path, response)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    # -- reads ---------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "backend": self.name,
            "client_id": self.config.client_id or None,
            "tenant_id": self.config.tenant_id or None,
        }
        try:
            me = self._request("GET", "/me", [READ_SCOPE])
            info["signed_in_as"] = me.get("userPrincipalName") or me.get("displayName")
            info["authenticated"] = True
        except (GraphAuthError, GraphApiError) as exc:
            info["authenticated"] = False
            info["auth_error"] = str(exc)
        return info

    @staticmethod
    def _chat_from_payload(payload: dict[str, Any]) -> Chat:
        members = [
            str(member.get("displayName") or member.get("email") or "").strip()
            for member in payload.get("members", []) or []
            if isinstance(member, dict)
        ]
        return Chat(
            id=str(payload.get("id") or ""),
            topic=str(payload.get("topic") or ""),
            kind=str(payload.get("chatType") or ""),
            members=[member for member in members if member],
            last_updated=str(payload.get("lastUpdatedDateTime") or ""),
            web_url=str(payload.get("webUrl") or ""),
        )

    def _message_from_payload(
        self, payload: dict[str, Any], chat_id: str, chat_name: str = ""
    ) -> Message:
        sender = payload.get("from") or {}
        user = sender.get("user") if isinstance(sender, dict) else {}
        user = user or {}
        body = payload.get("body") or {}
        content = str(body.get("content") or "")
        if str(body.get("contentType") or "").lower() == "html":
            content = strip_html(content)
        return Message(
            id=str(payload.get("id") or ""),
            chat_id=chat_id,
            chat_name=chat_name,
            sender=str(user.get("displayName") or ""),
            sender_email=str(user.get("userPrincipalName") or user.get("email") or ""),
            created_at=str(payload.get("createdDateTime") or ""),
            body=content,
            web_url=str(payload.get("webUrl") or ""),
        )

    def list_chats(self, limit: int = 20) -> list[Chat]:
        params = {"$top": max(1, min(limit, 50)), "$expand": "members"}
        payload = self._request("GET", "/me/chats", [READ_SCOPE], params=params)
        chats = [self._chat_from_payload(item) for item in payload.get("value", [])]
        chats.sort(key=lambda item: item.last_updated, reverse=True)
        return chats[:limit]

    def fetch_messages(self, chat_id: str, since: str = "", limit: int = 50) -> list[Message]:
        if not chat_id:
            raise ValueError("chat_id is required for the graph backend.")
        params: dict[str, Any] = {"$top": max(1, min(limit, 50))}
        payload = self._request(
            "GET", f"/me/chats/{chat_id}/messages", [READ_SCOPE], params=params
        )
        messages = [
            self._message_from_payload(item, chat_id) for item in payload.get("value", [])
        ]
        messages = [message for message in messages if message.body]
        if since:
            from ..models import parse_timestamp

            cutoff = parse_timestamp(since)
            if cutoff is not None:
                messages = [message for message in messages if message.sort_key() > cutoff]
        messages.sort(key=lambda item: item.sort_key())
        return messages[-limit:] if limit > 0 else messages

    def fetch_recent(self, since: str = "", limit: int = 50) -> list[Message]:
        """Newest message per chat, which is what 'did anything arrive?' needs.

        Graph has no cheap delegated 'all my messages' endpoint, so this expands
        ``lastMessagePreview`` over the chat list instead of fanning out one
        request per chat.
        """
        params = {"$top": 50, "$expand": "members,lastMessagePreview"}
        payload = self._request("GET", "/me/chats", [READ_SCOPE], params=params)
        from ..models import parse_timestamp

        cutoff = parse_timestamp(since)
        messages: list[Message] = []
        for item in payload.get("value", []):
            preview = item.get("lastMessagePreview")
            if not isinstance(preview, dict):
                continue
            chat = self._chat_from_payload(item)
            message = self._message_from_payload(preview, chat.id, chat.display_name())
            if not message.body:
                continue
            if cutoff is not None and message.sort_key() <= cutoff:
                continue
            messages.append(message)
        messages.sort(key=lambda item: item.sort_key(), reverse=True)
        return messages[:limit] if limit > 0 else messages

    # -- writes --------------------------------------------------------------

    def send_reply(self, chat_id: str, body: str) -> dict[str, Any]:
        payload = self._request(
            "POST",
            f"/me/chats/{chat_id}/messages",
            [WRITE_SCOPE],
            json={"body": {"contentType": "text", "content": body}},
        )
        return {
            "sent": True,
            "backend": self.name,
            "chat_id": chat_id,
            "message_id": payload.get("id"),
            "created_at": payload.get("createdDateTime"),
            "web_url": payload.get("webUrl"),
        }
