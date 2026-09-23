from __future__ import annotations

import httpx
import pytest

from gitlab_mcp.client import (
    GitLabApiError,
    GitLabClient,
    GitLabConfig,
    GitLabWriteDisabledError,
)

PROJECT = "/projects/group%2Fproject"
DIFF_REFS = {"base_sha": "base1", "head_sha": "head1", "start_sha": "start1"}


class FakeResponse:
    def __init__(self, payload, text: str = "", status_code: int = 200) -> None:
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://gitlab.example.com"),
                response=self,  # type: ignore[arg-type]
            )

    def json(self):
        return self._payload


def _note(note_id: int, body: str, *, system: bool = False, **extra):
    note = {
        "id": note_id,
        "author": {"username": "alice"},
        "body": body,
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-01T10:00:00Z",
        "system": system,
    }
    note.update(extra)
    return note


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict, dict | None]] = []
        self.discussion_pages: dict[int, list] = {}
        self.collapse_diffs = False

    def request(self, method: str, path: str, params=None, json=None, headers=None):
        params = params or {}
        self.calls.append((method, path, params, headers or {}, json))

        if path == "/user":
            return FakeResponse({"id": 7, "username": "ogoldste", "name": "Oren Goldstein"})
        if path == PROJECT:
            return FakeResponse(
                {
                    "id": 55,
                    "path_with_namespace": "group/project",
                    "name": "project",
                    "web_url": "https://gitlab.example.com/group/project",
                    "default_branch": "main",
                    "visibility": "private",
                }
            )
        if path == f"{PROJECT}/merge_requests":
            return FakeResponse(
                [
                    {
                        "iid": 12,
                        "title": "Fix SPI boot flow",
                        "state": "opened",
                        "author": {"username": "alice"},
                        "reviewers": [{"username": "carol", "name": "Carol"}],
                        "assignees": [{"username": "dave", "name": "Dave"}],
                        "draft": False,
                        "web_url": "https://gitlab.example.com/group/project/-/merge_requests/12",
                        "source_branch": "fix/spi",
                        "target_branch": "main",
                        "updated_at": "2026-08-30T12:00:00Z",
                        "merge_status": "can_be_merged",
                        "detailed_merge_status": "mergeable",
                        "has_conflicts": False,
                        "sha": "abc123",
                    }
                ]
            )
        if path == f"{PROJECT}/merge_requests/12":
            return FakeResponse(
                {
                    "iid": 12,
                    "title": "Fix SPI boot flow",
                    "description": "body",
                    "state": "opened",
                    "author": {"username": "alice", "name": "Alice", "avatar_url": "x"},
                    "reviewers": [{"username": "carol", "name": "Carol", "avatar_url": "x"}],
                    "assignees": [{"username": "dave", "name": "Dave", "avatar_url": "x"}],
                    "head_pipeline": {
                        "id": 900,
                        "status": "failed",
                        "ref": "fix/spi",
                        "sha": "abc123",
                        "web_url": "https://gitlab.example.com/pipelines/900",
                    },
                    "detailed_merge_status": "mergeable",
                    "has_conflicts": False,
                    "blocking_discussions_resolved": False,
                    "user_notes_count": 3,
                    "changes_count": "2",
                    "diff_refs": DIFF_REFS,
                    "sha": "abc123",
                }
            )
        if path == f"{PROJECT}/merge_requests/12/approvals":
            return FakeResponse({"message": "404 Not Found"}, status_code=404)
        if path == f"{PROJECT}/merge_requests/12/pipelines":
            return FakeResponse(
                [
                    {
                        "id": 900,
                        "iid": 4,
                        "status": "failed",
                        "source": "merge_request_event",
                        "ref": "fix/spi",
                        "sha": "abc123",
                        "web_url": "https://gitlab.example.com/pipelines/900",
                        "created_at": "2026-09-01T09:00:00Z",
                        "updated_at": "2026-09-01T09:30:00Z",
                        "extra_noise": "dropped",
                    }
                ]
            )
        if path == f"{PROJECT}/pipelines/900/jobs":
            return FakeResponse(
                [
                    {
                        "id": 7001,
                        "name": "build-ec",
                        "stage": "build",
                        "status": "failed",
                        "allow_failure": False,
                        "failure_reason": "script_failure",
                        "duration": 42.5,
                        "started_at": "2026-09-01T09:05:00Z",
                        "finished_at": "2026-09-01T09:06:00Z",
                        "web_url": "https://gitlab.example.com/jobs/7001",
                        "extra_noise": "dropped",
                    }
                ]
            )
        if path == f"{PROJECT}/merge_requests/12/discussions":
            if method == "POST":
                return FakeResponse(
                    {
                        "id": "newdisc",
                        "individual_note": False,
                        "notes": [_note(5001, json["body"], resolvable=True, resolved=False, position=json["position"])],
                    }
                )
            page = int(params.get("page", 1))
            return FakeResponse(self.discussion_pages.get(page, []))
        if path == f"{PROJECT}/merge_requests/12/discussions/disc1":
            return FakeResponse(
                {
                    "id": "disc1",
                    "individual_note": False,
                    "notes": [_note(101, "Please rename", resolvable=True, resolved=json["resolved"])],
                }
            )
        if path == f"{PROJECT}/merge_requests/12/discussions/disc1/notes":
            return FakeResponse(_note(3001, json["body"]))
        if path == f"{PROJECT}/merge_requests/12/notes":
            return FakeResponse(_note(2001, json["body"]))
        if path == f"{PROJECT}/merge_requests/12/changes":
            return FakeResponse(
                {
                    "iid": 12,
                    "title": "Fix SPI boot flow",
                    "state": "opened",
                    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/12",
                    "sha": "abc123",
                    "diff_refs": DIFF_REFS,
                    "changes_count": "2",
                    "changes": [
                        {
                            "old_path": "EC/spi.c",
                            "new_path": "EC/spi.c",
                            "new_file": False,
                            "renamed_file": False,
                            "deleted_file": False,
                            "diff": "" if self.collapse_diffs else "@@ -1 +1 @@\n-old\n+new\n",
                        },
                        {
                            "old_path": "docs/readme.md",
                            "new_path": "docs/readme.md",
                            "new_file": False,
                            "renamed_file": False,
                            "deleted_file": False,
                            "diff": "" if self.collapse_diffs else "@@ -2 +2 @@\n-a\n+b\n",
                        },
                    ],
                }
            )
        if path == f"{PROJECT}/merge_requests/12/raw_diffs":
            return FakeResponse({}, text="diff --git a/a.txt b/a.txt")
        if path == f"{PROJECT}/issues":
            return FakeResponse(
                [
                    {
                        "iid": 88,
                        "title": "Track boot timeout",
                        "state": "opened",
                        "author": {"username": "bob"},
                        "assignees": [{"username": "carol"}],
                        "labels": ["boot"],
                        "web_url": "https://gitlab.example.com/group/project/-/issues/88",
                        "updated_at": "2026-08-30T10:00:00Z",
                    }
                ]
            )
        if path == f"{PROJECT}/repository/branches":
            return FakeResponse(
                [
                    {
                        "name": "main",
                        "default": True,
                        "merged": False,
                        "protected": True,
                        "web_url": "https://gitlab.example.com/group/project/-/tree/main",
                        "commit": {
                            "short_id": "aaa111",
                            "title": "Main tip",
                            "author_name": "Bob",
                            "author_email": "bob@example.com",
                            "committed_date": "2026-08-01T10:00:00Z",
                        },
                    },
                    {
                        "name": "feature/bmc-boot",
                        "default": False,
                        "merged": False,
                        "protected": False,
                        "web_url": "https://gitlab.example.com/group/project/-/tree/feature/bmc-boot",
                        "commit": {
                            "short_id": "bbb222",
                            "title": "Boot work",
                            "author_name": "Oren Goldstein",
                            "author_email": "ogoldste@example.com",
                            "committed_date": "2026-09-01T10:00:00Z",
                        },
                    },
                ]
            )
        raise AssertionError(f"Unexpected path: {path}")

    def close(self) -> None:
        return None


def make_client(*, allow_write: bool = False) -> GitLabClient:
    client = GitLabClient(
        GitLabConfig(
            base_url="https://gitlab.example.com/api/v4",
            token="token",
            default_project="group/project",
            allow_write=allow_write,
        )
    )
    client._client = FakeHttpClient()
    return client


def test_health_uses_user_endpoint() -> None:
    client = make_client()
    health = client.health()

    assert health["status"] == "ok"
    assert health["user"]["username"] == "ogoldste"
    assert health["default_project"] == "group/project"
    assert health["write_enabled"] is False


def test_health_reports_write_enabled() -> None:
    assert make_client(allow_write=True).health()["write_enabled"] is True


def test_list_merge_requests_formats_summary() -> None:
    client = make_client()
    result = client.list_merge_requests(search="spi")

    assert result[0]["iid"] == 12
    assert result[0]["author"] == "alice"
    assert result[0]["source_branch"] == "fix/spi"
    assert result[0]["reviewers"] == ["carol"]
    assert result[0]["assignees"] == ["dave"]
    assert result[0]["detailed_merge_status"] == "mergeable"

    method, path, params, _headers, _json = client._client.calls[-1]
    assert method == "GET"
    assert path == f"{PROJECT}/merge_requests"
    assert params["search"] == "spi"
    assert params["page"] == 1


def test_get_merge_request_includes_review_status() -> None:
    client = make_client()
    result = client.get_merge_request("group/project", 12)

    assert result["reviewers"] == [{"username": "carol", "name": "Carol"}]
    assert result["assignees"] == [{"username": "dave", "name": "Dave"}]
    assert result["head_pipeline"]["status"] == "failed"
    assert result["head_pipeline"]["id"] == 900
    assert result["blocking_discussions_resolved"] is False
    assert result["diff_refs"] == DIFF_REFS


def test_get_merge_request_approvals_degrades_on_404() -> None:
    client = make_client()
    result = client.get_merge_request_approvals("group/project", 12)

    assert result["supported"] is False
    assert "Premium" in result["reason"]


def test_get_merge_request_pipelines_trims_fields() -> None:
    client = make_client()
    result = client.get_merge_request_pipelines("group/project", 12)

    assert result[0]["status"] == "failed"
    assert "extra_noise" not in result[0]


def test_get_pipeline_jobs_trims_fields_and_passes_scope() -> None:
    client = make_client()
    result = client.get_pipeline_jobs("group/project", 900, scope="failed")

    assert result[0]["name"] == "build-ec"
    assert result[0]["failure_reason"] == "script_failure"
    assert "extra_noise" not in result[0]

    _method, _path, params, _headers, _json = client._client.calls[-1]
    assert params["scope[]"] == "failed"


def test_discussions_paginate_and_drop_system_notes() -> None:
    client = make_client()
    real = [
        {
            "id": "disc1",
            "individual_note": False,
            "notes": [
                _note(
                    101,
                    "Please rename",
                    resolvable=True,
                    resolved=False,
                    position={"new_path": "EC/spi.c", "new_line": 10},
                )
            ],
        },
        {"id": "sys1", "individual_note": True, "notes": [_note(102, "added 1 commit", system=True)]},
    ]
    # The first page must be full (100 items) for pagination to request page 2.
    padding = [
        {"id": f"pad{i}", "individual_note": True, "notes": [_note(200 + i, "pad")]} for i in range(98)
    ]
    client._client.discussion_pages = {1: real + padding, 2: []}

    result = client.list_merge_request_discussions("group/project", 12)

    assert result[0]["id"] == "disc1"
    assert result[0]["file"] == "EC/spi.c"
    assert result[0]["resolved"] is False
    assert result[0]["notes"][0]["position"]["new_line"] == 10
    assert all(discussion["id"] != "sys1" for discussion in result)

    pages = [params["page"] for _m, path, params, _h, _j in client._client.calls if path.endswith("/discussions")]
    assert pages == [1, 2]


def test_discussions_include_system_and_resolved_filter() -> None:
    client = make_client()
    client._client.discussion_pages = {
        1: [
            {"id": "disc1", "individual_note": False, "notes": [_note(101, "a", resolvable=True, resolved=True)]},
            {"id": "disc2", "individual_note": False, "notes": [_note(102, "b", resolvable=True, resolved=False)]},
            {"id": "sys1", "individual_note": True, "notes": [_note(103, "added 1 commit", system=True)]},
        ]
    }

    assert [d["id"] for d in client.list_merge_request_discussions("group/project", 12, include_system=True)] == [
        "disc1",
        "disc2",
        "sys1",
    ]
    assert [d["id"] for d in client.list_merge_request_discussions("group/project", 12, resolved=False)] == ["disc2"]


def test_list_merge_request_changes_returns_diff_refs_and_files() -> None:
    client = make_client()
    result = client.list_merge_request_changes("group/project", 12)

    assert result["diff_refs"] == DIFF_REFS
    assert result["files_returned"] == 2
    assert result["files"][0]["new_path"] == "EC/spi.c"
    assert result["files"][0]["diff"].startswith("@@")
    assert "warning" not in result

    _method, _path, params, _headers, _json = client._client.calls[-1]
    assert params["access_raw_diffs"] == "true"


def test_list_merge_request_changes_flags_collapsed_diffs() -> None:
    client = make_client()
    client._client.collapse_diffs = True
    result = client.list_merge_request_changes("group/project", 12)

    assert result["files"][0]["diff"] == ""
    assert result["files"][0]["diff_collapsed"] is True
    assert "2 file diff(s) came back empty" in result["warning"]
    assert "get_merge_request_raw_diff" in result["warning"]


def test_list_merge_request_changes_can_disable_raw_diffs() -> None:
    client = make_client()
    client.list_merge_request_changes("group/project", 12, access_raw_diffs=False)

    _method, _path, params, _headers, _json = client._client.calls[-1]
    assert "access_raw_diffs" not in params


def test_list_merge_request_changes_filters_and_omits_diff() -> None:
    client = make_client()
    result = client.list_merge_request_changes("group/project", 12, path_filter="docs/", include_diff=False)

    assert result["files_returned"] == 1
    assert result["files"][0]["new_path"] == "docs/readme.md"
    assert "diff" not in result["files"][0]


def test_get_merge_request_raw_diff_returns_diff_text() -> None:
    client = make_client()
    result = client.get_merge_request_raw_diff("group/project", 12)

    assert result["content_type"] == "text/x-diff"
    assert "diff --git" in result["diff"]


def test_write_tools_blocked_when_write_disabled() -> None:
    client = make_client()

    with pytest.raises(GitLabWriteDisabledError, match="GITLAB_ALLOW_WRITE"):
        client.create_merge_request_note("group/project", 12, "hello")
    with pytest.raises(GitLabWriteDisabledError):
        client.create_merge_request_diff_comment("group/project", 12, "hi", new_path="EC/spi.c", new_line=10)
    with pytest.raises(GitLabWriteDisabledError):
        client.reply_to_merge_request_discussion("group/project", 12, "disc1", "hi")
    with pytest.raises(GitLabWriteDisabledError):
        client.resolve_merge_request_discussion("group/project", 12, "disc1")

    assert client._client.calls == []


def test_create_merge_request_note_posts_json_body() -> None:
    client = make_client(allow_write=True)
    result = client.create_merge_request_note("group/project", 12, "Looks good")

    assert result["body"] == "Looks good"
    method, path, _params, _headers, json_body = client._client.calls[-1]
    assert method == "POST"
    assert path == f"{PROJECT}/merge_requests/12/notes"
    assert json_body == {"body": "Looks good"}


def test_create_diff_comment_autofills_shas() -> None:
    client = make_client(allow_write=True)
    result = client.create_merge_request_diff_comment(
        "group/project", 12, "Off by one", new_path="EC/spi.c", new_line=10
    )

    assert result["id"] == "newdisc"
    method, path, _params, _headers, json_body = client._client.calls[-1]
    assert method == "POST"
    assert path == f"{PROJECT}/merge_requests/12/discussions"
    assert json_body["position"]["position_type"] == "text"
    assert json_body["position"]["base_sha"] == "base1"
    assert json_body["position"]["head_sha"] == "head1"
    assert json_body["position"]["start_sha"] == "start1"
    assert json_body["position"]["new_line"] == 10
    assert json_body["position"]["old_path"] == "EC/spi.c"
    assert "old_line" not in json_body["position"]


def test_create_diff_comment_keeps_explicit_shas() -> None:
    client = make_client(allow_write=True)
    client.create_merge_request_diff_comment(
        "group/project",
        12,
        "Removed line",
        old_path="EC/spi.c",
        old_line=4,
        base_sha="b2",
        head_sha="h2",
        start_sha="s2",
    )

    fetched_mr = [path for _m, path, _p, _h, _j in client._client.calls if path == f"{PROJECT}/merge_requests/12"]
    assert fetched_mr == []

    _method, _path, _params, _headers, json_body = client._client.calls[-1]
    assert json_body["position"]["head_sha"] == "h2"
    assert json_body["position"]["old_line"] == 4
    assert json_body["position"]["new_path"] == "EC/spi.c"


def test_create_diff_comment_requires_anchor() -> None:
    client = make_client(allow_write=True)

    with pytest.raises(ValueError, match="new_path or old_path"):
        client.create_merge_request_diff_comment("group/project", 12, "hi", new_line=3)
    with pytest.raises(ValueError, match="new_line or old_line"):
        client.create_merge_request_diff_comment("group/project", 12, "hi", new_path="EC/spi.c")
    with pytest.raises(ValueError, match="non-empty"):
        client.create_merge_request_diff_comment("group/project", 12, "   ", new_path="EC/spi.c", new_line=3)


def test_reply_and_resolve_discussion() -> None:
    client = make_client(allow_write=True)

    reply = client.reply_to_merge_request_discussion("group/project", 12, "disc1", "Fixed")
    assert reply["body"] == "Fixed"

    resolved = client.resolve_merge_request_discussion("group/project", 12, "disc1")
    assert resolved["resolved"] is True

    method, path, _params, _headers, json_body = client._client.calls[-1]
    assert method == "PUT"
    assert path == f"{PROJECT}/merge_requests/12/discussions/disc1"
    assert json_body == {"resolved": True}


def test_api_error_includes_status_and_hint() -> None:
    client = make_client()

    with pytest.raises(GitLabApiError) as excinfo:
        client._request("GET", f"{PROJECT}/merge_requests/12/approvals")

    assert excinfo.value.status_code == 404
    assert "HTTP 404" in str(excinfo.value)
    assert "404 Not Found" in str(excinfo.value)


def test_list_issues_formats_summary() -> None:
    client = make_client()
    result = client.list_issues()

    assert result[0]["iid"] == 88
    assert result[0]["assignees"] == ["carol"]


def test_list_branches_sorts_by_commit_date() -> None:
    client = make_client()
    result = client.list_branches()

    assert [branch["name"] for branch in result] == ["feature/bmc-boot", "main"]
    assert result[0]["commit"]["short_id"] == "bbb222"


def test_list_branches_filters_by_author() -> None:
    client = make_client()
    result = client.list_branches(author="ogoldste")

    assert [branch["name"] for branch in result] == ["feature/bmc-boot"]

    _method, _path, params, _headers, _json = client._client.calls[-1]
    assert params["per_page"] == 100


def test_list_branches_filters_by_name_contains() -> None:
    client = make_client()
    result = client.list_branches(name_contains="feature/")

    assert [branch["name"] for branch in result] == ["feature/bmc-boot"]


def test_list_branches_or_combines_author_and_name() -> None:
    client = make_client()
    result = client.list_branches(author="nobody", name_contains="main,feature/")

    assert [branch["name"] for branch in result] == ["feature/bmc-boot", "main"]

