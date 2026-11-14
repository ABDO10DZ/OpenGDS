import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path

from git_service import GitService, discover_git_executable


class GitDiscoveryTests(unittest.TestCase):
    def test_explicit_executable_override_is_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "git.exe"
            executable.write_text("placeholder", encoding="utf-8")
            found = discover_git_executable({"OPENGDS_GIT_EXECUTABLE": str(executable), "PATH": ""})
            self.assertEqual(found, str(executable.resolve()))

    def test_windows_program_files_install_is_found_when_path_is_missing(self):
        from unittest.mock import patch
        expected = Path("C:/Program Files/Git/cmd/git.exe")
        def is_file(path):
            # Windows Path renders backslashes; normalize both operands so the
            # fixture behaves identically on Windows and POSIX test hosts.
            actual = str(path).replace("\\", "/").casefold()
            target = str(expected).replace("\\", "/").casefold()
            return actual == target
        with patch("git_service.shutil.which", return_value=None), \
             patch.object(Path, "is_file", is_file):
            found = discover_git_executable({"PATH": "", "ProgramFiles": "C:/Program Files"})
        self.assertEqual(found, str(expected.resolve()))

    def test_returns_none_when_git_is_not_installed(self):
        from unittest.mock import patch
        with patch("git_service.shutil.which", return_value=None), \
             patch.object(Path, "is_file", return_value=False):
            self.assertIsNone(discover_git_executable({"PATH": ""}))


def _git_cli_is_usable() -> bool:
    """Only run repository integration tests when the discovered Git can execute."""
    executable = discover_git_executable()
    if not executable:
        return False
    try:
        result = subprocess.run(
            [executable, "--version"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            timeout=3, check=False, shell=False,
        )
        return result.returncode == 0 and "git version" in result.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(_git_cli_is_usable(), "Git integration tests require a working Git CLI")
class GitServiceTests(unittest.TestCase):
    def test_history_graph_and_commit_inline_diff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            service.run("config", "user.name", "OpenGDS Test")
            service.run("config", "user.email", "test@example.invalid")
            target = root / "main.gd"
            target.write_text("extends Node\nfunc _ready():\n    pass\n", encoding="utf-8")
            service.stage(["main.gd"])
            service.commit("Add main script")
            graph = service.history_graph()
            self.assertTrue(graph)
            commit = graph[0]["hash"]
            self.assertIn("Add main script", graph[0]["subject"])
            self.assertIn("main.gd", service.commit_files(commit))
            patch = service.commit_diff(commit, "main.gd")
            self.assertIn("+extends Node", patch)
            self.assertIn("_ready", service.commit_diff(commit, "main.gd"))

    def test_diff_combines_staged_and_unstaged_hunks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            service.run("config", "user.name", "OpenGDS Test")
            service.run("config", "user.email", "test@example.invalid")
            target = root / "main.gd"
            target.write_text("extends Node\nvar first = 1\nvar second = 2\n", encoding="utf-8")
            service.stage(["main.gd"])
            service.commit("Initial script")
            target.write_text("extends Node\nvar first = 10\nvar second = 2\n", encoding="utf-8")
            service.stage(["main.gd"])
            target.write_text("extends Node\nvar first = 10\nvar second = 20\n", encoding="utf-8")
            diff = service.diff("main.gd")
            self.assertIn("var first = 10", diff)
            self.assertIn("var second = 20", diff)

    def test_init_stage_commit_and_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            service.run("config", "user.name", "OpenGDS Test")
            service.run("config", "user.email", "test@example.invalid")
            target = root / "scripts" / "test.gd"
            target.parent.mkdir()
            target.write_text("extends Node\n", encoding="utf-8")
            changes = service.status()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].path, "scripts/test.gd")
            self.assertTrue(changes[0].unstaged)
            service.stage(["scripts/test.gd"])
            changes = service.status()
            self.assertEqual(changes[0].status, "A ")
            service.commit("Add test script")
            self.assertEqual(service.status(), [])
            branch = service.branch()
            self.assertTrue(branch)
            service.create_branch("feature/test")
            self.assertEqual(service.branch(), "feature/test")
            self.assertIn("feature/test", service.branches())

    def test_status_preserves_unicode_and_spaces_in_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            target = root / "scripts" / "玩家 file.gd"
            target.parent.mkdir()
            target.write_text("extends Node\n", encoding="utf-8")
            changes = service.status()
            self.assertEqual([(item.status, item.path) for item in changes], [("??", "scripts/玩家 file.gd")])

    def test_add_remote_rejects_embedded_http_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            service = GitService(td)
            service.init()
            with self.assertRaisesRegex(ValueError, "Do not embed credentials"):
                service.add_remote("origin", "https://user:token@example.com/repo.git")


    def test_discard_untracked_file_removes_only_selected_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            target = root / "scripts" / "new.gd"
            target.parent.mkdir()
            target.write_text("extends Node\n", encoding="utf-8")
            self.assertEqual(service.status()[0].status, "??")
            service.discard(["scripts/new.gd"])
            self.assertFalse(target.exists())
            self.assertEqual(service.status(), [])

    def test_discard_tracked_modification_restores_head_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            service.run("config", "user.name", "OpenGDS Test")
            service.run("config", "user.email", "test@example.invalid")
            target = root / "main.gd"
            target.write_text("extends Node\n", encoding="utf-8")
            service.stage(["main.gd"])
            service.commit("Initial")
            target.write_text("extends Node\nfunc broken(:\n", encoding="utf-8")
            service.stage(["main.gd"])
            service.discard(["main.gd"])
            self.assertEqual(target.read_text(encoding="utf-8"), "extends Node\n")
            self.assertEqual(service.status(), [])

    def test_git_path_validation_rejects_traversal_and_drive_paths(self):
        with tempfile.TemporaryDirectory() as td:
            service = GitService(td)
            for path in ("../outside.txt", r"C:\outside.txt", "/tmp/outside.txt", "folder/../outside"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    service._validated_relative_paths([path])

    def test_discard_untracked_symlink_unlinks_link_without_touching_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = GitService(root)
            service.init()
            outside = root.parent / (root.name + "-outside.txt")
            outside.write_text("keep me", encoding="utf-8")
            link = root / "external-link.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                outside.unlink(missing_ok=True)
                self.skipTest("Symbolic links are unavailable for this user")
            try:
                service.discard(["external-link.txt"])
                self.assertFalse(link.is_symlink())
                self.assertEqual(outside.read_text(encoding="utf-8"), "keep me")
            finally:
                outside.unlink(missing_ok=True)

    def test_clone_rejects_existing_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "already-exists").mkdir()
            with self.assertRaises(ValueError):
                GitService.clone("https://example.invalid/repo.git", root / "already-exists")


if __name__ == "__main__":
    unittest.main()
