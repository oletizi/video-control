"""Shared Resolve connection bootstrap for the discovery spike.

THROWAWAY spike code (see spike/README.md). This module is the single place that
sets up the DaVinci Resolve scripting environment and resolves a working Python
interpreter, so every probe can reuse it.

It implements:
  - R1 (research.md): env-var bootstrap + native-module connection with a
    fail-fast diagnosis on an unreachable Resolve.
  - R2 / FR-003: interpreter + native-library resolution in discovery order
    (operator default first, then documented fallbacks), producing an ordered
    list of InterpreterAttempt records (data-model.md).

Design constraints:
  - Python 3.11-compatible syntax ONLY (must also run under a fallback 3.11, not
    just the operator's 3.14). No 3.12+ syntax.
  - Talks to a LIVE app that may not be running. Every entry point degrades
    gracefully: it never hangs and never raises out to the caller on absence.

Usable both as a module (import the functions below) and as a script:
    python spike/resolve_env.py
which prints the ordered interpreter attempts plus a connection diagnosis as JSON
(useful for the doctor probe).
"""

import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import threading

# --------------------------------------------------------------------------- #
# macOS Resolve scripting environment (vendor README values)
# --------------------------------------------------------------------------- #

DEFAULT_RESOLVE_SCRIPT_API = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
)
DEFAULT_RESOLVE_SCRIPT_LIB = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/"
    "Fusion/fusionscript.so"
)

# Glob roots searched for a Resolve-provided Python *interpreter* (best-effort).
# IMPORTANT: we only ever probe an actual python executable — never the Resolve
# GUI binary (e.g. .../Contents/MacOS/Resolve), because invoking that with `-c`
# would launch the app. Candidates are further filtered by _looks_like_python().
_RESOLVE_RUNTIME_GLOBS = [
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/**/python3",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/**/python3.*",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/**/bin/python*",
]

# How long (seconds) to wait on a subprocess import probe or an in-process
# connect before declaring a timeout. Kept short so nothing hangs the operator.
_IMPORT_PROBE_TIMEOUT_S = 20
_CONNECT_TIMEOUT_S = 20

# Module-level record of the most recent connect() failure reason.
last_error: str | None = None


# --------------------------------------------------------------------------- #
# Environment bootstrap
# --------------------------------------------------------------------------- #


def resolve_env_vars() -> dict:
    """Return the three scripting env vars the spike uses, WITHOUT mutating os.environ.

    Honors any values the operator has already exported; otherwise supplies the
    documented macOS defaults. PYTHONPATH is the existing value with
    ``<RESOLVE_SCRIPT_API>/Modules/`` appended (so ``DaVinciResolveScript`` is
    importable).
    """
    api = os.environ.get("RESOLVE_SCRIPT_API", DEFAULT_RESOLVE_SCRIPT_API)
    lib = os.environ.get("RESOLVE_SCRIPT_LIB", DEFAULT_RESOLVE_SCRIPT_LIB)

    modules_dir = os.path.join(api, "Modules")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing_pythonpath.split(os.pathsep) if p]
    if modules_dir not in parts:
        parts.append(modules_dir)
    pythonpath = os.pathsep.join(parts)

    return {
        "RESOLVE_SCRIPT_API": api,
        "RESOLVE_SCRIPT_LIB": lib,
        "PYTHONPATH": pythonpath,
    }


def ensure_env() -> dict:
    """Set the scripting env vars into os.environ if not already set, and make the
    ``Modules`` dir importable in THIS process. Returns the effective env vars.
    """
    env = resolve_env_vars()
    os.environ.setdefault("RESOLVE_SCRIPT_API", env["RESOLVE_SCRIPT_API"])
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", env["RESOLVE_SCRIPT_LIB"])
    # PYTHONPATH must reflect the appended Modules dir even if it was already set.
    os.environ["PYTHONPATH"] = env["PYTHONPATH"]

    modules_dir = os.path.join(env["RESOLVE_SCRIPT_API"], "Modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)
    return env


# --------------------------------------------------------------------------- #
# Interpreter discovery (FR-003 order)
# --------------------------------------------------------------------------- #

# The tiny probe snippet run inside a candidate interpreter. It sets up sys.path
# from the injected env, tries to import DaVinciResolveScript (which loads the
# native fusionscript.so), and prints a single JSON line describing the result.
# It deliberately does NOT call scriptapp() — importing is the load test; a live
# connection is a separate concern and could depend on Resolve being up.
_SUBPROCESS_PROBE = r"""
import json, os, platform, sys

api = os.environ.get("RESOLVE_SCRIPT_API", "")
modules = os.path.join(api, "Modules")
if modules and modules not in sys.path:
    sys.path.insert(0, modules)

out = {
    "version": platform.python_version(),
    "arch": platform.machine(),
    "load_result": "fail",
    "failure_type": None,
}
try:
    import DaVinciResolveScript  # noqa: F401
    out["load_result"] = "pass"
except ImportError as exc:
    out["failure_type"] = "import-error: " + str(exc)
except Exception as exc:  # native-lib load failures surface here
    out["failure_type"] = type(exc).__name__ + ": " + str(exc)
print(json.dumps(out))
"""


def _repro_command(interpreter: str) -> str:
    """A copy-pasteable command that reproduces a single interpreter's load test."""
    env = resolve_env_vars()
    return (
        f'RESOLVE_SCRIPT_API="{env["RESOLVE_SCRIPT_API"]}" '
        f'RESOLVE_SCRIPT_LIB="{env["RESOLVE_SCRIPT_LIB"]}" '
        f'PYTHONPATH="{env["PYTHONPATH"]}" '
        f'"{interpreter}" -c "import DaVinciResolveScript; print(\'loaded\')"'
    )


def _new_attempt(path: str, origin: str) -> dict:
    """Build the InterpreterAttempt skeleton (data-model.md shape) for one path."""
    env = resolve_env_vars()
    return {
        "path": path,
        "origin": origin,
        "version": None,
        "arch": None,
        "load_result": "fail",
        "failure_type": None,
        "env_vars": env,
        "native_lib_path": env["RESOLVE_SCRIPT_LIB"],
        "repro_command": _repro_command(path),
    }


def _attempt_in_process() -> dict:
    """Load test for the CURRENT interpreter, done in-process (per the task: import
    is attempted in this process for the operator default).
    """
    attempt = _new_attempt(sys.executable, "operator-default (current interpreter)")
    attempt["version"] = platform.python_version()
    attempt["arch"] = platform.machine()
    ensure_env()
    try:
        import DaVinciResolveScript  # noqa: F401

        attempt["load_result"] = "pass"
    except ImportError as exc:
        attempt["failure_type"] = "import-error: " + str(exc)
    except Exception as exc:  # native-lib (fusionscript.so) load failure
        attempt["failure_type"] = type(exc).__name__ + ": " + str(exc)
    return attempt


def _attempt_subprocess(path: str, origin: str) -> dict:
    """Load test for a NON-current interpreter by shelling out and running the
    probe snippet, parsing its JSON. Import of the native lib MUST happen inside
    the target interpreter, hence the subprocess.
    """
    attempt = _new_attempt(path, origin)
    if not os.path.exists(path):
        attempt["failure_type"] = "interpreter-not-found"
        return attempt

    env = dict(os.environ)
    env.update(resolve_env_vars())
    try:
        proc = subprocess.run(
            [path, "-c", _SUBPROCESS_PROBE],
            env=env,
            capture_output=True,
            text=True,
            timeout=_IMPORT_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        attempt["failure_type"] = "timeout: import probe exceeded %ds" % _IMPORT_PROBE_TIMEOUT_S
        return attempt
    except OSError as exc:
        attempt["failure_type"] = "spawn-error: " + str(exc)
        return attempt

    line = (proc.stdout or "").strip().splitlines()
    payload = None
    for candidate in reversed(line):
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if payload is None:
        stderr = (proc.stderr or "").strip()
        attempt["failure_type"] = "probe-no-json (rc=%d): %s" % (
            proc.returncode,
            stderr[:400] if stderr else "no output",
        )
        return attempt

    attempt["version"] = payload.get("version")
    attempt["arch"] = payload.get("arch")
    attempt["load_result"] = payload.get("load_result", "fail")
    attempt["failure_type"] = payload.get("failure_type")
    return attempt


def _discover_fallback_31x() -> list[tuple[str, str]]:
    """Locate a pinned python3.11, via PATH, pyenv, or uv. Returns (path, origin)
    pairs, deduped by resolved real path.
    """
    found: list[tuple[str, str]] = []

    which = shutil.which("python3.11")
    if which:
        found.append((which, "documented-fallback (python3.11 on PATH)"))

    pyenv = shutil.which("pyenv")
    if pyenv:
        try:
            proc = subprocess.run(
                [pyenv, "which", "python3.11"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            candidate = (proc.stdout or "").strip()
            if proc.returncode == 0 and candidate and os.path.exists(candidate):
                found.append((candidate, "documented-fallback (pyenv python3.11)"))
        except (subprocess.TimeoutExpired, OSError):
            pass

    uv = shutil.which("uv")
    if uv:
        try:
            proc = subprocess.run(
                [uv, "python", "find", "3.11"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            candidate = (proc.stdout or "").strip()
            if proc.returncode == 0 and candidate and os.path.exists(candidate):
                found.append((candidate, "documented-fallback (uv python3.11)"))
        except (subprocess.TimeoutExpired, OSError):
            pass

    return found


def _looks_like_python(path: str) -> bool:
    """True only for an executable file whose basename names a python interpreter.

    Guards against ever probing the Resolve GUI binary (which a bare `-c` would
    launch).
    """
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        return False
    base = os.path.basename(path).lower()
    return base == "python3" or base.startswith("python3.") or base == "python"


def _discover_resolve_runtime() -> list[tuple[str, str]]:
    """Any Resolve-provided Python interpreter found in the bundle (documented
    fallback). Only real python executables are returned — never the GUI binary.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in _RESOLVE_RUNTIME_GLOBS:
        for candidate in glob.glob(pattern, recursive=True):
            if candidate in seen or not _looks_like_python(candidate):
                continue
            seen.add(candidate)
            found.append(
                (candidate, "documented-fallback (Resolve-provided runtime)")
            )
    return found


def interpreter_attempts() -> list[dict]:
    """Return the ordered list of InterpreterAttempt records (FR-003 discovery order):

      1. operator default (current interpreter, in-process import)
      2. pinned python3.11 (PATH / pyenv / uv), via subprocess
      3. any Resolve-provided runtime, via subprocess

    The first record with ``load_result == "pass"`` is the working interpreter.
    Deduped by resolved real path so the current interpreter is not re-probed.
    """
    attempts: list[dict] = []
    seen: set[str] = set()

    def _real(p: str) -> str:
        try:
            return os.path.realpath(p)
        except OSError:
            return p

    # 1. Operator default — in-process.
    current = _attempt_in_process()
    attempts.append(current)
    seen.add(_real(sys.executable))

    # 2 + 3. Documented fallbacks — each in its own target interpreter.
    for path, origin in _discover_fallback_31x() + _discover_resolve_runtime():
        rp = _real(path)
        if rp in seen:
            continue
        seen.add(rp)
        attempts.append(_attempt_subprocess(path, origin))

    return attempts


def working_interpreter(attempts: list[dict] | None = None) -> dict | None:
    """The first attempt whose native lib loaded, or None if none did."""
    if attempts is None:
        attempts = interpreter_attempts()
    for attempt in attempts:
        if attempt.get("load_result") == "pass":
            return attempt
    return None


# --------------------------------------------------------------------------- #
# Live connection (R1 / FR-001)
# --------------------------------------------------------------------------- #


def _connect_worker(result: dict) -> None:
    """Run the import + scriptapp handshake, storing (resolve, error) in ``result``.

    Runs on a worker thread so connect() can bound it with a timeout and never
    hang the operator, even if the native call blocks.
    """
    try:
        ensure_env()
        import DaVinciResolveScript as dvr

        resolve = dvr.scriptapp("Resolve")
        result["resolve"] = resolve
        if resolve is None:
            result["error"] = (
                "scriptapp('Resolve') returned None — Resolve is not reachable "
                "(not running, external scripting disabled, or free edition)."
            )
    except ImportError as exc:
        result["error"] = (
            "Could not import DaVinciResolveScript in this interpreter "
            "(%s): %s" % (sys.executable, exc)
        )
    except Exception as exc:  # native-lib load / unexpected API error
        result["error"] = "%s while connecting: %s" % (type(exc).__name__, exc)


def connect():
    """Import DaVinciResolveScript and call scriptapp('Resolve').

    Returns the resolve object on success, or None if unreachable. NEVER hangs
    (bounded by a worker-thread timeout) and NEVER raises on absence. On None,
    the reason is available via the module-level ``last_error`` and a fuller
    operator-facing diagnosis via ``diagnose_connection_failure()``.
    """
    global last_error
    last_error = None

    result: dict = {"resolve": None, "error": None}
    worker = threading.Thread(target=_connect_worker, args=(result,), daemon=True)
    worker.start()
    worker.join(_CONNECT_TIMEOUT_S)

    if worker.is_alive():
        last_error = (
            "Connection attempt exceeded %ds and was abandoned "
            "(possible hang in the native scripting call)." % _CONNECT_TIMEOUT_S
        )
        return None

    if result["resolve"] is None:
        last_error = result["error"] or "Unknown connection failure."
        return None

    return result["resolve"]


def diagnose_connection_failure(
    attempts: list[dict] | None = None, error: str | None = None
) -> str:
    """Build a fail-fast, operator-actionable diagnosis for a None connect().

    Names the specific gate — interpreter cannot load the native lib vs. Resolve
    not running / external scripting disabled — per FR-014 and US1 scenario 3.
    """
    if attempts is None:
        attempts = interpreter_attempts()
    if error is None:
        error = last_error

    worker = working_interpreter(attempts)

    if worker is None:
        tried = "; ".join(
            "%s (%s): %s"
            % (a["path"], a.get("origin", "?"), a.get("failure_type") or "load failed")
            for a in attempts
        )
        return (
            "INTERPRETER GATE: no Python interpreter could load the native "
            "scripting library (fusionscript.so). The harness cannot talk to "
            "Resolve from any tried interpreter. Tried: %s. "
            "Verify RESOLVE_SCRIPT_LIB points at an existing fusionscript.so and "
            "that the interpreter architecture matches the library." % tried
        )

    # The native library loads, so the failure is at the live-connection layer.
    return (
        "CONNECTION GATE: the native library loaded in %s (%s), but "
        "scriptapp('Resolve') did not return a Resolve object. %s "
        "Checklist: (1) DaVinci Resolve is actually running; (2) Preferences > "
        "System > General > 'External scripting using' is set to Local/Network "
        "(disabled or free edition refuses external scripting); (3) re-run the "
        "doctor probe once Resolve is up."
        % (worker["path"], worker.get("version") or "?", error or "")
    )


# --------------------------------------------------------------------------- #
# CLI entry point (useful for the doctor probe)
# --------------------------------------------------------------------------- #


def _main() -> int:
    attempts = interpreter_attempts()
    resolve = connect()
    worker = working_interpreter(attempts)

    report = {
        "env_vars": resolve_env_vars(),
        "interpreter_attempts": attempts,
        "working_interpreter": worker,
        "connection": {
            "connected": resolve is not None,
            "last_error": last_error,
            "diagnosis": None if resolve is not None else diagnose_connection_failure(attempts),
        },
    }
    print(json.dumps(report, indent=2))
    # 0 if we connected, 1 otherwise — lets a shell caller gate on it without parsing.
    return 0 if resolve is not None else 1


if __name__ == "__main__":
    sys.exit(_main())
