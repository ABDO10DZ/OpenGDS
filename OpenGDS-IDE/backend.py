"""Safe subprocess adapter for the OpenGDS.py command-line backend."""
from __future__ import annotations
import os, sys, subprocess, logging, re, time, shutil, tempfile, importlib.util, hashlib

import gdsc_compat as compat
from pathlib import Path

from logging_system import log_event, log_directory, configure_logging

class BackendError(RuntimeError): pass


def is_frozen_app() -> bool:
    """Detect PyInstaller frozen mode, including its one-file extraction runtime."""
    return bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))


def default_backend_path() -> Path:
    """Return the embedded GUI executable or adjacent Python core by default."""
    if is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(__file__).with_name("OpenGDS.py").resolve()


def find_python_command() -> list[str] | None:
    """Find a real Python interpreter, excluding the frozen IDE executable."""
    if not is_frozen_app():
        return [sys.executable]
    for candidate in ("python.exe", "python", "python3.exe", "python3"):
        found = shutil.which(candidate)
        if found:
            return [found]
    launcher = shutil.which("py.exe") or shutil.which("py")
    if launcher:
        return [launcher, "-3"]
    return None


class OpenGDSBackend:
    def __init__(self, script: str | Path | None = None):
        # Explicit paths always win, including in a frozen GUI. This lets users
        # replace the embedded core with a standalone opengds-cli.exe or, when
        # Python is installed, an updated OpenGDS.py file.
        requested_path = Path(script).expanduser().resolve() if script is not None else None
        running_exe = Path(sys.executable).resolve() if is_frozen_app() else None
        self.embedded = bool(is_frozen_app() and (requested_path is None or requested_path == running_exe))
        self.script = (default_backend_path() if requested_path is None else requested_path)
        self.standalone_executable = (not self.embedded and self.script.suffix.lower() == ".exe")
        self.python_command = None if self.standalone_executable or self.embedded else find_python_command()
        self.default_timeout = 300
        self._compat_core_module = None
        if not self.embedded and not self.script.is_file():
            raise FileNotFoundError(f"OpenGDS backend not found: {self.script}")
        if not self.embedded and not self.standalone_executable and not self.python_command:
            raise BackendError(
                "OpenGDS.py requires a Python interpreter. Select opengds-cli.exe to run without Python."
            )
        if not logging.getLogger("opengds").handlers:
            configure_logging(log_directory() / "opengds-ide.log")

    def command(self, *args: str) -> list[str]:
        if self.embedded:
            return [str(sys.executable), "--opengds-cli", *map(str, args)]
        if self.standalone_executable:
            return [str(self.script), *map(str, args)]
        return [*(self.python_command or [sys.executable]), str(self.script), *map(str, args)]

    def run(self, *args: str, cwd: str | Path | None = None, timeout: int | None = None, cancel_event=None) -> subprocess.CompletedProcess:
        mode = str(args[0]) if args else "core"
        if mode == "dcmp" and len(args) > 1 and Path(args[1]).expanduser().is_dir():
            return self._decompile_folder_compat(args, cancel_event=cancel_event)
        command = self.command(*args)
        default_category = "GDSCRIPT" if mode == "comp" else ("GODOT_DEBUG" if mode == "dbg" else "GDSC")
        log_event("BUILD", logging.INFO, f"Launching OpenGDS core: {command!r}; cwd={cwd or os.getcwd()}")
        core_log = log_directory() / "core.log"
        core_log_offset = core_log.stat().st_size if core_log.exists() else 0
        effective_timeout = self.default_timeout if timeout is None else timeout
        try:
            run_options = {}
            if self.embedded and os.name == "nt":
                # The application is a GUI-subsystem executable; prevent a
                # transient console window when it re-launches itself as CLI.
                run_options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if cancel_event is None:
                result = subprocess.run(command, cwd=str(cwd) if cwd else None,
                                        text=True, encoding="utf-8", errors="replace",
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=effective_timeout, shell=False, env=os.environ.copy(),
                                        **run_options)
            else:
                process = subprocess.Popen(command, cwd=str(cwd) if cwd else None,
                                           text=True, encoding="utf-8", errors="replace",
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           shell=False, env=os.environ.copy(), **run_options)
                started = time.monotonic()
                output = ""
                while True:
                    if cancel_event.is_set():
                        process.terminate()
                        try:
                            output, _ = process.communicate(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            output, _ = process.communicate()
                        log_event("BUILD", logging.WARNING,
                                  f"OpenGDS subprocess cancelled by user: {command!r}")
                        raise BackendError("OpenGDS operation cancelled by user.")
                    elapsed = time.monotonic() - started
                    if effective_timeout is not None and elapsed >= effective_timeout:
                        process.kill()
                        output, _ = process.communicate()
                        raise subprocess.TimeoutExpired(command, effective_timeout, output=output)
                    try:
                        output, _ = process.communicate(timeout=0.15)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                result = subprocess.CompletedProcess(command, process.returncode, output)
        except subprocess.TimeoutExpired:
            log_event("PYTHON", logging.ERROR, f"OpenGDS subprocess timed out: {command!r}", exc_info=True)
            raise
        except Exception:
            log_event("PYTHON", logging.ERROR, f"Could not execute OpenGDS subprocess: {command!r}", exc_info=True)
            raise

        # The OpenGDS subprocess writes internal lexer/decoder/runtime traces to core.log.
        # Merge only the newly appended records into the OpenGDS-IDE log so they are visible
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
                active_category = category if category in {"CORE", "GUI", "GODOT_ENGINE", "GODOT_ENGINE_ERR", "GODOT_DEBUG", "GDSCRIPT", "GDSC", "PYTHON", "LOGIC", "LSP", "DAP", "BUILD", "FILE", "AI", "GIT", "SYSTEM"} else "CORE"
                active_level = getattr(logging, level_name, logging.INFO)
                log_event(active_category, active_level, f"OpenGDS core: {message}")
            elif line.strip():
                log_event(active_category, active_level, f"OpenGDS core trace: {line}")

    def _compat_core(self):
        if self._compat_core_module is not None:
            return self._compat_core_module
        if self.embedded or self.script.suffix.lower() != ".py":
            raise BackendError("GDSC v100 support requires a Python OpenGDS.py core; the core file itself is not modified.")
        module_name = "_opengds_compat_core_" + hashlib.sha256(str(self.script).encode()).hexdigest()[:12]
        spec = importlib.util.spec_from_file_location(module_name, self.script)
        if spec is None or spec.loader is None:
            raise BackendError(f"Cannot load OpenGDS core for compatibility: {self.script}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        self._compat_core_module = module
        return module

    def _decompile_folder_compat(self, args, cancel_event=None):
        root = Path(args[1]).expanduser().resolve()
        tail = [str(x) for x in args[2:]]
        output_root = Path(str(root) + ".dcmp")
        force = "--force" in tail
        if "--outdir" in tail:
            at = tail.index("--outdir")
            if at + 1 >= len(tail):
                raise ValueError("--outdir requires a directory")
            output_root = Path(tail[at + 1]).expanduser().resolve()
        core = self._compat_core()
        output_root.mkdir(parents=True, exist_ok=True)
        ok, failed, skipped, messages = 0, 0, 0, []
        for binary in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".gdc"):
            if cancel_event is not None and cancel_event.is_set():
                raise BackendError("Operation cancelled by user")
            try:
                data = binary.read_bytes()
                header = compat.inspect_header(data)
                if header.version in (100, 101):
                    _header, source = compat.decompile_data(data, core)
                elif header.profile and header.profile.capability == "gdre":
                    source = compat.decompile_legacy_file(binary)
                else:
                    skipped += 1
                    messages.append(f"[SKIP] {binary}: unknown GDSC revision {header.version}")
                    continue
                relative = binary.relative_to(root).with_suffix(".gd")
                target = output_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and not force:
                    skipped += 1
                    messages.append(f"[SKIP] {binary}: output exists: {target}")
                    continue
                temp = target.with_name(target.name + ".opengds-tmp")
                try:
                    temp.write_text(source, encoding="utf-8")
                    os.replace(temp, target)
                finally:
                    if temp.exists():
                        temp.unlink()
                ok += 1
                messages.append(f"[OK] {binary} -> {target} (GDSC v{header.version})")
            except Exception as exc:
                failed += 1
                messages.append(f"[ERROR] {binary}: {exc}")
        report = "\n".join([
            f"Folder decompile: {root}", f"Succeeded: {ok}",
            f"Failed: {failed}", f"Skipped: {skipped}", *messages
        ])
        return subprocess.CompletedProcess(
            ["opengds-compat", "dcmp", str(root)], 1 if failed else 0, report, ""
        )

    def compile(self, source: str | Path, output: str | Path | None = None,
                compressed: bool = True, overwrite: bool = False, tab_size: int = 4,
                continue_on_error: bool = False, cancel_event=None,
                bytecode_version: int = 101, engine_version: str = "") -> subprocess.CompletedProcess:
        if int(bytecode_version) not in (100, 101):
            if not engine_version.strip():
                raise compat.ExternalBytecodeToolRequired(
                    "Legacy GDSC compilation requires an explicit Godot engine version "
                    "(for example 3.5.0) and an installed GDRE Tools executable."
                )
            source_path = Path(source).expanduser().resolve()
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            target = Path(output).expanduser().resolve() if output else source_path.with_suffix(".gdc")
            if target.exists() and not overwrite:
                raise BackendError(f"Output already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="opengds-gdre-", dir=target.parent) as stage_dir:
                staged = Path(stage_dir) / "compiled.gdc"
                compat.compile_legacy_file(source_path, staged, engine_version.strip(), timeout=self.default_timeout)
                header = compat.inspect_header(staged.read_bytes())
                if not header.profile or header.profile.capability != "gdre":
                    raise compat.GDSCCompatibilityError(
                        f"GDRE Tools output revision {header.version} is not a recognized legacy GDSC version."
                    )
                os.replace(staged, target)
            message = (
                f"Compiled {source_path} -> {target}; legacy GDSC v{header.version}; "
                f"Godot {engine_version.strip()}"
            )
            return subprocess.CompletedProcess(
                ["gdre_tools", "--compile", str(source_path)], 0, message
            )
        if int(bytecode_version) != 101:
            source_path = Path(source).expanduser().resolve()
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            target = Path(output).expanduser().resolve() if output else source_path.with_suffix(".gdc")
            if target.exists() and not overwrite:
                raise BackendError(f"Output already exists: {target}")
            core = self._compat_core()
            data = compat.compile_data(
                source_path.read_text(encoding="utf-8-sig"), core, 100,
                compressed=compressed, tab_size=tab_size
            )
            header, decoded = compat.decode_compatible(data, core)
            errors = [x for x in core.validate_gdc_structure(decoded) if x[0] == "ERROR"]
            if header.version != 100 or errors:
                raise BackendError("GDSC v100 failed structural validation: " + repr(errors[:5]))
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".opengds-tmp")
            try:
                temp.write_bytes(data)
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            message = f"Compiled {source_path} -> {target}; GDSC v100; {len(decoded[5])} tokens"
            return subprocess.CompletedProcess(["opengds-compat", "comp", str(source_path)], 0, message)
        args = ["comp", str(source), "--tab-size", str(tab_size)]
        if output: args += ["--output", str(output)]
        if not compressed: args.append("--no-compress")
        if overwrite: args.append("--force")
        if continue_on_error: args.append("--continue-on-error")
        return self.run(*args, cancel_event=cancel_event)

    def diff(self, first: str | Path, second: str | Path) -> str:
        return self.run("diff", str(first), str(second)).stdout

    def decompile(self, binary: str | Path, *, cancel_event=None) -> str:
        source = Path(binary).expanduser().resolve()
        header = compat.inspect_header(source.read_bytes())
        if header.version == 100:
            return compat.decompile_data(source.read_bytes(), self._compat_core())[1]
        if header.version != 101:
            if header.profile and header.profile.capability == "gdre":
                return compat.decompile_legacy_file(source)
            raise compat.GDSCCompatibilityError(f"Unsupported GDSC revision {header.version}")
        return self.run("dcmp", str(binary), cancel_event=cancel_event).stdout

    def inspect(self, mode: str, path: str | Path, *, context: int = 4, show_tokens: bool = False,
                max_tokens: int = 200, breakpoints=(), cancel_event=None) -> str:
        if mode not in {"info", "hexdump", "audit", "consts", "disasm", "dbg"}:
            raise ValueError(f"Unsupported inspection mode: {mode}")
        data = Path(path).expanduser().resolve().read_bytes()
        header = compat.inspect_header(data)
        if header.version != 100:
            return self._inspect_command(mode, path, context, show_tokens, max_tokens, breakpoints, cancel_event)
        core = self._compat_core()
        normalized = compat.normalize_v100(data, core)
        with tempfile.TemporaryDirectory(prefix="opengds-v100-") as temp:
            normalized_path = Path(temp) / Path(path).name
            normalized_path.write_bytes(normalized)
            report = self._inspect_command(mode, normalized_path, context, show_tokens, max_tokens, breakpoints, cancel_event)
        report = report.replace(str(normalized_path), str(Path(path).expanduser().resolve()))
        report = re.sub(r"(?m)^GDSC version: 101$", "GDSC version: 100", report)
        return report

    def _inspect_command(self, mode, path, context, show_tokens, max_tokens, breakpoints, cancel_event):
        args = [mode, str(path)]
        if mode == "dbg":
            args += ["--classic", "--context", str(context), "--max-tokens", str(max_tokens)]
            if show_tokens: args.append("--show-tokens")
            for line in breakpoints: args += ["--breakpoint", str(int(line))]
        return self.run(*args, cancel_event=cancel_event).stdout

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
        """Replace a source backend atomically; frozen core updates require a new EXE."""
        if self.embedded:
            raise BackendError("The OpenGDS core is embedded in this executable. Select a standalone opengds-cli.exe or configure an external OpenGDS.py core.")
        import datetime
        source = Path(new_script).resolve()
        if not source.is_file(): raise FileNotFoundError(source)
        if source.suffix.lower() != ".py":
            raise ValueError("Atomic source-core updates accept OpenGDS.py files only; configure .exe files as standalone CLI backends.")
        if self.script.suffix.lower() != ".py":
            raise BackendError("The active backend is not a Python source file. Select an OpenGDS.py target first.")
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
