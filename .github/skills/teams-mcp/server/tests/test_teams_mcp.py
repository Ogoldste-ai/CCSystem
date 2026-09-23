from __future__ import annotations

import json
from pathlib import Path

import pytest

from teams_mcp.backends.filedrop import FileDropBackend
from teams_mcp.backends.graph import GraphApiError, GraphBackend
from teams_mcp.config import FILEDROP, GRAPH, TeamsConfig, TeamsWriteDisabledError
from teams_mcp.models import Message, parse_timestamp, strip_html
from teams_mcp.sender import WebhookError, WebhookSender
from teams_mcp.store import SeenStore


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def make_config(tmp_path: Path, **overrides) -> TeamsConfig:
    inbox = tmp_path / "inbox"
    outbox = tmp_path / "outbox"
    inbox.mkdir(exist_ok=True)
    outbox.mkdir(exist_ok=True)
    defaults = dict(
        backend=FILEDROP,
        inbox_dir=inbox,
        outbox_dir=outbox,
        archive_dir=outbox / "sent",
        state_file=tmp_path / "state.json",
        allow_write=False,
    )
    defaults.update(overrides)
    return TeamsConfig(**defaults)


def drop(inbox: Path, name: str, payload: dict) -> None:
    (inbox / name).write_text(json.dumps(payload), encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}" if payload is not None else b""
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    """Records Graph calls so assertions can check the URL and body."""

    def __init__(self, routes: dict[tuple[str, str], FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, path: str, **kwargs) -> FakeResponse:
        self.calls.append((method, path, kwargs))
        return self.routes.get((method, path), FakeResponse(404, {"error": {"message": "no route"}}))


def graph_backend(tmp_path: Path, routes: dict, allow_write: bool = True) -> tuple[GraphBackend, FakeHttp]:
    config = make_config(
        tmp_path, backend=GRAPH, client_id="cid", tenant_id="tid", allow_write=allow_write
    )
    http = FakeHttp(routes)
    backend = GraphBackend(config, http=http)
    backend._acquire_token = lambda scopes: "fake-token"  # type: ignore[method-assign]
    return backend, http


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------


def test_strip_html_flattens_teams_markup():
    raw = "<div><p>Hello &amp; welcome</p><p>Second line</p></div>"
    assert strip_html(raw) == "Hello & welcome\nSecond line"


def test_strip_html_handles_breaks_and_entities():
    assert strip_html("a<br>b&nbsp;c") == "a\nb c"


def test_strip_html_empty_input():
    assert strip_html("") == ""


def test_parse_timestamp_accepts_graph_z_suffix():
    parsed = parse_timestamp("2026-09-10T16:50:57.281Z")
    assert parsed is not None and parsed.tzinfo is not None


def test_parse_timestamp_rejects_garbage():
    assert parse_timestamp("not a date") is None


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------


def test_write_guard_blocks_when_disabled(tmp_path):
    config = make_config(tmp_path, allow_write=False)
    with pytest.raises(TeamsWriteDisabledError) as excinfo:
        config.require_write()
    assert "TEAMS_ALLOW_WRITE" in str(excinfo.value)


def test_write_guard_allows_when_enabled(tmp_path):
    make_config(tmp_path, allow_write=True).require_write()


def test_problems_flags_missing_inbox(tmp_path):
    config = make_config(tmp_path, inbox_dir=None)
    assert any("TEAMS_INBOX_DIR" in issue for issue in config.problems())


def test_problems_flags_write_without_outbox(tmp_path):
    config = make_config(tmp_path, outbox_dir=None, allow_write=True)
    assert any("TEAMS_OUTBOX_DIR" in issue for issue in config.problems())


def test_problems_flags_unknown_backend(tmp_path):
    assert config_problem(make_config(tmp_path, backend="carrier-pigeon"), "TEAMS_BACKEND")


def test_problems_flags_missing_client_id(tmp_path):
    config = make_config(tmp_path, backend=GRAPH, client_id="", tenant_id="t")
    assert any("TEAMS_CLIENT_ID" in issue for issue in config.problems())


def config_problem(config: TeamsConfig, needle: str) -> bool:
    return any(needle in issue for issue in config.problems())


def test_clean_config_has_no_problems(tmp_path):
    assert make_config(tmp_path).problems() == []


# --------------------------------------------------------------------------
# filedrop backend
# --------------------------------------------------------------------------


def test_filedrop_parses_camel_case_flow_output(tmp_path):
    config = make_config(tmp_path)
    drop(
        config.inbox_dir,
        "m1.json",
        {
            "id": "1",
            "chatId": "chat-a",
            "from": "Shir Zamir",
            "fromEmail": "szamir@nuvoton.com",
            "createdAt": "2026-09-10T10:00:00Z",
            "body": "<p>ping</p>",
        },
    )
    messages = FileDropBackend(config).fetch_messages("chat-a")
    assert len(messages) == 1
    assert messages[0].sender == "Shir Zamir"
    assert messages[0].body == "ping"


def test_filedrop_accepts_alternate_key_spellings(tmp_path):
    config = make_config(tmp_path)
    drop(
        config.inbox_dir,
        "m2.json",
        {
            "messageId": "2",
            "conversationId": "chat-b",
            "sender": {"displayName": "Bar Issacha"},
            "content": "hello",
            "createdDateTime": "2026-09-10T11:00:00Z",
        },
    )
    messages = FileDropBackend(config).fetch_messages("chat-b")
    assert messages[0].id == "2"
    assert messages[0].sender == "Bar Issacha"


def test_filedrop_skips_malformed_files(tmp_path):
    """A file caught mid-sync must not break the whole listing."""
    config = make_config(tmp_path)
    (config.inbox_dir / "broken.json").write_text("{not json", encoding="utf-8")
    drop(config.inbox_dir, "ok.json", {"id": "3", "chatId": "c", "body": "fine"})
    messages = FileDropBackend(config).fetch_messages("c")
    assert [message.id for message in messages] == ["3"]


def test_filedrop_since_filter(tmp_path):
    config = make_config(tmp_path)
    drop(config.inbox_dir, "a.json", {"id": "a", "chatId": "c", "body": "old", "createdAt": "2026-09-01T00:00:00Z"})
    drop(config.inbox_dir, "b.json", {"id": "b", "chatId": "c", "body": "new", "createdAt": "2026-09-09T00:00:00Z"})
    messages = FileDropBackend(config).fetch_messages("c", since="2026-09-05T00:00:00Z")
    assert [message.id for message in messages] == ["b"]


def test_filedrop_orders_oldest_first(tmp_path):
    config = make_config(tmp_path)
    drop(config.inbox_dir, "b.json", {"id": "b", "chatId": "c", "body": "2", "createdAt": "2026-09-09T00:00:00Z"})
    drop(config.inbox_dir, "a.json", {"id": "a", "chatId": "c", "body": "1", "createdAt": "2026-09-01T00:00:00Z"})
    assert [m.id for m in FileDropBackend(config).fetch_messages("c")] == ["a", "b"]


def test_filedrop_fetch_recent_is_newest_first(tmp_path):
    config = make_config(tmp_path)
    drop(config.inbox_dir, "a.json", {"id": "a", "chatId": "c", "body": "1", "createdAt": "2026-09-01T00:00:00Z"})
    drop(config.inbox_dir, "b.json", {"id": "b", "chatId": "c", "body": "2", "createdAt": "2026-09-09T00:00:00Z"})
    assert [m.id for m in FileDropBackend(config).fetch_recent()] == ["b", "a"]


def test_filedrop_list_chats_groups_and_orders(tmp_path):
    config = make_config(tmp_path)
    drop(config.inbox_dir, "a.json", {"id": "a", "chatId": "old", "body": "1", "createdAt": "2026-09-01T00:00:00Z"})
    drop(config.inbox_dir, "b.json", {"id": "b", "chatId": "new", "body": "2", "createdAt": "2026-09-09T00:00:00Z"})
    assert [chat.id for chat in FileDropBackend(config).list_chats()] == ["new", "old"]


def test_filedrop_reply_writes_json_and_leaves_no_temp(tmp_path):
    config = make_config(tmp_path, allow_write=True)
    result = FileDropBackend(config).send_reply("chat-a", "on it")
    written = list(config.outbox_dir.glob("reply-*.json"))
    assert result["queued"] is True and len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["chatId"] == "chat-a" and payload["body"] == "on it"
    assert list(config.outbox_dir.glob("*.tmp")) == []


def test_filedrop_health_counts_messages(tmp_path):
    config = make_config(tmp_path)
    drop(config.inbox_dir, "a.json", {"id": "a", "chatId": "c", "body": "x"})
    assert FileDropBackend(config).health()["messages_on_disk"] == 1


# --------------------------------------------------------------------------
# seen store
# --------------------------------------------------------------------------


def test_store_suppresses_repeats(tmp_path):
    store = SeenStore(tmp_path / "state.json")
    assert store.mark_seen(["a", "b"]) == 2
    assert store.mark_seen(["b", "c"]) == 1
    assert store.has_seen("a") and not store.has_seen("zz")


def test_store_round_trips_through_disk(tmp_path):
    path = tmp_path / "state.json"
    SeenStore(path).mark_seen(["x"])
    first = SeenStore(path)
    first.mark_seen(["x", "y"])
    first.save()
    assert SeenStore(path).has_seen("y")


def test_store_is_bounded(tmp_path):
    store = SeenStore(tmp_path / "state.json", max_ids=10)
    store.mark_seen(str(index) for index in range(50))
    assert store.stats()["tracked_ids"] == 10
    assert store.has_seen("49") and not store.has_seen("0")


def test_store_tolerates_corrupt_state_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{{{", encoding="utf-8")
    store = SeenStore(path)
    assert store.has_seen("anything") is False


# --------------------------------------------------------------------------
# graph backend
# --------------------------------------------------------------------------


def test_graph_list_chats_normalises_payload(tmp_path):
    routes = {
        ("GET", "/me/chats"): FakeResponse(
            200,
            {
                "value": [
                    {
                        "id": "19:abc",
                        "topic": "",
                        "chatType": "oneOnOne",
                        "lastUpdatedDateTime": "2026-09-10T10:00:00Z",
                        "members": [{"displayName": "Shir Zamir"}],
                    }
                ]
            },
        )
    }
    backend, _ = graph_backend(tmp_path, routes)
    chats = backend.list_chats()
    assert chats[0].id == "19:abc"
    assert chats[0].display_name() == "Shir Zamir"


def test_graph_fetch_recent_uses_last_message_preview(tmp_path):
    routes = {
        ("GET", "/me/chats"): FakeResponse(
            200,
            {
                "value": [
                    {
                        "id": "19:abc",
                        "chatType": "oneOnOne",
                        "members": [{"displayName": "Shir Zamir"}],
                        "lastMessagePreview": {
                            "id": "m9",
                            "createdDateTime": "2026-09-10T12:00:00Z",
                            "from": {"user": {"displayName": "Shir Zamir"}},
                            "body": {"contentType": "html", "content": "<p>hi</p>"},
                        },
                    }
                ]
            },
        )
    }
    backend, http = graph_backend(tmp_path, routes)
    messages = backend.fetch_recent()
    assert [message.body for message in messages] == ["hi"]
    # One request, not one per chat.
    assert len(http.calls) == 1
    assert "lastMessagePreview" in http.calls[0][2]["params"]["$expand"]


def test_graph_fetch_recent_applies_since(tmp_path):
    routes = {
        ("GET", "/me/chats"): FakeResponse(
            200,
            {
                "value": [
                    {
                        "id": "c1",
                        "lastMessagePreview": {
                            "id": "old",
                            "createdDateTime": "2026-09-01T00:00:00Z",
                            "body": {"contentType": "text", "content": "old"},
                        },
                    }
                ]
            },
        )
    }
    backend, _ = graph_backend(tmp_path, routes)
    assert backend.fetch_recent(since="2026-09-05T00:00:00Z") == []


def test_graph_send_reply_posts_text_body(tmp_path):
    routes = {
        ("POST", "/me/chats/19:abc/messages"): FakeResponse(
            201, {"id": "m1", "createdDateTime": "2026-09-10T12:00:00Z"}
        )
    }
    backend, http = graph_backend(tmp_path, routes)
    result = backend.send_reply("19:abc", "on it")
    assert result["sent"] is True and result["message_id"] == "m1"
    assert http.calls[0][2]["json"]["body"]["content"] == "on it"


def test_graph_403_explains_admin_consent(tmp_path):
    routes = {
        ("GET", "/me/chats"): FakeResponse(403, {"error": {"message": "Access denied"}})
    }
    backend, _ = graph_backend(tmp_path, routes)
    with pytest.raises(GraphApiError) as excinfo:
        backend.list_chats()
    assert "administrator consent" in str(excinfo.value)
    assert "AADSTS65001" in str(excinfo.value)


def test_graph_health_reports_auth_failure_without_raising(tmp_path):
    backend, _ = graph_backend(tmp_path, {("GET", "/me"): FakeResponse(401, {"error": {"message": "no"}})})
    info = backend.health()
    assert info["authenticated"] is False and "auth_error" in info


def test_graph_fetch_messages_requires_chat_id(tmp_path):
    backend, _ = graph_backend(tmp_path, {})
    with pytest.raises(ValueError):
        backend.fetch_messages("")


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------


def test_backend_selection_follows_config(tmp_path):
    from teams_mcp.server import build_backend

    assert build_backend(make_config(tmp_path)).name == "filedrop"
    assert build_backend(make_config(tmp_path, backend=GRAPH, client_id="c", tenant_id="t")).name == "graph"


def test_message_to_dict_is_stable():
    message = Message(id="1", chat_id="c", body="hi", sender="S")
    assert set(message.to_dict()) == {
        "id",
        "chat_id",
        "chat_name",
        "sender",
        "sender_email",
        "created_at",
        "is_from_me",
        "body",
        "web_url",
    }


# --------------------------------------------------------------------------
# webhook sender
# --------------------------------------------------------------------------


class FakeWebhookHttp:
    def __init__(self, status: int = 202, text: str = "") -> None:
        self.status = status
        self.text = text
        self.posts: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict) -> FakeResponse:  # noqa: A002
        self.posts.append((url, json))
        response = FakeResponse(self.status, {})
        response.text = self.text
        return response


def webhook_config(tmp_path: Path, url: str = "https://prod-1.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke?sig=SECRET"):
    return make_config(tmp_path, webhook_url=url, allow_write=True)


def test_webhook_builds_adaptive_card(tmp_path):
    http = FakeWebhookHttp()
    sender = WebhookSender(webhook_config(tmp_path), http=http)
    result = sender.send("hello there", title="Update")
    assert result["sent"] is True
    payload = http.posts[0][1]
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    texts = [block["text"] for block in card["body"]]
    assert texts == ["Update", "hello there"]


def test_webhook_omits_title_block_when_absent(tmp_path):
    http = FakeWebhookHttp()
    WebhookSender(webhook_config(tmp_path), http=http).send("just body")
    card = http.posts[0][1]["attachments"][0]["content"]
    assert [block["text"] for block in card["body"]] == ["just body"]


def test_webhook_payload_carries_plain_text_alongside_the_card(tmp_path):
    # A flow built on "Post message in a chat or channel" binds a text field and
    # renders card JSON verbatim, so the plain rendering has to travel too.
    http = FakeWebhookHttp()
    WebhookSender(webhook_config(tmp_path), http=http).send("hello there", title="Update")
    assert http.posts[0][1]["text"] == "Update\n\nhello there"


def test_webhook_plain_text_is_just_the_body_without_a_title(tmp_path):
    http = FakeWebhookHttp()
    WebhookSender(webhook_config(tmp_path), http=http).send("just body")
    assert http.posts[0][1]["text"] == "just body"


def test_webhook_result_states_it_is_not_your_identity(tmp_path):
    http = FakeWebhookHttp()
    result = WebhookSender(webhook_config(tmp_path), http=http).send("hi")
    assert "Workflows bot" in result["posted_as"]


def test_webhook_without_url_explains_how_to_create_one(tmp_path):
    sender = WebhookSender(make_config(tmp_path, webhook_url="", allow_write=True))
    with pytest.raises(WebhookError) as excinfo:
        sender.send("hi")
    assert "TEAMS_WEBHOOK_URL" in str(excinfo.value)
    assert "Workflows" in str(excinfo.value)


def test_webhook_http_error_is_actionable(tmp_path):
    http = FakeWebhookHttp(status=404, text="not found")
    sender = WebhookSender(webhook_config(tmp_path), http=http)
    with pytest.raises(WebhookError) as excinfo:
        sender.send("hi")
    assert "404" in str(excinfo.value)
    assert "no longer exists" in str(excinfo.value)


def test_webhook_describe_never_leaks_the_signature(tmp_path):
    """The webhook URL embeds a signature and is itself a credential."""
    config = webhook_config(tmp_path)
    described = WebhookSender(config).describe()
    assert described["configured"] is True
    assert described["host"] == "prod-1.westeurope.logic.azure.com"
    assert "SECRET" not in json.dumps(described)


def test_webhook_describe_reports_unconfigured(tmp_path):
    assert WebhookSender(make_config(tmp_path, webhook_url="")).describe()["configured"] is False


def test_config_allows_write_with_webhook_and_no_outbox(tmp_path):
    config = make_config(tmp_path, outbox_dir=None, allow_write=True, webhook_url="https://x/y")
    assert config.problems() == []


def test_config_flags_write_with_neither_outbox_nor_webhook(tmp_path):
    config = make_config(tmp_path, outbox_dir=None, allow_write=True, webhook_url="")
    assert any("TEAMS_WEBHOOK_URL" in issue for issue in config.problems())
