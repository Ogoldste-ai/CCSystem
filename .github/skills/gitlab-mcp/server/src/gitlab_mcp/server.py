from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import GitLabClient, GitLabConfig


def build_server() -> FastMCP:
    client = GitLabClient(GitLabConfig.from_env())
    server = FastMCP("gitlab-review")

    @server.tool()
    def health() -> dict[str, Any]:
        """Verify GitLab auth and report whether write tools are enabled."""
        return client.health()

    @server.tool()
    def resolve_project(project: str = "") -> dict[str, Any]:
        return client.resolve_project(project)

    @server.tool()
    def list_branches(
        project: str = "",
        search: str = "",
        author: str = "",
        name_contains: str = "",
        page: int = 1,
        per_page: int = 20,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """List repository branches, newest commit first.

        `search` is a server-side branch-name filter. `author` matches the tip
        commit author name/email and `name_contains` matches the branch name;
        both accept comma-separated aliases and are OR-ed together. Because tip
        commit authorship is unreliable when someone else pushed the last merge,
        pass both, e.g. author="ogoldste", name_contains="oren/".
        """
        return client.list_branches(
            project=project,
            search=search,
            author=author,
            name_contains=name_contains,
            page=page,
            per_page=per_page,
            max_pages=max_pages,
        )

    @server.tool()
    def list_merge_requests(
        project: str = "",
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
        return client.list_merge_requests(
            project=project,
            state=state,
            search=search,
            author_username=author_username,
            reviewer_username=reviewer_username,
            assignee_username=assignee_username,
            labels=labels,
            target_branch=target_branch,
            source_branch=source_branch,
            page=page,
            per_page=per_page,
        )

    @server.tool()
    def get_merge_request(
        project: str,
        iid: int,
        include_notes: bool = False,
        include_approvals: bool = False,
    ) -> dict[str, Any]:
        """Full detail for one merge request.

        Answers "what is the status of my merge request": reviewers and assignees,
        head pipeline status, merge/conflict status, and diff_refs. Prefer
        list_merge_request_discussions over include_notes for reading comments.
        """
        return client.get_merge_request(
            project=project,
            iid=iid,
            include_notes=include_notes,
            include_approvals=include_approvals,
        )

    @server.tool()
    def get_merge_request_approvals(project: str, iid: int) -> dict[str, Any]:
        """Who approved a merge request and how many approvals are still required.

        Returns {"supported": false} on instances where the approvals API is not
        available rather than failing.
        """
        return client.get_merge_request_approvals(project=project, iid=iid)

    @server.tool()
    def get_merge_request_pipelines(project: str, iid: int, per_page: int = 20) -> list[dict[str, Any]]:
        """Pipeline status for a merge request, newest pipeline first."""
        return client.get_merge_request_pipelines(project=project, iid=iid, per_page=per_page)

    @server.tool()
    def get_pipeline_jobs(
        project: str,
        pipeline_id: int,
        scope: str = "",
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Jobs of a pipeline, to see which stage or job failed.

        Pass scope="failed" to list only failing jobs. Use the pipeline id from
        get_merge_request_pipelines or the head_pipeline of get_merge_request.
        """
        return client.get_pipeline_jobs(
            project=project,
            pipeline_id=pipeline_id,
            scope=scope,
            per_page=per_page,
        )

    @server.tool()
    def list_merge_request_discussions(
        project: str,
        iid: int,
        include_system: bool = False,
        resolved: bool | None = None,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Read the comments on a merge request as threaded discussions.

        Fetches every page, keeps thread structure, reports resolved state and the
        file/line each inline comment is anchored to. System notes such as "added 1
        commit" are excluded unless include_system is true. Pass resolved=false to
        see only threads that still need attention.
        """
        return client.list_merge_request_discussions(
            project=project,
            iid=iid,
            include_system=include_system,
            resolved=resolved,
            max_pages=max_pages,
        )

    @server.tool()
    def list_merge_request_changes(
        project: str,
        iid: int,
        path_filter: str = "",
        include_diff: bool = True,
        access_raw_diffs: bool = True,
    ) -> dict[str, Any]:
        """Review the changes of a merge request file by file.

        Returns diff_refs, which are required to post inline comments, plus one entry
        per changed file. Use include_diff=false for a cheap file listing, and
        path_filter to narrow to a path substring. access_raw_diffs keeps GitLab from
        collapsing per-file diffs on large merge requests; any diff that still comes
        back empty is flagged with diff_collapsed.
        """
        return client.list_merge_request_changes(
            project=project,
            iid=iid,
            path_filter=path_filter,
            include_diff=include_diff,
            access_raw_diffs=access_raw_diffs,
        )

    @server.tool()
    def get_merge_request_raw_diff(project: str, iid: int) -> dict[str, Any]:
        """The whole merge request diff as one unified diff text."""
        return client.get_merge_request_raw_diff(project=project, iid=iid)

    @server.tool()
    def create_merge_request_note(project: str, iid: int, body: str) -> dict[str, Any]:
        """Post a merge request level comment. Requires GITLAB_ALLOW_WRITE=1."""
        return client.create_merge_request_note(project=project, iid=iid, body=body)

    @server.tool()
    def create_merge_request_diff_comment(
        project: str,
        iid: int,
        body: str,
        new_path: str = "",
        new_line: int | None = None,
        old_path: str = "",
        old_line: int | None = None,
        base_sha: str = "",
        head_sha: str = "",
        start_sha: str = "",
    ) -> dict[str, Any]:
        """Comment on a specific line of the merge request diff. Requires GITLAB_ALLOW_WRITE=1.

        Use new_path/new_line for added or changed lines and old_path/old_line for
        removed lines, taking both from list_merge_request_changes. The SHAs are read
        from the merge request automatically when omitted.
        """
        return client.create_merge_request_diff_comment(
            project=project,
            iid=iid,
            body=body,
            new_path=new_path,
            new_line=new_line,
            old_path=old_path,
            old_line=old_line,
            base_sha=base_sha,
            head_sha=head_sha,
            start_sha=start_sha,
        )

    @server.tool()
    def reply_to_merge_request_discussion(
        project: str,
        iid: int,
        discussion_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Reply in an existing discussion thread. Requires GITLAB_ALLOW_WRITE=1.

        Take discussion_id from list_merge_request_discussions.
        """
        return client.reply_to_merge_request_discussion(
            project=project,
            iid=iid,
            discussion_id=discussion_id,
            body=body,
        )

    @server.tool()
    def resolve_merge_request_discussion(
        project: str,
        iid: int,
        discussion_id: str,
        resolved: bool = True,
    ) -> dict[str, Any]:
        """Resolve or unresolve a discussion thread. Requires GITLAB_ALLOW_WRITE=1."""
        return client.resolve_merge_request_discussion(
            project=project,
            iid=iid,
            discussion_id=discussion_id,
            resolved=resolved,
        )

    @server.tool()
    def list_issues(
        project: str = "",
        state: str = "opened",
        search: str = "",
        author_username: str = "",
        assignee_username: str = "",
        labels: list[str] | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        return client.list_issues(
            project=project,
            state=state,
            search=search,
            author_username=author_username,
            assignee_username=assignee_username,
            labels=labels,
            page=page,
            per_page=per_page,
        )

    @server.tool()
    def get_issue(project: str, iid: int, include_notes: bool = False) -> dict[str, Any]:
        return client.get_issue(project=project, iid=iid, include_notes=include_notes)

    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitLab review MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport mode",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transports")
    parser.add_argument("--port", type=int, default=8766, help="Port for HTTP transports")
    parser.add_argument("--path", default="/mcp", help="Path for streamable HTTP transport")
    parser.add_argument("--sse-path", default="/sse", help="Path for SSE transport")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = build_server()

    if args.transport == "stdio":
        server.run()
        return

    server.settings.host = args.host
    server.settings.port = args.port
    server.settings.streamable_http_path = args.path
    server.settings.sse_path = args.sse_path
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
