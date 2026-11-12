"""Safe subprocess adapter for the OpenGDS.py command-line backend."""
from __future__ import annotations
import os, sys, subprocess, logging, re
from pathlib import Path

from logging_system import log_event, log_directory, configure_logging

class BackendError(RuntimeError): pass

class OpenGDSBackend:
    def __init__(self, script: str | Path):
        self.script = Path(script).expanduser().resolve()
        self.default_timeout = 300
        if not self.script.is_file(): raise FileNotFoundError(f"OpenGDS backend not found: {self.script}")
        if not logging.getLogger("opengds").handlers:
            configure_logging(log_directory() / "studio.log")

    def command(self, *args: str) -> list[str]:
        return [sys.executable, str(self.script), *map(str, args)]

    def run(self, *args: str, cwd: str | Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
        command = self.command(*args)
        mode = str(args[0]) if args else "core"
        default_category = "GDSCRIPT" if mode == "comp" else ("GODOT_DEBUG" if mode == "dbg" else "GDSC")
        log_event("BUILD", logging.INFO, f"Launching OpenGDS core: {command!r}; cwd={cwd or os.getcwd()}")
        core_log = log_directory() / "core.log"
        core_log_offset = core_log.stat().st_size if core_log.exists() else 0
        effective_timeout = self.default_timeout if timeout is None else timeout
        try:
            result = subprocess.run(command, cwd=str(cwd) if cwd else None,
                                    text=True, encoding="utf-8", errors="replace",
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=effective_timeout, shell=False, env=os.environ.copy())
        except subprocess.TimeoutExpired:
            log_event("PYTHON", logging.ERROR, f"OpenGDS subprocess timed out: {command!r}", exc_info=True)
            raise
        except Exception:
            log_event("PYTHON", logging.ERROR, f"Could not execute OpenGDS subprocess: {command!r}", exc_info=True)
            raise

        # The OpenGDS subprocess writes internal lexer/decoder/runtime traces to core.log.
        # Merge only the newly appended records into the Studio log so they are visible
        # in the colored in-app viewer as well as remaining available in the raw core log.
        self._merge_core_log(core_log, core_log_offset)

        output_lines = result.stdout.splitlines()
        for line in output_lines:
            stripped = line.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if any(token in upper for token in ("TRACEBACK", "PYTHON EXCEPTION", "UNHANDLED EXCEPTION")):
                category, level = "PYTHON", logging.ERROR
            elif "GDSCRIPT" in upper and any(token in upper for token in ("ERROR", "WARNING", "FAILED")):
                category, level = "GDSCRIPT", logging.ERROR if "ERROR" in upper or "FAILED" in upper else logging.WARNING
            elif any(token in upper for token in ("[ERROR]", "ERROR:", "FAILED", "INVALID GDSC", "NOT GDSC")):
                category, level = default_category, logging.ERROR
            elif mode == "dbg" and any(token in upper for token in ("GODOT", "BREAKPOINT", "ENGINE")):
                category, level = "GODOT_DEBUG", logging.INFO
            else:
                category, level = default_category, logging.INFO
            log_event(category, level, line)

        log_event("BUILD", logging.INFO if result.returncode == 0 else logging.ERROR,
                  f"OpenGDS core process finished: mode={mode}, exit_code={result.returncode}")
        if result.returncode:
            raise BackendError(result.stdout.strip() or f"OpenGDS exited with code {result.returncode}")
        return result

    @staticmethod
    def _merge_core_log(path: Path, offset: int) -> None:
        if not path.is_file():
            return
        try:
            size = path.stat().st_size
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(offset if size >= offset else 0)
                appended = stream.read()
        except Exception:
            log_event("PYTHON", logging.ERROR, f"Could not read OpenGDS core log: {path}", exc_info=True)
            return
        header = re.compile(r"^\d{4}-\d{2}-\d{2} .*? (DEBUG|INFO|WARNING|ERROR|CRITICAL) \[([A-Z_]+)\] [^:]+: (.*)$")
        active_category, active_level = "CORE", logging.INFO
        for line in appended.splitlines():
            match = header.match(line)
            if match:
                level_name, category, message = match.groups()
                active_category = category if category in {"CORE", "GUI", "GODOT_ENGINE", "GODOT_ENGINE_ERR", "GODOT_DEBUG", "GDSCRIPT", "GDSC", "PYTHON", "LOGIC", "LSP", "DAP", "BUILD", "FILE", "SYSTEM"} else "CORE"
                active_level = getattr(logging, level_name, logging.INFO)
                log_event(active_category, active_level, f"OpenGDS core: {message}")
            elif line.strip():
                log_event(active_category, active_level, f"OpenGDS core trace: {line}")

    def compile(self, source: str | Path, output: str | Path | None = None,
                compressed: bool = True, overwrite: bool = False, tab_size: int = 4, continue_on_error: bool = False) -> subprocess.CompletedProcess:
        args = ["comp", str(source), "--tab-size", str(tab_size)]
        if output: args += ["--output", str(output)]
        if not compressed: args.append("--no-compress")
        if overwrite: args.append("--force")
        if continue_on_error: args.append("--continue-on-error")
        return self.run(*args)

    def diff(self, first: str | Path, second: str | Path) -> str:
        return self.run("diff", str(first), str(second)).stdout

    def decompile(self, binary: str | Path) -> str:
        return self.run("dcmp", str(binary)).stdout

    def inspect(self, mode: str, path: str | Path, *, context: int = 4, show_tokens: bool = False, max_tokens: int = 200, breakpoints=()) -> str:
        if mode not in {"info", "hexdump", "audit", "consts", "disasm", "dbg"}:
            raise ValueError(f"Unsupported inspection mode: {mode}")
        args = [mode, str(path)]
        if mode == "dbg":
            args += ["--classic", "--context", str(context), "--max-tokens", str(max_tokens)]
            if show_tokens: args.append("--show-tokens")
            for line in breakpoints: args += ["--breakpoint", str(int(line))]
        return self.run(*args).stdout

    def runtime_debug_command(self, binary: str | Path, godot: str, project: str,
                              breakpoints=(), interrupt=False, scene="", headless=False,
                              source_path="", include_frame_callbacks=False, extra_args=(), dry_run=False) -> list[str]:
        if include_frame_callbacks and not interrupt:
            raise ValueError("include_frame_callbacks requires interrupt=True")
        args = ["dbg", str(binary), "--godot", godot, "--project", project]
        if interrupt: args.append("--interrupt")
        for line in breakpoints: args += ["--breakpoint", str(int(line))]
        if scene: args += ["--scene", scene]
        if headless: args.append("--headless")
        if source_path: args += ["--source-path", source_path]
        if include_frame_callbacks: args.append("--include-frame-callbacks")
        if dry_run: args.append("--dry-run")
        for arg in extra_args: args += ["--godot-arg", str(arg)]
        return self.command(*args)

    def install_update(self, new_script: str | Path) -> Path:
        """Replace backend atomically, keeping a timestamped backup."""
        import shutil, datetime
        source = Path(new_script).resolve()
        if not source.is_file(): raise FileNotFoundError(source)
        if source == self.script: raise ValueError("Selected backend is already active")
        log_event("CORE", logging.WARNING, f"Updating OpenGDS core: {source} -> {self.script}")
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.script.with_name(self.script.stem + f".backup-{stamp}" + self.script.suffix)
        shutil.copy2(self.script, backup)
        temp = self.script.with_suffix(self.script.suffix + ".new")
        shutil.copy2(source, temp)
        try: os.replace(temp, self.script)
        finally:
            if temp.exists(): temp.unlink()
        log_event("CORE", logging.INFO, f"OpenGDS core updated. Backup created at {backup}")
        return backup
