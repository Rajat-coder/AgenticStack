import logging
from dataclasses import dataclass, field

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class Commit:
    sha: str
    message: str
    author: str
    date: str


@dataclass
class PullRequest:
    number: int
    title: str
    branch: str
    changed_files: list[str] = field(default_factory=list)


class GitHubClient:

    def __init__(self):
        self.owner = settings.github_repo_owner
        self.repo = settings.github_repo_name
        self.headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.base = f"{GITHUB_API}/repos/{self.owner}/{self.repo}"

    async def get_recent_commits(
        self, branch: str = "main", limit: int = 10
    ) -> list[Commit]:
        """
        Returns the last N commits on a branch.
        Context engineer uses this to understand what recently changed.
        """
        url = f"{self.base}/commits"
        params = {"sha": branch, "per_page": limit}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

        return [
            Commit(
                sha=c["sha"][:7],
                message=c["commit"]["message"].split("\n")[0],  # first line only
                author=c["commit"]["author"]["name"],
                date=c["commit"]["author"]["date"],
            )
            for c in data
        ]

    async def get_open_prs(self) -> list[PullRequest]:
        """
        Returns all open PRs with the files they touch.
        Context engineer uses this to detect file conflicts before planning.
        """
        url = f"{self.base}/pulls"
        params = {"state": "open", "per_page": 50}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            prs = response.json()

            result = []
            for pr in prs:
                # Fetch changed files for each PR
                files_url = f"{self.base}/pulls/{pr['number']}/files"
                files_response = await client.get(files_url, headers=self.headers)
                files_response.raise_for_status()
                changed_files = [f["filename"] for f in files_response.json()]

                result.append(PullRequest(
                    number=pr["number"],
                    title=pr["title"],
                    branch=pr["head"]["ref"],
                    changed_files=changed_files,
                ))

        return result

    async def branch_exists(self, branch_name: str) -> bool:
        """
        Check if a branch already exists in the remote repo.
        Harness calls this before creating the feature branch.
        """
        url = f"{self.base}/branches/{branch_name}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return True

    async def create_branch(
        self, branch_name: str, from_branch: str = "main"
    ) -> None:
        """
        Create a new branch from the tip of from_branch.

        Git doesn't let you "name" a branch directly.
        You create a ref (a named pointer) that points to a commit SHA.

        Step 1: get the latest commit SHA on from_branch
        Step 2: create a new ref pointing to that SHA
        """
        async with httpx.AsyncClient(timeout=30) as client:

            # Step 1 — get the SHA of the latest commit on the base branch
            ref_url = f"{self.base}/git/ref/heads/{from_branch}"
            ref_response = await client.get(ref_url, headers=self.headers)
            ref_response.raise_for_status()
            sha = ref_response.json()["object"]["sha"]

            # Step 2 — create a new ref pointing to that SHA
            create_url = f"{self.base}/git/refs"
            await client.post(
                create_url,
                headers=self.headers,
                json={
                    "ref": f"refs/heads/{branch_name}",
                    "sha": sha,
                },
            )

        logger.info("Created branch %s from %s (%s)", branch_name, from_branch, sha[:7])

    async def create_pr(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> str:
        """
        Open a GitHub Pull Request.
        Returns the URL of the created PR.
        """
        url = f"{self.base}/pulls"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=self.headers,
                json={
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                },
            )
            if response.status_code == 422:
                error_body = response.json()
                errors = error_body.get("errors", [])
                for err in errors:
                    if "already exists" in str(err.get("message", "")).lower():
                        # PR exists — find and return its URL
                        prs_response = await self._client.get(
                            f"https://api.github.com/repos/{settings.github_repo_owner}/{settings.github_repo_name}/pulls",
                            params={"head": f"{settings.github_repo_owner}:{head_branch}", "state": "open"},
                        )
                        prs = prs_response.json()
                        if prs:
                            logger.info("PR already exists: %s", prs[0]["html_url"])
                            return prs[0]["html_url"]
            response.raise_for_status()
            pr_url = response.json()["html_url"]

        logger.info("PR created: %s", pr_url)
        return pr_url


# Single shared instance
github = GitHubClient()