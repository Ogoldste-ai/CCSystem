from __future__ import annotations

import json
import ssl
from typing import Any

import httpx
import truststore

from .config import TeamsConfig

# Power Automate rejects a webhook POST that is not one of the shapes the
# Workflows templates understand. An Adaptive Card is the only one that renders
# reliably now that MessageCard action buttons no longer work.
ADAPTIVE_CARD_VERSION = "1.4"


class WebhookError(RuntimeError):
    """Posting to the Workflows webhook failed."""


def build_adaptive_card(body: str, title: str = "") -> dict[str, Any]:
    """Build the webhook payload.

    The payload deliberately carries the same message twice:

    * ``attachments`` holds an Adaptive Card, for a flow whose final step is
      *Post card in a chat or channel*.
    * ``text`` holds the plain rendering, for the far more common flow built on
      *Post message in a chat or channel*, which treats its Message field as
      text and would otherwise render the card JSON verbatim.

    Carrying both means one payload works with either flow shape, so the flow
    can be rebuilt without a matching code change here. The cost is a few
    duplicated bytes per message, which is irrelevant at this volume.
    """
    blocks: list[dict[str, Any]] = []
    if title:
        blocks.append(
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True}
        )
    blocks.append({"type": "TextBlock", "text": body, "wrap": True})
    return {
        "type": "message",
        "text": f"{title}\n\n{body}" if title else body,
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": ADAPTIVE_CARD_VERSION,
                    "body": blocks,
                },
            }
        ],
    }


class WebhookSender:
    """Posts messages through a Power Automate Workflows webhook.

    Sending is deliberately separate from reading. A Workflows webhook needs no
    Entra app registration, no admin consent and no premium licence, so it very
    often works long before any read path does - but it can only ever send, and
    only to the one chat or channel its URL was created for.

    Messages arrive under the Workflows (Flow) bot identity, not the user's own,
    which is the main trade-off against the Graph backend.
    """

    name = "webhook"

    def __init__(self, config: TeamsConfig, http: Any | None = None) -> None:
        self.config = config
        self._http = http

    def _client(self) -> Any:
        if self._http is None:
            self._http = httpx.Client(
                timeout=self.config.timeout_seconds,
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                headers={"User-Agent": self.config.user_agent},
            )
        return self._http

    def describe(self) -> dict[str, Any]:
        url = self.config.webhook_url
        # The URL embeds a signature and is a credential in its own right, so
        # only ever surface enough of it to tell two webhooks apart.
        host = ""
        if "://" in url:
            host = url.split("://", 1)[1].split("/", 1)[0]
        return {"configured": bool(url), "host": host or None}

    def send(self, body: str, title: str = "") -> dict[str, Any]:
        if not self.config.webhook_url:
            raise WebhookError(
                "TEAMS_WEBHOOK_URL is not set. Create a webhook in Teams via the Workflows "
                "app ('Post to a channel when a webhook request is received', or the chat "
                "equivalent) and set the generated URL."
            )
        payload = build_adaptive_card(body, title)
        try:
            response = self._client().post(self.config.webhook_url, json=payload)
        except Exception as exc:  # network/TLS failures
            raise WebhookError(f"Could not reach the Teams webhook: {exc}") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400:
            detail = str(getattr(response, "text", "") or "").strip()[:300]
            hint = ""
            if status in (401, 403):
                hint = " The webhook URL may have been rotated or the flow turned off."
            elif status == 404:
                hint = " The flow behind this webhook no longer exists."
            raise WebhookError(f"Teams webhook returned HTTP {status}: {detail or 'no body'}.{hint}")
        return {
            "sent": True,
            "via": self.name,
            "http_status": status,
            "posted_as": "Workflows bot (not your personal Teams identity)",
            "body": body,
        }
