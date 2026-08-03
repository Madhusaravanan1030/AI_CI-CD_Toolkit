"""
Minimal GitHub REST API client for posting a PR review with inline
comments. Uses only `requests` + a token, no extra SDK dependency.
"""

import os

import requests

GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ["GITHUB_TOKEN"]
        self.repo = repo or os.environ["GITHUB_REPOSITORY"]  # "owner/name"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get_pr_head_sha(self, pr_number: int) -> str:
        resp = self.session.get(f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}")
        resp.raise_for_status()
        return resp.json()["head"]["sha"]

    def post_review(self, pr_number: int, findings: list, event: str = "COMMENT") -> dict:
        """
        Posts a single PR review containing all findings as inline comments.
        Batching into one review (vs. one call per comment) avoids spamming
        the PR timeline with individual notifications.
        """
        if not findings:
            return self._post_no_issues_review(pr_number)

        commit_sha = self.get_pr_head_sha(pr_number)
        comments = [
            {
                "path": f.file,
                "line": f.line,
                "side": "RIGHT",
                "body": f"**[{f.severity.upper()}]** {f.message}",
            }
            for f in findings
        ]

        body = f"AI review found {len(findings)} item(s) worth a look."
        payload = {
            "commit_id": commit_sha,
            "body": body,
            "event": event,
            "comments": comments,
        }
        resp = self.session.post(
            f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def _post_no_issues_review(self, pr_number: int) -> dict:
        commit_sha = self.get_pr_head_sha(pr_number)
        payload = {
            "commit_id": commit_sha,
            "body": "AI review: no notable issues found in the added lines.",
            "event": "COMMENT",
        }
        resp = self.session.post(
            f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
