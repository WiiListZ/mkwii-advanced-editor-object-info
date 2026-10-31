import base64
import json
import unittest
from unittest.mock import patch

from objinfo import docformat
from objinfo.github import Client, GitHubError, Snapshot, UPSTREAM, cli_token, propose, snapshot
import subprocess

BASE = {"version": 1, "objects": {"box": {"notes": "Before"}}}
MINE = {"version": 1, "objects": {"box": {"notes": "My tested value"}}}


class GitHub(unittest.TestCase):
    def test_snapshot_reads_file_at_exact_commit(self):
        with patch.object(Client, "call", side_effect=[{"object": {"sha": "reviewed"}}, {
            "sha": "blob", "content": base64.b64encode(docformat.dumps(BASE).encode()).decode(),
        }]) as call:
            latest = snapshot()
        self.assertEqual(latest.document, BASE)
        self.assertEqual(latest.commit, "reviewed")
        self.assertIn("?ref=reviewed", call.call_args_list[1].args[1])

    def test_empty_repository_has_actionable_error(self):
        with patch.object(Client, "call", side_effect=GitHubError("empty", 409)):
            with self.assertRaisesRegex(GitHubError, "maintainer must first publish"):
                snapshot()

    def test_outdated_preview_never_writes(self):
        with patch("objinfo.github.snapshot", return_value=Snapshot(BASE, "new-head", "blob")), patch.object(Client, "call", return_value={"login": "WiiListZ"}) as call:
            with self.assertRaisesRegex(GitHubError, "changed on GitHub"):
                propose("token", docformat.dumps(MINE), "Test", expected_commit="old-head")
            self.assertEqual([item.args[0] for item in call.call_args_list], ["GET"])

    def test_maintainer_creates_branch_and_pr_without_writing_main(self):
        calls = []
        def respond(client, method, path, body=None, ok_missing=False):
            calls.append((method, path, body))
            if path == "/user":
                return {"login": "WiiListZ"}
            if path.endswith("/pulls"):
                return {"html_url": "https://github.com/example/pull/1"}
            return {}
        with patch("objinfo.github.snapshot", return_value=Snapshot(BASE, "reviewed", "blob")), patch.object(Client, "call", new=respond):
            url = propose("token", docformat.dumps(MINE), "Evidence", expected_commit="reviewed")
        self.assertTrue(url.endswith("/1"))
        branch = next(body["ref"] for method, path, body in calls if path.endswith("/git/refs"))
        self.assertNotEqual(branch, "refs/heads/main")
        update = next(body for method, path, body in calls if method == "PUT")
        self.assertEqual(update["branch"], branch.removeprefix("refs/heads/"))
        self.assertEqual(json.loads(base64.b64decode(update["content"])), MINE)
        self.assertEqual(update["sha"], "blob")
        pull = calls[-1][2]
        self.assertTrue(pull["title"].startswith("docs(objects): "))
        self.assertIn("## Objects changed", pull["body"])
        self.assertIn("## Evidence\n\nEvidence", pull["body"])
        self.assertIn("## Base revision\n\n`reviewed`", pull["body"])
        self.assertNotIn("Co-authored-by", pull["body"])

    def test_contributor_uses_actual_fork_name_without_modifying_fork_main(self):
        calls = []
        def respond(client, method, path, body=None, ok_missing=False):
            calls.append((method, path, body))
            if path == "/user":
                return {"login": "Contributor"}
            if path.endswith("/forks"):
                return {"full_name": "Contributor/renamed-fork", "owner": {"login": "Contributor"}}
            if path.endswith("/pulls"):
                return {"html_url": "https://github.com/example/pull/2"}
            return {"sha": "ready"}
        with patch("objinfo.github.snapshot", return_value=Snapshot(BASE, "reviewed", "blob")), patch.object(Client, "call", new=respond):
            propose("token", docformat.dumps(MINE), "Evidence", expected_commit="reviewed")
        update_path = next(path for method, path, body in calls if method == "PUT")
        self.assertIn("Contributor/renamed-fork/contents", update_path)
        self.assertFalse(any("merge-upstream" in path for _, path, _ in calls))
        pull = calls[-1][2]
        self.assertTrue(pull["head"].startswith("Contributor:object-info-"))

    def test_invalid_json_and_no_changes_never_write(self):
        with patch.object(Client, "call") as call:
            with self.assertRaises(ValueError):
                propose("token", '{"version":1,"objects":{}}', "Evidence")
            call.assert_not_called()
        with patch("objinfo.github.snapshot", return_value=Snapshot(BASE, "reviewed", "blob")), patch.object(Client, "call", return_value={"login": "WiiListZ"}) as call:
            with self.assertRaisesRegex(GitHubError, "no changes"):
                propose("token", docformat.dumps(BASE), "Evidence", expected_commit="reviewed")
            self.assertEqual(call.call_count, 1)

    def test_pr_failure_exposes_saved_branch_recovery_url(self):
        def respond(client, method, path, body=None, ok_missing=False):
            if path == "/user":
                return {"login": "WiiListZ"}
            if path.endswith("/pulls"):
                raise GitHubError("Permission denied", 403)
            return {}
        with patch("objinfo.github.snapshot", return_value=Snapshot(BASE, "reviewed", "blob")), patch.object(Client, "call", new=respond):
            with self.assertRaisesRegex(GitHubError, "/compare/main"):
                propose("token", docformat.dumps(MINE), "Evidence", expected_commit="reviewed")

    def test_cli_login_is_used_when_no_token_is_pasted(self):
        with patch("objinfo.github.shutil.which", return_value="gh"), patch("objinfo.github.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "secret\n", "")) as run:
            self.assertEqual(cli_token(), "secret")
            self.assertIn("capture_output", run.call_args.kwargs)
        with patch("objinfo.github.shutil.which", return_value=None):
            with self.assertRaisesRegex(GitHubError, "paste a GitHub token"):
                cli_token()

    def test_changed_cli_account_stops_before_any_write(self):
        with patch("objinfo.github.cli_token", return_value="secret"), patch.object(Client, "call", return_value={"login": "DifferentUser"}) as call:
            with self.assertRaisesRegex(GitHubError, "account changed"):
                propose("", docformat.dumps(MINE), expected_login="ExpectedUser")
            self.assertEqual([item.args[0] for item in call.call_args_list], ["GET"])
