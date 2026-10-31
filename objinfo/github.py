"""Read a consistent GitHub snapshot, then propose reviewed JSON on a separate branch."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from . import DATA_PATH, REPO_NAME, REPO_OWNER, REPO_URL
from . import docformat
from .contribution import format_proposal
from .validation import validate_document

API = "https://api.github.com"
UPSTREAM = f"/repos/{REPO_OWNER}/{REPO_NAME}"
WEB_EDIT_URL = f"{REPO_URL}/edit/main/{DATA_PATH}"


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, token: str = "", timeout: float = 30):
        self.token = token.strip()
        self.timeout = timeout

    def call(self, method: str, path: str, body: Any = None, ok_missing: bool = False) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ObjectInfoEditor", "Cache-Control": "no-cache",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            **({"Content-Type": "application/json"} if data is not None else {}),
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            if ok_missing and error.code == 404:
                return None
            try:
                message = json.loads(error.read().decode("utf-8")).get("message", "")
            except (ValueError, AttributeError):
                message = ""
            if error.code == 401:
                raise GitHubError("The token was refused (401): check that it is correct and not expired.", 401) from error
            if error.code in (403, 429):
                raise GitHubError(f"GitHub refused this request ({error.code}): {message or 'check token permissions or rate limits'}.", error.code) from error
            raise GitHubError(f"GitHub answered {error.code}: {message} ({method} {path}).", error.code) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise GitHubError(f"GitHub could not be reached: {getattr(error, 'reason', str(error))}") from error


@dataclass
class Snapshot:
    document: dict
    commit: str
    file_sha: str | None


def snapshot(client: Client | None = None) -> Snapshot:
    gh = client or Client()
    try:
        ref = gh.call("GET", f"{UPSTREAM}/git/ref/heads/main", ok_missing=True)
    except GitHubError as error:
        if error.status == 409:
            raise GitHubError("The repository is empty. The maintainer must first publish the supplied project, including data/objects.json.", 409) from error
        raise
    if not ref:
        raise GitHubError("The repository has no main branch. The maintainer must first publish the supplied project, including data/objects.json.", 404)
    commit = ref["object"]["sha"]
    record = gh.call("GET", f"{UPSTREAM}/contents/{DATA_PATH}?ref={commit}", ok_missing=True)
    if not record:
        raise GitHubError("data/objects.json is missing on GitHub. The maintainer must publish it before contributions can be proposed.", 404)
    try:
        document = docformat.loads(base64.b64decode(record["content"]).decode("utf-8-sig"))
        docformat.parse(document)
    except (ValueError, KeyError, TypeError) as error:
        raise GitHubError(f"GitHub's data/objects.json is not valid: {error}") from error
    return Snapshot(document, commit, record["sha"])


def download_latest(timeout: float = 15) -> str:
    return docformat.dumps(snapshot(Client(timeout=timeout)).document)


def cli_token() -> str:
    """Use the person's own GitHub CLI login; never bundle or save credentials."""
    command = shutil.which("gh")
    if not command:
        raise GitHubError("To create the pull request directly, paste a GitHub token below or sign in with GitHub CLI on this computer.")
    try:
        result = subprocess.run([command, "auth", "token", "--hostname", "github.com"], capture_output=True,
                                text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitHubError("Could not read the GitHub CLI login. Paste a GitHub token to continue.") from error
    if result.returncode or not result.stdout.strip():
        raise GitHubError("GitHub CLI is not signed in. Paste a GitHub token to create the pull request.")
    return result.stdout.strip()


def cli_account() -> str:
    return Client(cli_token()).call("GET", "/user")["login"]


def propose(token: str, text: str, evidence: str = "", progress: Callable[[str], None] = lambda _: None,
            expected_commit: str | None = None, reviewed: bool = False, game_tested: bool = False,
            expected_login: str | None = None) -> str:
    """Create a PR from the upstream commit that was reviewed. Never write to main."""
    document = docformat.loads(text)
    report = validate_document(document)
    if not report.valid:
        raise ValueError("\n".join(report.errors))
    gh = Client(token.strip() or cli_token())
    progress("Checking the token and the reviewed version…")
    login = gh.call("GET", "/user")["login"]
    if expected_login and login.lower() != expected_login.lower():
        raise GitHubError("The connected GitHub account changed. Close and reopen the proposal to review the account before submitting.")
    latest = snapshot(gh)
    if expected_commit is not None and latest.commit != expected_commit:
        raise GitHubError("The documentation changed on GitHub since this preview. Close this window and review the proposal again; your edits are still in the editor.")
    try:
        proposal = format_proposal(latest.document, document, evidence, latest.commit, reviewed, game_tested)
    except ValueError as error:
        raise GitHubError(str(error)) from error

    if login.lower() == REPO_OWNER.lower():
        repo, owner = UPSTREAM, login
    else:
        progress("Preparing your fork…")
        fork = gh.call("POST", f"{UPSTREAM}/forks", {"default_branch_only": True})
        repo, owner = f"/repos/{fork['full_name']}", fork["owner"]["login"]
        for _ in range(20):
            record = gh.call("GET", f"{repo}/git/commits/{latest.commit}", ok_missing=True)
            if record:
                break
            time.sleep(1)
        else:
            raise GitHubError("Your fork is not ready for the reviewed commit yet. Try again shortly.")

    branch = f"object-info-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    progress(f"Creating branch {branch}…")
    gh.call("POST", f"{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": latest.commit})
    progress("Saving the reviewed changes…")
    gh.call("PUT", f"{repo}/contents/{DATA_PATH}", {
        "message": proposal.title, "content": base64.b64encode(docformat.dumps(document).encode("utf-8")).decode("ascii"),
        "branch": branch, **({"sha": latest.file_sha} if latest.file_sha else {}),
    })
    progress("Opening the pull request…")
    head = branch if repo == UPSTREAM else f"{owner}:{branch}"
    try:
        pull = gh.call("POST", f"{UPSTREAM}/pulls", {"title": proposal.title, "head": head, "base": "main", "body": proposal.body,
                                                  "maintainer_can_modify": True})
    except GitHubError as error:
        query = urllib.parse.urlencode({"expand": "1", "title": proposal.title, "body": proposal.body})
        compare = f"{REPO_URL}/compare/main...{urllib.parse.quote(head, safe=':')}?{query}"
        raise GitHubError(f"The changes were saved on branch {branch}, but the pull request could not be opened. Finish it here: {compare}\n\n{error}") from error
    return pull["html_url"]
