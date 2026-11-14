"""Git command integration for OpenGDS-IDE. Uses the user's installed Git CLI."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit


class GitError(RuntimeError):
    pass


def discover_git_executable(environ: dict[str, str] | None = None) -> str | None:
    """Find Git even when the app was launched before PATH was refreshed.

    Git for Windows commonly installs under the Program Files Git directory, while Scoop
    and per-user installers use separate locations. Explicit configuration wins.
    """
    env = dict(os.environ if environ is None else environ)
    explicit = str(env.get("OPENGDS_GIT_EXECUTABLE", "")).strip().strip('"')
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())

    found = shutil.which("git", path=env.get("PATH"))
    if found:
        return found

    candidates: list[Path] = []
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        root = str(env.get(key, "")).strip()
        if root:
            base = Path(root) / "Git"
            candidates.extend((base / "cmd" / "git.exe", base / "bin" / "git.exe",
                               base / "mingw64" / "bin" / "git.exe"))
    local = str(env.get("LOCALAPPDATA", "")).strip()
    if local:
        candidates.extend((Path(local) / "Programs" / "Git" / "cmd" / "git.exe",
                           Path(local) / "Programs" / "Git" / "bin" / "git.exe"))
    profile = str(env.get("USERPROFILE", "")).strip()
    if profile:
        candidates.append(Path(profile) / "scoop" / "apps" / "git" / "current" / "cmd" / "git.exe")
    # Git for Windows also records its installation root in the registry;
    # consult it for machines where the installer did not update PATH.
    if os.name == "nt":
        try:
            import winreg
            registry_locations = (
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\GitForWindows"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GitForWindows"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GitForWindows"),
            )
            for hive, key_name in registry_locations:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        install_path, _kind = winreg.QueryValueEx(key, "InstallPath")
                    base = Path(str(install_path))
                    candidates.extend((base / "cmd" / "git.exe", base / "bin" / "git.exe"))
                except OSError:
                    continue
        except ImportError:
            pass

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return None


@dataclass(frozen=True)
class GitChange:
    status: str
    path: str

    @property
    def staged(self) -> bool:
        return self.status[:1] not in {" ", "?"}

    @property
    def unstaged(self) -> bool:
        return self.status[1:2] != " " or self.status == "??"


class GitService:
    def __init__(self, root: str | Path, git_executable: str | None = None):
        self.root = Path(root).expanduser().resolve()
        self.git = git_executable or discover_git_executable()
        if not self.git:
            raise GitError("Git was not found. Install Git for Windows and restart OpenGDS-IDE.")
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)

    def run(self, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
        command = [self.git, *map(str, args)]
        try:
            result = subprocess.run(command, cwd=str(self.root), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    shell=False, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"Git command timed out after {timeout} seconds: git {' '.join(args)}") from exc
        if check and result.returncode:
            raise GitError(result.stdout.strip() or f"git {' '.join(args)} failed with exit {result.returncode}")
        return result

    def is_repository(self) -> bool:
        return self.run("rev-parse", "--is-inside-work-tree", check=False).returncode == 0

    def init(self) -> str:
        return self.run("init").stdout

    def branch(self) -> str:
        result = self.run("branch", "--show-current", check=False)
        return result.stdout.strip() or "(detached HEAD)"

    def branches(self) -> list[str]:
        output = self.run("branch", "--format=%(refname:short)", check=False).stdout
        return [line.strip() for line in output.splitlines() if line.strip()]

    def switch_branch(self, name: str) -> str:
        name = str(name).strip()
        if not name or name.startswith("-"):
            raise ValueError("Invalid branch name.")
        return self.run("switch", name).stdout

    def create_branch(self, name: str, *, switch: bool = True) -> str:
        name = str(name).strip()
        if not name or name.startswith("-"):
            raise ValueError("Invalid branch name.")
        return self.run("switch", "-c", name).stdout if switch else self.run("branch", name).stdout

    def status(self) -> list[GitChange]:
        # Keep the output as bytes: --porcelain -z uses NUL separators and
        # filenames may contain spaces, tabs, newlines, or non-ASCII bytes.
        result = subprocess.run(
            [self.git, "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, shell=False, timeout=60, check=False,
        )
        if result.returncode:
            message = result.stdout.decode("utf-8", "replace").strip()
            raise GitError(message or f"git status failed with exit {result.returncode}")

        parts = result.stdout.split(b"\x00")
        changes: list[GitChange] = []
        index = 0
        while index < len(parts):
            part = parts[index]
            index += 1
            if not part:
                continue
            status = part[:2].decode("ascii", "replace")
            # With -z, rename/copy entries carry the destination path here and
            # the original path in the following NUL-delimited field.
            path_bytes = part[3:] if len(part) > 3 else b""
            path = os.fsdecode(path_bytes)
            if "R" in status or "C" in status:
                if index < len(parts):
                    index += 1
            if path:
                changes.append(GitChange(status, path))
        return changes

    def stage(self, paths: list[str]) -> str:
        validated = self._validated_relative_paths(paths)
        return self.run("add", "--", *validated).stdout

    def unstage(self, paths: list[str]) -> str:
        validated = self._validated_relative_paths(paths)
        return self.run("restore", "--staged", "--", *validated).stdout

    def commit(self, message: str) -> str:
        message = str(message).strip()
        if not message:
            raise ValueError("Commit message cannot be empty.")
        return self.run("commit", "-m", message, timeout=120).stdout

    def fetch(self, remote: str = "") -> str:
        return self.run("fetch", remote, timeout=180).stdout if remote else self.run("fetch", "--all", timeout=180).stdout

    def pull(self, remote: str = "", branch: str = "") -> str:
        args = ["pull"]
        if remote:
            args.append(remote)
        if branch:
            args.append(branch)
        return self.run(*args, timeout=180).stdout

    def push(self, remote: str = "origin", branch: str = "") -> str:
        args = ["push", "-u", remote]
        if branch:
            args.append(branch)
        return self.run(*args, timeout=180).stdout

    def _validated_relative_paths(self, paths: list[str]) -> list[str]:
        """Validate Git pathspecs as workspace-relative paths without following symlinks."""
        if not paths:
            raise ValueError("Select at least one changed path.")
        root = Path(os.path.abspath(self.root))
        validated: list[str] = []
        for raw in paths:
            value = str(raw or "").strip().replace("\\", "/")
            posix = PurePosixPath(value)
            windows = PureWindowsPath(value)
            if (not value or "\x00" in value or posix.is_absolute()
                    or windows.is_absolute() or windows.drive
                    or any(part in {"", ".", ".."} for part in value.split("/"))):
                raise ValueError(f"Invalid repository-relative Git path: {raw!r}")
            candidate = root.joinpath(*posix.parts)
            absolute = Path(os.path.abspath(candidate))
            try:
                if os.path.commonpath((str(root), str(absolute))) != str(root):
                    raise ValueError("Git path escapes the repository root.")
            except ValueError as exc:
                raise ValueError("Git path escapes the repository root.") from exc
            # Parent symlinks could redirect a path outside the checkout. A final
            # symlink is permitted because Git stores the link itself; discard()
            # unlinks it rather than following its target.
            parent = root
            for part in posix.parts[:-1]:
                parent = parent / part
                if parent.is_symlink():
                    raise ValueError("Git paths cannot traverse symbolic-link directories.")
            validated.append(posix.as_posix())
        return list(dict.fromkeys(validated))

    def diff(self, path: str) -> str:
        relative = self._validated_relative_paths([path])[0]
        # Compare the working tree to HEAD so staged and unstaged hunks appear
        # together in one coherent review, as they do in a modern IDE.
        combined = self.run("diff", "HEAD", "--no-ext-diff", "--unified=4", "--", relative, check=False)
        if combined.stdout.strip():
            return combined.stdout
        result = self.run("diff", "--no-ext-diff", "--unified=4", "--", relative, check=False)
        if result.stdout.strip():
            return result.stdout
        staged = self.run("diff", "--cached", "--", relative, check=False)
        if staged.stdout.strip():
            return staged.stdout
        candidate = self.root.joinpath(*PurePosixPath(relative).parts)
        if candidate.is_symlink():
            return "Symbolic links are not opened as text by Source Control."
        if candidate.is_file():
            try:
                content = candidate.read_text(encoding="utf-8-sig")
                return "UNTRACKED FILE (not yet in Git history)\n\n" + content[:200_000]
            except (UnicodeDecodeError, OSError):
                return "No textual diff is available for this file."
        return "No diff available."

    def discard(self, paths: list[str]) -> str:
        """Discard staged/unstaged changes; remove untracked paths without following symlinks."""
        validated = self._validated_relative_paths(paths)
        current = {item.path: item for item in self.status()}
        tracked = [path for path in validated if path in current and current[path].status != "??"]
        untracked = [path for path in validated if path in current and current[path].status == "??"]
        output = []
        if tracked:
            output.append(self.run("restore", "--source=HEAD", "--staged", "--worktree", "--", *tracked).stdout)
        for relative in untracked:
            target = self.root.joinpath(*PurePosixPath(relative).parts)
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        return "\n".join(part for part in output if part).strip() or "Selected uncommitted changes discarded."

    def history_graph(self, limit: int = 150) -> list[dict[str, str]]:
        """Return an ASCII commit graph with abbreviated hashes and subjects."""
        limit = max(1, min(int(limit), 500))
        result = self.run("log", "--all", "--graph", "--decorate", "--oneline",
                          "--date-order", "--no-color", "-n", str(limit), check=False)
        if result.returncode:
            if "does not have any commits" in result.stdout or "unknown revision" in result.stdout:
                return []
            raise GitError(result.stdout.strip() or "Could not read Git history.")
        rows = []
        for line in result.stdout.splitlines():
            match = re.search(r"(?<![0-9a-fA-F])([0-9a-fA-F]{7,40})(?![0-9a-fA-F])", line)
            if not match:
                continue
            graph = line[:match.start()]
            remainder = line[match.end():].strip()
            rows.append({"hash": match.group(1), "graph": graph, "subject": remainder, "line": line})
        return rows

    @staticmethod
    def _validate_commit(commit: str) -> str:
        value = str(commit or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
            raise ValueError("Invalid commit identifier.")
        return value

    def commit_details(self, commit: str) -> str:
        value = self._validate_commit(commit)
        result = self.run("show", "--no-ext-diff", "--no-renames", "--format=fuller", "--stat", value)
        return result.stdout

    def commit_files(self, commit: str) -> list[str]:
        value = self._validate_commit(commit)
        result = self.run("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", value)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def commit_diff(self, commit: str, path: str = "") -> str:
        value = self._validate_commit(commit)
        args = ["show", "--format=", "--no-ext-diff", "--unified=4", value]
        if path:
            relative = self._validated_relative_paths([path])[0]
            args += ["--", relative]
        return self.run(*args).stdout

    def remotes(self) -> dict[str, str]:
        output = self.run("remote", "-v", check=False).stdout
        result: dict[str, str] = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1] == "(fetch)":
                result[parts[0]] = parts[1]
        return result

    def add_remote(self, name: str, url: str) -> str:
        name, url = str(name).strip(), str(url).strip()
        if (not name or name.startswith("-") or any(ch.isspace() for ch in name)
                or ".." in name or name.endswith(".lock")):
            raise ValueError("Remote name is invalid.")
        if not url or any(ch.isspace() for ch in url):
            raise ValueError("A valid remote URL is required.")
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
            raise ValueError("Do not embed credentials in a remote URL. Use Git Credential Manager or SSH authentication.")
        return self.run("remote", "add", name, url).stdout

    @classmethod
    def clone(cls, url: str, destination: str | Path, git_executable: str | None = None) -> Path:
        git = git_executable or discover_git_executable()
        if not git:
            raise GitError("Git was not found. Install Git for Windows or set OPENGDS_GIT_EXECUTABLE to git.exe.")
        url = str(url).strip()
        target = Path(destination).expanduser().resolve()
        if not url or target.exists():
            raise ValueError("A repository URL is required and destination must not already exist.")
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([git, "clone", "--", url, str(target)], cwd=str(target.parent),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", shell=False, timeout=600, check=False)
        if result.returncode:
            raise GitError(result.stdout.strip() or "Git clone failed.")
        return target

    def github_auth_status(self) -> tuple[bool, str]:
        gh = shutil.which("gh")
        if not gh:
            raise GitError("GitHub CLI (gh) is not installed. Install it to use the Sign in to GitHub action. Git Credential Manager can still authenticate pushes and pulls.")
        result = subprocess.run([gh, "auth", "status"], cwd=str(self.root), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", shell=False, timeout=20, check=False)
        return result.returncode == 0, result.stdout.strip()

    def launch_github_login(self) -> None:
        gh = shutil.which("gh")
        if not gh:
            raise GitError("GitHub CLI (gh) is not installed. Install GitHub CLI or use Git Credential Manager for Git HTTPS authentication.")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if __import__("os").name == "nt" else 0
        # Do not redirect stdio: gh auth login is interactive and needs a real
        # terminal to show its device code/browser instructions.
        subprocess.Popen([gh, "auth", "login"], cwd=str(self.root), shell=False,
                         creationflags=flags, start_new_session=(flags == 0))
