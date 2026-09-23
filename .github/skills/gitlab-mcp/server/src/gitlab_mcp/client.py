from __future__ import annotations

from dataclasses import dataclass
import os
import ssl
from typing import Any
from urllib.parse import quote

import httpx
import truststore

TRUTHY = {"1", "true", "yes", "on"}

WRITE_DISABLED_MESSAGE = (
    "GitLab write operations are disabled. Set GITLAB_ALLOW_WRITE=1 in the MCP server "
    "environment and restart or reload the client to enable them. The GITLAB_TOKEN must "
    "also carry the 'api' scope; 'read_api' cannot post comments."
)


class GitLabApiError(RuntimeError):
    """A GitLab REST call returned a non-2xx status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code

    @staticmethod
    def _payload_message(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            return str(getattr(response, "text", "") or "").strip()[:500]
        if isinstance(payload, dict):
            for key in ("message", "error", "error_description"):
                value = payload.get(key)
                if value:
                    return str(value)[:500]
        return str(payload)[:500]

    @classmethod
    def from_response(cls, method: str, path: str, response: Any) -> "GitLabApiError":
        status = int(getattr(response, "status_code", 0) or 0)
        detail = cls._payload_message(response) or "no response body"
        hint = ""
        if status in (401, 403):
            hint = (
                " The token was rejected for this operation; posting comments requires a "
                "token with the 'api' scope and Developer access or above on the project."
            )
        elif status == 404:
            hint = (
                " The project, merge request, or endpoint does not exist, or the token "
                "cannot see it. Some endpoints are GitLab Premium only."
            )
        return cls(status, f"GitLab API {method} {path} failed with HTTP {status}: {detail}.{hint}")


class GitLabWriteDisabledError(RuntimeError):
    """A write tool was called while GITLAB_ALLOW_WRITE was not enabled."""


@dataclass(slots=True)
class GitLabConfig:
    base_url: str
    token: str
    default_project: str = ""
    timeout_seconds: float = 30.0
    allow_write: bool = False

    @classmethod
    def from_env(cls) -> "GitLabConfig":
        base_url = os.environ.get("GITLAB_BASE_URL", "").strip().rstrip("/")
        token = os.environ.get("GITLAB_TOKEN", "").strip()
        default_project = os.environ.get("GITLAB_DEFAULT_PROJECT", "").strip()
        allow_write = os.environ.get("GITLAB_ALLOW_WRITE", "").strip().lower() in TRUTHY
        if not base_url:
            raise ValueError("GITLAB_BASE_URL is required")
        if not token:
            raise ValueError("GITLAB_TOKEN is required")
        if not base_url.endswith("/api/v4"):
            base_url = f"{base_url}/api/v4"
        return cls(
            base_url=base_url,
            token=token,
            default_project=default_project,
            allow_write=allow_write,
        )


class GitLabClient:
    def __init__(self, config: GitLabConfig) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            headers={
                "PRIVATE-TOKEN": config.token,
                "Accept": "application/json",
                "User-Agent": "gitlab-review-mcp/0.1.0",
            },
            timeout=config.timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def _resolve_project_value(self, project: str = "") -> str:
        value = (project or self.config.default_project).strip()
        if not value:
            raise ValueError("project is required unless GITLAB_DEFAULT_PROJECT is set")
        return value

    @staticmethod
    def _encode_project(project: str) -> str:
        if project.isdigit():
            return project
        return quote(project, safe="")

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in params.items():
            if value in ("", None, [], ()):
                continue
            if isinstance(value, list):
                cleaned[key] = ",".join(str(item) for item in value)
            else:
                cleaned[key] = value
        return cleaned

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> Any:
        headers = {"Accept": accept}
        try:
            response = self._client.request(
                method,
                path,
                params=self._clean_params(params or {}),
                json=json_body,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitLabApiError.from_response(method, path, exc.response) from exc
        if accept == "application/json":
            return response.json()
        return response.text

    def _request_optional(self, method: str, path: str, **kwargs: Any) -> Any | None:
        """Like `_request`, but returns None when the endpoint is unavailable.

        Used for tier-gated endpoints such as merge request approvals, which 404 on
        GitLab CE and 403 for tokens without the required scope.
        """
        try:
            return self._request(method, path, **kwargs)
        except GitLabApiError as exc:
            if exc.status_code in (401, 403, 404):
                return None
            raise

    def _require_write(self) -> None:
        if not self.config.allow_write:
            raise GitLabWriteDisabledError(WRITE_DISABLED_MESSAGE)

    @staticmethod
    def _require_body(body: str) -> str:
        text = (body or "").strip()
        if not text:
            raise ValueError("body must be a non-empty comment string")
        return text

    def health(self) -> dict[str, Any]:
        user = self._request("GET", "/user")
        return {
            "status": "ok",
            "base_url": self.config.base_url,
            "user": {
                "username": user.get("username"),
                "name": user.get("name"),
                "id": user.get("id"),
            },
            "default_project": self.config.default_project,
            "write_enabled": self.config.allow_write,
        }

    def resolve_project(self, project: str = "") -> dict[str, Any]:
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request("GET", f"/projects/{encoded}")
        return {
            "id": payload.get("id"),
            "path_with_namespace": payload.get("path_with_namespace"),
            "name": payload.get("name"),
            "web_url": payload.get("web_url"),
            "default_branch": payload.get("default_branch"),
            "visibility": payload.get("visibility"),
        }

    @staticmethod
    def _branch_matches_author(commit: dict[str, Any], aliases: list[str]) -> bool:
        name = str(commit.get("author_name") or "").lower()
        email = str(commit.get("author_email") or "").lower()
        return any(alias in name or alias in email for alias in aliases)

    @staticmethod
    def _format_branch(item: dict[str, Any]) -> dict[str, Any]:
        commit = item.get("commit") or {}
        return {
            "name": item.get("name"),
            "default": item.get("default"),
            "merged": item.get("merged"),
            "protected": item.get("protected"),
            "web_url": item.get("web_url"),
            "commit": {
                "short_id": commit.get("short_id"),
                "title": commit.get("title"),
                "author_name": commit.get("author_name"),
                "author_email": commit.get("author_email"),
                "committed_date": commit.get("committed_date"),
            },
        }

    def list_branches(
        self,
        project: str = "",
        *,
        search: str = "",
        author: str = "",
        name_contains: str = "",
        page: int = 1,
        per_page: int = 20,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """List branches.

        `author` and `name_contains` accept comma-separated aliases and are matched
        case-insensitively. `author` only sees the tip commit, which is unreliable
        for ownership when someone else pushed the last merge, so combine it with
        `name_contains` for branch-naming conventions such as `oren/...`.
        """
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        author_aliases = [alias.strip().lower() for alias in author.split(",") if alias.strip()]
        name_aliases = [alias.strip().lower() for alias in name_contains.split(",") if alias.strip()]
        filtering = bool(author_aliases or name_aliases)

        raw: list[dict[str, Any]] = []
        if filtering:
            # Filters are client-side, so every page must be scanned.
            for current_page in range(1, max_pages + 1):
                chunk = self._request(
                    "GET",
                    f"/projects/{encoded}/repository/branches",
                    params={"search": search, "page": current_page, "per_page": 100},
                )
                raw.extend(chunk)
                if len(chunk) < 100:
                    break
        else:
            raw = self._request(
                "GET",
                f"/projects/{encoded}/repository/branches",
                params={"search": search, "page": page, "per_page": per_page},
            )

        branches = []
        for item in raw:
            if filtering:
                name = str(item.get("name") or "").lower()
                matched_author = self._branch_matches_author(item.get("commit") or {}, author_aliases)
                matched_name = any(alias in name for alias in name_aliases)
                if not (matched_author or matched_name):
                    continue
            branches.append(self._format_branch(item))
        branches.sort(key=lambda branch: branch["commit"].get("committed_date") or "", reverse=True)
        if filtering:
            branches = branches[:per_page]
        return branches

    @staticmethod
    def _format_user(user: dict[str, Any] | None) -> dict[str, Any]:
        user = user or {}
        return {"username": user.get("username"), "name": user.get("name")}

    @classmethod
    def _format_users(cls, users: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [cls._format_user(user) for user in users or []]

    @staticmethod
    def _format_pipeline(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        return {
            "id": item.get("id"),
            "iid": item.get("iid"),
            "status": item.get("status"),
            "source": item.get("source"),
            "ref": item.get("ref"),
            "sha": item.get("sha"),
            "web_url": item.get("web_url"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }

    @staticmethod
    def _format_job(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "stage": item.get("stage"),
            "status": item.get("status"),
            "allow_failure": item.get("allow_failure"),
            "failure_reason": item.get("failure_reason"),
            "duration": item.get("duration"),
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
            "web_url": item.get("web_url"),
        }

    @classmethod
    def _format_note(cls, note: dict[str, Any]) -> dict[str, Any]:
        formatted = {
            "id": note.get("id"),
            "author": (note.get("author") or {}).get("username"),
            "body": note.get("body"),
            "created_at": note.get("created_at"),
            "updated_at": note.get("updated_at"),
            "system": bool(note.get("system")),
            "resolvable": note.get("resolvable"),
            "resolved": note.get("resolved"),
        }
        position = note.get("position") or {}
        if position:
            formatted["position"] = {
                "new_path": position.get("new_path"),
                "new_line": position.get("new_line"),
                "old_path": position.get("old_path"),
                "old_line": position.get("old_line"),
            }
        return formatted

    @classmethod
    def _format_discussion(cls, discussion: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
        formatted_notes = [cls._format_note(note) for note in notes]
        resolvable_notes = [note for note in formatted_notes if note.get("resolvable")]
        resolved: bool | None = None
        if resolvable_notes:
            resolved = all(bool(note.get("resolved")) for note in resolvable_notes)
        file_path = None
        for note in formatted_notes:
            position = note.get("position") or {}
            if position.get("new_path") or position.get("old_path"):
                file_path = position.get("new_path") or position.get("old_path")
                break
        return {
            "id": discussion.get("id"),
            "individual_note": discussion.get("individual_note"),
            "resolvable": bool(resolvable_notes),
            "resolved": resolved,
            "file": file_path,
            "notes": formatted_notes,
        }

    def list_merge_requests(
        self,
        project: str = "",
        *,
        state: str = "opened",
        search: str = "",
        author_username: str = "",
        reviewer_username: str = "",
        assignee_username: str = "",
        labels: list[str] | None = None,
        target_branch: str = "",
        source_branch: str = "",
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "GET",
            f"/projects/{encoded}/merge_requests",
            params={
                "state": state,
                "search": search,
                "author_username": author_username,
                "reviewer_username": reviewer_username,
                "assignee_username": assignee_username,
                "labels": labels or [],
                "target_branch": target_branch,
                "source_branch": source_branch,
                "page": page,
                "per_page": per_page,
                "order_by": "updated_at",
                "sort": "desc",
            },
        )
        return [
            {
                "iid": item.get("iid"),
                "title": item.get("title"),
                "state": item.get("state"),
                "author": (item.get("author") or {}).get("username"),
                "reviewers": [
                    user["username"] for user in self._format_users(item.get("reviewers")) if user["username"]
                ],
                "assignees": [
                    user["username"] for user in self._format_users(item.get("assignees")) if user["username"]
                ],
                "draft": item.get("draft"),
                "web_url": item.get("web_url"),
                "source_branch": item.get("source_branch"),
                "target_branch": item.get("target_branch"),
                "updated_at": item.get("updated_at"),
                "merge_status": item.get("merge_status"),
                "detailed_merge_status": item.get("detailed_merge_status"),
                "has_conflicts": item.get("has_conflicts"),
                "sha": item.get("sha"),
            }
            for item in payload
        ]

    def get_merge_request(
        self,
        project: str,
        iid: int,
        *,
        include_notes: bool = False,
        include_approvals: bool = False,
    ) -> dict[str, Any]:
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request("GET", f"/projects/{encoded}/merge_requests/{iid}")
        result = {
            "iid": payload.get("iid"),
            "title": payload.get("title"),
            "description": payload.get("description"),
            "state": payload.get("state"),
            "draft": payload.get("draft"),
            "author": self._format_user(payload.get("author")),
            "assignees": self._format_users(payload.get("assignees")),
            "reviewers": self._format_users(payload.get("reviewers")),
            "labels": payload.get("labels"),
            "source_branch": payload.get("source_branch"),
            "target_branch": payload.get("target_branch"),
            "web_url": payload.get("web_url"),
            "merge_status": payload.get("merge_status"),
            "detailed_merge_status": payload.get("detailed_merge_status"),
            "has_conflicts": payload.get("has_conflicts"),
            "blocking_discussions_resolved": payload.get("blocking_discussions_resolved"),
            "user_notes_count": payload.get("user_notes_count"),
            "changes_count": payload.get("changes_count"),
            "head_pipeline": self._format_pipeline(payload.get("head_pipeline") or payload.get("pipeline")),
            "diff_refs": payload.get("diff_refs"),
            "sha": payload.get("sha"),
            "updated_at": payload.get("updated_at"),
        }
        if include_notes:
            result["notes"] = self._request("GET", f"/projects/{encoded}/merge_requests/{iid}/notes")
        if include_approvals:
            result["approvals"] = self.get_merge_request_approvals(project_value, iid)
        return result

    def get_merge_request_approvals(self, project: str, iid: int) -> dict[str, Any]:
        """Approval state for a merge request.

        The approvals endpoint is a GitLab Premium feature, so this degrades to
        `{"supported": False}` instead of raising on CE instances.
        """
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request_optional("GET", f"/projects/{encoded}/merge_requests/{iid}/approvals")
        if payload is None:
            return {
                "supported": False,
                "reason": (
                    "The merge request approvals endpoint is unavailable on this instance "
                    "(GitLab Premium feature) or the token cannot read it."
                ),
            }
        return {
            "supported": True,
            "approved": payload.get("approved"),
            "approvals_required": payload.get("approvals_required"),
            "approvals_left": payload.get("approvals_left"),
            "approved_by": [
                self._format_user(entry.get("user"))["username"] for entry in payload.get("approved_by") or []
            ],
            "user_has_approved": payload.get("user_has_approved"),
            "user_can_approve": payload.get("user_can_approve"),
        }

    def get_merge_request_pipelines(self, project: str, iid: int, *, per_page: int = 20) -> list[dict[str, Any]]:
        """Pipelines that ran for a merge request, newest first."""
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "GET",
            f"/projects/{encoded}/merge_requests/{iid}/pipelines",
            params={"per_page": per_page},
        )
        pipelines = [self._format_pipeline(item) for item in payload]
        return [pipeline for pipeline in pipelines if pipeline]

    def get_pipeline_jobs(
        self,
        project: str,
        pipeline_id: int,
        *,
        scope: str = "",
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Jobs for a pipeline. `scope` filters by job status, e.g. "failed"."""
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "GET",
            f"/projects/{encoded}/pipelines/{pipeline_id}/jobs",
            params={"scope[]": scope, "per_page": per_page},
        )
        return [self._format_job(item) for item in payload]

    def list_merge_request_discussions(
        self,
        project: str,
        iid: int,
        *,
        include_system: bool = False,
        resolved: bool | None = None,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Threaded merge request discussions across every page.

        System notes ("added 1 commit", "assigned to @user") are dropped unless
        `include_system` is set, because they bury the human review comments.
        `resolved=False` returns only threads still needing attention.
        """
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)

        raw: list[dict[str, Any]] = []
        for current_page in range(1, max_pages + 1):
            chunk = self._request(
                "GET",
                f"/projects/{encoded}/merge_requests/{iid}/discussions",
                params={"page": current_page, "per_page": 100},
            )
            raw.extend(chunk)
            if len(chunk) < 100:
                break

        discussions: list[dict[str, Any]] = []
        for item in raw:
            notes = item.get("notes") or []
            if not include_system:
                notes = [note for note in notes if not note.get("system")]
            if not notes:
                continue
            formatted = self._format_discussion(item, notes)
            if resolved is not None and bool(formatted["resolved"]) is not resolved:
                continue
            discussions.append(formatted)
        return discussions

    def list_merge_request_changes(
        self,
        project: str,
        iid: int,
        *,
        path_filter: str = "",
        include_diff: bool = True,
        access_raw_diffs: bool = True,
    ) -> dict[str, Any]:
        """Per-file changes plus the `diff_refs` needed to post inline comments.

        GitLab collapses per-file diffs on large merge requests and returns them as
        empty strings, which would silently hide changes from a reviewer.
        `access_raw_diffs` (on by default) makes GitLab read the diffs from Gitaly
        so they come back complete; any file whose diff is still empty is flagged
        with `diff_collapsed`.
        """
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "GET",
            f"/projects/{encoded}/merge_requests/{iid}/changes",
            params={"access_raw_diffs": "true" if access_raw_diffs else ""},
        )
        needle = path_filter.strip().lower()

        files: list[dict[str, Any]] = []
        collapsed = 0
        for item in payload.get("changes") or []:
            new_path = item.get("new_path") or ""
            old_path = item.get("old_path") or ""
            if needle and needle not in new_path.lower() and needle not in old_path.lower():
                continue
            entry = {
                "new_path": new_path,
                "old_path": old_path,
                "new_file": item.get("new_file"),
                "renamed_file": item.get("renamed_file"),
                "deleted_file": item.get("deleted_file"),
            }
            if include_diff:
                diff = item.get("diff") or ""
                entry["diff"] = diff
                if not diff:
                    entry["diff_collapsed"] = True
                    collapsed += 1
            files.append(entry)

        result = {
            "project": project_value,
            "iid": payload.get("iid", iid),
            "title": payload.get("title"),
            "state": payload.get("state"),
            "web_url": payload.get("web_url"),
            "sha": payload.get("sha"),
            "diff_refs": payload.get("diff_refs"),
            "changes_count": payload.get("changes_count"),
            "files_returned": len(files),
            "files": files,
        }
        if collapsed:
            result["warning"] = (
                f"{collapsed} file diff(s) came back empty and are marked diff_collapsed. "
                "Use get_merge_request_raw_diff for the complete diff of those files."
            )
        return result

    def create_merge_request_note(self, project: str, iid: int, body: str) -> dict[str, Any]:
        """Post a merge request level comment."""
        self._require_write()
        text = self._require_body(body)
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "POST",
            f"/projects/{encoded}/merge_requests/{iid}/notes",
            json_body={"body": text},
        )
        return self._format_note(payload)

    def create_merge_request_diff_comment(
        self,
        project: str,
        iid: int,
        body: str,
        *,
        new_path: str = "",
        new_line: int | None = None,
        old_path: str = "",
        old_line: int | None = None,
        base_sha: str = "",
        head_sha: str = "",
        start_sha: str = "",
    ) -> dict[str, Any]:
        """Start a discussion anchored to a line of the merge request diff.

        The three SHAs are fetched from the merge request `diff_refs` when omitted; a
        stale or missing SHA is the usual reason GitLab rejects an inline comment.
        """
        self._require_write()
        text = self._require_body(body)
        if not new_path and not old_path:
            raise ValueError("new_path or old_path is required to anchor a diff comment")
        if new_line is None and old_line is None:
            raise ValueError("new_line or old_line is required to anchor a diff comment")

        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)

        if not (base_sha and head_sha and start_sha):
            refs = (self._request("GET", f"/projects/{encoded}/merge_requests/{iid}") or {}).get("diff_refs") or {}
            base_sha = base_sha or refs.get("base_sha") or ""
            head_sha = head_sha or refs.get("head_sha") or ""
            start_sha = start_sha or refs.get("start_sha") or ""
        if not (base_sha and head_sha and start_sha):
            raise ValueError(
                "could not resolve diff_refs for this merge request; pass base_sha, "
                "head_sha and start_sha explicitly"
            )

        position: dict[str, Any] = {
            "position_type": "text",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "start_sha": start_sha,
            "new_path": new_path or old_path,
            "old_path": old_path or new_path,
        }
        if new_line is not None:
            position["new_line"] = new_line
        if old_line is not None:
            position["old_line"] = old_line

        payload = self._request(
            "POST",
            f"/projects/{encoded}/merge_requests/{iid}/discussions",
            json_body={"body": text, "position": position},
        )
        return self._format_discussion(payload, payload.get("notes") or [])

    def reply_to_merge_request_discussion(
        self,
        project: str,
        iid: int,
        discussion_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Reply inside an existing merge request discussion thread."""
        self._require_write()
        text = self._require_body(body)
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "POST",
            f"/projects/{encoded}/merge_requests/{iid}/discussions/{discussion_id}/notes",
            json_body={"body": text},
        )
        return self._format_note(payload)

    def resolve_merge_request_discussion(
        self,
        project: str,
        iid: int,
        discussion_id: str,
        *,
        resolved: bool = True,
    ) -> dict[str, Any]:
        """Resolve or unresolve a merge request discussion thread."""
        self._require_write()
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "PUT",
            f"/projects/{encoded}/merge_requests/{iid}/discussions/{discussion_id}",
            json_body={"resolved": resolved},
        )
        return self._format_discussion(payload, payload.get("notes") or [])

    def get_merge_request_raw_diff(self, project: str, iid: int) -> dict[str, Any]:
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        diff_text = self._request(
            "GET",
            f"/projects/{encoded}/merge_requests/{iid}/raw_diffs",
            accept="text/plain",
        )
        return {
            "project": project_value,
            "iid": iid,
            "content_type": "text/x-diff",
            "diff": diff_text,
        }

    def list_issues(
        self,
        project: str = "",
        *,
        state: str = "opened",
        search: str = "",
        author_username: str = "",
        assignee_username: str = "",
        labels: list[str] | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request(
            "GET",
            f"/projects/{encoded}/issues",
            params={
                "state": state,
                "search": search,
                "author_username": author_username,
                "assignee_username": assignee_username,
                "labels": labels or [],
                "page": page,
                "per_page": per_page,
                "order_by": "updated_at",
                "sort": "desc",
            },
        )
        return [
            {
                "iid": item.get("iid"),
                "title": item.get("title"),
                "state": item.get("state"),
                "author": (item.get("author") or {}).get("username"),
                "assignees": [(assignee or {}).get("username") for assignee in item.get("assignees") or []],
                "labels": item.get("labels"),
                "web_url": item.get("web_url"),
                "updated_at": item.get("updated_at"),
            }
            for item in payload
        ]

    def get_issue(self, project: str, iid: int, *, include_notes: bool = False) -> dict[str, Any]:
        project_value = self._resolve_project_value(project)
        encoded = self._encode_project(project_value)
        payload = self._request("GET", f"/projects/{encoded}/issues/{iid}")
        result = {
            "iid": payload.get("iid"),
            "title": payload.get("title"),
            "description": payload.get("description"),
            "state": payload.get("state"),
            "author": payload.get("author"),
            "assignees": payload.get("assignees"),
            "labels": payload.get("labels"),
            "web_url": payload.get("web_url"),
            "updated_at": payload.get("updated_at"),
        }
        if include_notes:
            result["notes"] = self._request("GET", f"/projects/{encoded}/issues/{iid}/notes")
        return result
