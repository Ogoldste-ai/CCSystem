from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

import teams_mcp.filedrop_scan as scanner_module
from teams_mcp.backends.filedrop import FileDropBackend
from teams_mcp.config import TeamsConfig
from teams_mcp.filedrop_scan import FileDropScanError, FileDropScanner, ScanResult
from teams_mcp.models import Message
from teams_mcp.server import build_server
from teams_mcp.store import SeenStore


@pytest.fixture
def config(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return TeamsConfig(inbox_dir=inbox, state_file=tmp_path / "seen.json")


def drop(config, name="message.json", **fields):
    payload = {"id": name, "chatId": "chat", "body": "<p>hello</p>"}
    payload.update(fields)
    (config.inbox_dir / name).write_text(json.dumps(payload), encoding="utf-8")


async def call(server, name="check_new_messages", **arguments):
    tool = server._tool_manager.get_tool(name)
    assert tool is not None
    return await tool.run(arguments)


@pytest.fixture
def workers(monkeypatch):
    original = anyio.open_process
    processes = []

    def install(script=None, spawned=None, delay_spawn=False):
        async def open_process(command, **kwargs):
            if script is not None:
                command = [sys.executable, "-u", "-c", script]
            process = await original(command, **kwargs)
            processes.append(process)
            if spawned is not None:
                spawned.set()
            if delay_spawn:
                await anyio.sleep(0.1)
            return process

        monkeypatch.setattr(scanner_module.anyio, "open_process", open_process)

    yield install, processes
    assert all(process.returncode is not None for process in processes)


def stalled_worker(messages=()):
    event = ScanResult(messages=list(messages)).diagnostics()
    event.update(finished=False, messages=[message.to_dict() for message in messages])
    return (
        "import json, sys, time; json.load(sys.stdin); "
        f"print({json.dumps(event)!r}, flush=True); time.sleep(60)"
    )


@pytest.mark.parametrize("attributes", [0x00400020, 0x00001020, 0x00480020])
def test_cloud_files_are_not_opened(config, monkeypatch, attributes):
    drop(config, "cloud.json")
    original_stat = Path.stat
    original_read = Path.read_text

    def stat(path, *args, **kwargs):
        if path.name == "cloud.json":
            return SimpleNamespace(st_file_attributes=attributes)
        return original_stat(path, *args, **kwargs)

    def read(path, *args, **kwargs):
        assert path.name != "cloud.json", "A deferred file must never be opened"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(Path, "read_text", read)
    result = FileDropBackend(config).scan()
    assert not result.complete and result.finished
    assert result.deferred_files == 1
    assert result.messages == []


def test_mixed_files_are_retried_after_hydration(config, monkeypatch):
    drop(config, "local.json")
    drop(config, "cloud.json")
    original_stat = Path.stat
    cloud = True

    def stat(path, *args, **kwargs):
        if path.name == "cloud.json" and cloud:
            return SimpleNamespace(st_file_attributes=0x00400000)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    backend = FileDropBackend(config)
    first = backend.scan()
    assert [message.id for message in first.messages] == ["local.json"]
    assert first.deferred_files == 1 and not first.complete
    cloud = False
    second = backend.scan()
    assert second.complete and len(second.messages) == 2


def test_disappearing_and_unreadable_files_are_reported(config, monkeypatch):
    drop(config)
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path.name == "message.json":
            raise FileNotFoundError("File disappeared during sync")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    result = FileDropBackend(config).scan()
    assert result.unreadable_files == 1 and not result.complete


def test_edited_and_replaced_files_are_not_cached(config):
    drop(config, body="first")
    backend = FileDropBackend(config)
    assert backend.scan().messages[0].body == "first"
    drop(config, body="edited")
    assert backend.scan().messages[0].body == "edited"
    (config.inbox_dir / "message.json").unlink()
    assert backend.scan().complete and backend.scan().messages == []


@pytest.mark.parametrize("body", ["{", "42", '[{"id": "ok", "body": "hi"}, null]'])
def test_invalid_files_are_partial_and_retryable(config, body):
    path = config.inbox_dir / "invalid.json"
    path.write_text(body, encoding="utf-8")
    backend = FileDropBackend(config)
    result = backend.scan()
    assert result.invalid_files == 1 and not result.complete
    path.write_text('{"id": "fixed", "body": "ok"}', encoding="utf-8")
    assert backend.scan().complete


def test_unreadable_content_is_partial(config, monkeypatch):
    drop(config)

    def read(*args, **kwargs):
        raise PermissionError("File still syncing")

    monkeypatch.setattr(Path, "read_text", read)
    result = FileDropBackend(config).scan()
    assert result.unreadable_files == 1 and not result.complete


def test_recent_preserves_order_for_equal_timestamps():
    result = ScanResult(messages=[Message("a", "c", "one"), Message("b", "c", "two")])
    assert [message.id for message in result.recent()] == ["b", "a"]


def test_real_worker_reads_all_supported_payloads(config):
    drop(config, "one.json", createdAt="2026-10-26T01:00:00Z")
    (config.inbox_dir / "array.json").write_text(
        '[{"id": "two", "chatId": "chat", "body": "second"}]', encoding="utf-8"
    )
    (config.inbox_dir / "notification.json").write_text(
        '{"value": [{"subscriptionId": "sub", "messageId": "notification"}]}', encoding="utf-8"
    )
    result = asyncio.run(FileDropScanner(config).scan())
    assert result.complete and result.files_scanned == 3
    assert {message.id for message in result.messages} == {"one.json", "two"}
    assert result.elapsed_ms < 5000


def test_complete_checks_keep_limits_order_and_seen_semantics(config):
    drop(config, "old.json", createdAt="2026-10-25T01:00:00Z")
    drop(config, "new.json", createdAt="2026-10-26T01:00:00Z")
    server = build_server(config)

    async def run():
        peek = await call(server, limit=1, mark_seen=False)
        assert peek["complete"] and not peek["marked_seen"]
        assert peek["messages"][0]["id"] == "new.json"
        assert not config.state_file.exists()
        first = await call(server, limit=1)
        second = await call(server, limit=1)
        third = await call(server, limit=1)
        assert first["marked_seen"] and second["marked_seen"]
        assert second["messages"][0]["id"] == "old.json"
        assert third["complete"] and third["new_count"] == 0
        messages = await call(server, "read_messages", chat_id="chat")
        assert [message["id"] for message in messages] == ["old.json", "new.json"]
        chats = await call(server, "list_chats")
        assert chats[0]["id"] == "chat"
        message = await call(server, "get_message", message_id="new.json")
        assert message["id"] == "new.json"

    asyncio.run(run())
    assert SeenStore(config.state_file).stats()["tracked_ids"] == 2


@pytest.mark.parametrize("with_local", [True, False])
def test_partial_checks_warn_and_never_persist_seen(config, with_local):
    (config.inbox_dir / "syncing.json").write_text("{", encoding="utf-8")
    if with_local:
        drop(config)
    server = build_server(config)

    async def run():
        first = await call(server)
        second = await call(server)
        assert not first["complete"] and not first["marked_seen"]
        assert first["scan"]["invalid_files"] == 1
        assert "does not mean there are no new messages" in first["warning"]
        assert first["new_count"] == int(with_local)
        assert second["new_count"] == first["new_count"]
        assert not config.state_file.exists()

    asyncio.run(run())


@pytest.mark.parametrize("name,arguments", [
    ("list_chats", {}),
    ("read_messages", {"chat_id": "chat"}),
    ("get_message", {"message_id": "missing"}),
])
def test_other_reads_do_not_hide_incomplete_scans(config, name, arguments):
    (config.inbox_dir / "syncing.json").write_text("{", encoding="utf-8")
    with pytest.raises(ToolError, match="Incomplete Teams inbox scan"):
        asyncio.run(call(build_server(config), name, **arguments))


def test_hung_worker_times_out_preserves_progress_and_recovers(config, monkeypatch, workers):
    install, processes = workers
    install(stalled_worker([Message("partial", "chat", "available")]))
    monkeypatch.setattr(scanner_module, "SCAN_TIMEOUT_SECONDS", 0.5)
    scanner = FileDropScanner(config)

    async def run():
        started = time.perf_counter()
        partial = await scanner.scan()
        assert partial.timed_out and not partial.complete
        assert [message.id for message in partial.messages] == ["partial"]
        assert time.perf_counter() - started < 3
        assert processes[0].returncode is not None
        install()
        monkeypatch.setattr(scanner_module, "SCAN_TIMEOUT_SECONDS", 3)
        assert (await scanner.scan()).complete

    asyncio.run(run())


def test_health_and_overlapping_calls_remain_responsive(config, monkeypatch, workers):
    install, processes = workers
    monkeypatch.setattr(scanner_module, "SCAN_TIMEOUT_SECONDS", 1)
    server = build_server(config)

    async def run():
        spawned = asyncio.Event()
        install(stalled_worker(), spawned=spawned)
        checking = asyncio.create_task(call(server))
        await asyncio.wait_for(spawned.wait(), 2)
        started = time.perf_counter()
        assert (await call(server, "health"))["status"] == "ok"
        with pytest.raises(ToolError, match="already running"):
            await call(server)
        assert time.perf_counter() - started < 0.5
        result = await checking
        assert result["scan"]["timed_out"] and not result["marked_seen"]
        assert not config.state_file.exists()

    asyncio.run(run())


@pytest.mark.parametrize("delay_spawn", [False, True])
def test_cancellation_reaps_worker_without_consuming_messages(config, workers, delay_spawn):
    install, processes = workers
    server = build_server(config)

    async def run():
        spawned = asyncio.Event()
        install(stalled_worker(), spawned=spawned, delay_spawn=delay_spawn)
        checking = asyncio.create_task(call(server))
        await asyncio.wait_for(spawned.wait(), 2)
        checking.cancel()
        with pytest.raises(asyncio.CancelledError):
            await checking
        assert processes[0].returncode is not None
        assert not config.state_file.exists()
        install()
        assert (await call(server, mark_seen=False))["complete"]

    asyncio.run(run())


def test_anyio_cancellation_reaps_worker(config, workers):
    install, processes = workers

    async def run():
        spawned = anyio.Event()
        install(stalled_worker(), spawned=spawned)
        async with anyio.create_task_group() as group:
            group.start_soon(FileDropScanner(config).scan)
            await spawned.wait()
            group.cancel_scope.cancel()
        assert processes[0].returncode is not None
        assert not config.state_file.exists()

    anyio.run(run)


@pytest.mark.parametrize("script", [
    "import sys; sys.exit(7)",
    "print('not a scanner event', flush=True)",
])
def test_worker_failure_is_an_error_not_empty_success(config, workers, script):
    install, processes = workers
    install(script)
    with pytest.raises(FileDropScanError, match="scanner failed"):
        asyncio.run(FileDropScanner(config).scan())


def test_worker_config_errors_are_actionable(config):
    config.inbox_dir = None
    with pytest.raises(FileDropScanError, match="TEAMS_INBOX_DIR"):
        asyncio.run(FileDropScanner(config).scan())


def test_cancellation_after_scan_does_not_mark_seen(config, monkeypatch):
    async def scan(scanner):
        asyncio.current_task().cancel()
        return ScanResult(messages=[Message("new", "chat", "hello")], finished=True)

    monkeypatch.setattr(FileDropScanner, "scan", scan)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call(build_server(config)))
    assert not config.state_file.exists()


def test_graph_check_response_is_unchanged(config, monkeypatch):
    from teams_mcp.backends.graph import GraphBackend
    from teams_mcp.config import GRAPH

    config.backend = GRAPH
    monkeypatch.setattr(
        GraphBackend, "fetch_recent",
        lambda self, **kwargs: [Message("graph", "chat", "hello")],
    )
    response = asyncio.run(call(build_server(config), mark_seen=False))
    assert set(response) == {"new_count", "marked_seen", "messages"}
    assert response["new_count"] == 1 and not response["marked_seen"]


def test_people_tools_explain_filedrop_directory_limit(config):
    config.allow_write = True
    server = build_server(config)

    async def run():
        with pytest.raises(ToolError, match="requires TEAMS_BACKEND=graph"):
            await call(server, "search_people", query="gbarak")
        with pytest.raises(ToolError, match="requires TEAMS_BACKEND=graph"):
            await call(server, "start_chat", user_id="01234567-89ab-cdef-0123-456789abcdef")

    asyncio.run(run())


def test_people_tools_forward_to_graph_backend(config, monkeypatch):
    from teams_mcp.backends.graph import GraphBackend
    from teams_mcp.config import GRAPH

    config.backend = GRAPH
    config.client_id = "client"
    config.tenant_id = "tenant"
    config.allow_write = True
    monkeypatch.setattr(
        GraphBackend, "search_people", lambda self, query, limit=10: [{"id": "person-1", "query": query}]
    )
    monkeypatch.setattr(
        GraphBackend, "start_chat", lambda self, user_id: {"started": True, "user_id": user_id}
    )
    server = build_server(config)

    async def run():
        people = await call(server, "search_people", query="gbarak")
        chat = await call(server, "start_chat", user_id="person-1")
        assert people == [{"id": "person-1", "query": "gbarak"}]
        assert chat == {"started": True, "user_id": "person-1"}

    asyncio.run(run())


def test_start_chat_requires_write_permission(config):
    from teams_mcp.config import GRAPH

    config.backend = GRAPH
    config.client_id = "client"
    config.tenant_id = "tenant"
    config.allow_write = False
    server = build_server(config)

    with pytest.raises(ToolError, match="Teams write operations are disabled"):
        asyncio.run(call(server, "start_chat", user_id="01234567-89ab-cdef-0123-456789abcdef"))


def test_stdio_transport_returns_scan_diagnostics(config):
    drop(config)

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "teams_mcp.server"],
            env={
                "TEAMS_BACKEND": "filedrop",
                "TEAMS_INBOX_DIR": str(config.inbox_dir),
                "TEAMS_STATE_FILE": str(config.state_file),
                "TEAMS_ALLOW_WRITE": "0",
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                response = await session.call_tool("check_new_messages", {"mark_seen": False})
                assert not response.isError
                result = json.loads(response.content[0].text)
                assert result["complete"] and result["new_count"] == 1
                assert "scan" in result and not result["marked_seen"]

    asyncio.run(run())
    assert not config.state_file.exists()
