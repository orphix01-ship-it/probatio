"""Execution of untrusted generated programs.

The program must print exactly one JSON document on stdout. It runs:
- in a separate process group, in a fresh temporary directory;
- with Python isolated mode (-I -S) and a scrubbed environment;
- under rlimits (CPU, address space, file size, processes, open files);
- with a wall-clock timeout that kills the whole process group;
- inside a new user+network namespace (``unshare -rn``) when available, so it
  has no network. Whether isolation was achieved is reported, never assumed.

The sandbox only produces candidate data; that data is then certified by a
checker like any other candidate.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX
    resource = None


@dataclass
class SandboxResult:
    ok: bool
    output: Any = None
    error: str = ""
    network_isolated: bool = False
    stderr_tail: str = ""


_NET_ISOLATION: bool | None = None


def network_isolation_available() -> bool:
    global _NET_ISOLATION
    if _NET_ISOLATION is None:
        exe = shutil.which("unshare")
        _NET_ISOLATION = False
        if exe:
            try:
                r = subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=5)
                _NET_ISOLATION = r.returncode == 0
            except Exception:
                _NET_ISOLATION = False
    return _NET_ISOLATION


def _limits(cpu_s: int, mem_mb: int):
    def apply():
        os.setsid()
        if resource is None:
            return
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        mem = mem_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except (ValueError, OSError):
            pass  # macOS does not support RLIMIT_AS reliably
        resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except (ValueError, OSError):
            pass
    return apply


# Defence-in-depth layer injected ahead of every program. Python audit hooks
# cannot be removed once installed. This is NOT a hard security boundary on its
# own (the OS-level layers and the docker backend are); it closes the easy
# paths: process spawning, sockets, native code, and writes outside the
# sandbox directory.
GUARD = r'''
import sys as _s, os as _o
_ROOT = _o.path.realpath(_o.getcwd())
_BLOCK = {"os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
          "subprocess.Popen", "socket.__new__", "socket.connect", "socket.bind",
          "socket.getaddrinfo", "ctypes.dlopen", "ctypes.dlsym", "ctypes.cdata",
          "os.kill", "os.killpg", "os.putenv", "os.unsetenv", "os.chdir", "pty.spawn",
          "webbrowser.open", "urllib.Request", "sys.setrecursionlimit"}
_PATH_EVENTS = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
                "os.symlink", "os.link", "os.truncate", "os.utime", "shutil.rmtree",
                "shutil.copyfile", "shutil.move"}
_NO_IMPORT = {"ctypes", "_ctypes", "subprocess", "socket", "_socket", "multiprocessing",
              "urllib.request", "http.client", "ssl", "_posixsubprocess", "pty"}
def _inside(p):
    try:
        p = _o.fsdecode(p) if not isinstance(p, int) else None
    except Exception:
        return False
    if p is None:
        return True
    return _o.path.realpath(_o.path.join(_ROOT, p)).startswith(_ROOT + _o.sep)
def _hook(ev, args):
    if ev in _BLOCK:
        raise PermissionError("probatio sandbox: " + ev + " blocked")
    if ev == "import" and args[0] in _NO_IMPORT:
        raise PermissionError("probatio sandbox: import of " + args[0] + " blocked")
    if ev == "open":
        path, mode, flags = (list(args) + [None, None, 0])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                  (isinstance(flags, int) and flags & (_o.O_WRONLY | _o.O_RDWR | _o.O_CREAT))
        if writing and not _inside(path):
            raise PermissionError("probatio sandbox: write outside sandbox blocked")
    if ev in _PATH_EVENTS and args and not _inside(args[0]):
        raise PermissionError("probatio sandbox: " + ev + " outside sandbox blocked")
_s.addaudithook(_hook)
del _hook
'''


def _docker_cmd(tmp: str, mem_mb: int, cpu_s: int) -> list[str] | None:
    exe = shutil.which("docker")
    if not exe:
        return None
    image = os.environ.get("PROBATIO_SANDBOX_IMAGE", "python:3.13-slim")
    return [exe, "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:size=16m",
            "--memory", f"{mem_mb}m", "--cpus", "1", "--pids-limit", "64", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "65534:65534",
            "-v", f"{tmp}:/w:ro", "-w", "/w", image, "python", "-I", "-S", "/w/candidate.py"]


def run_program(source: str, *, timeout_s: float = 10, cpu_s: int = 10, mem_mb: int = 512,
                max_output: int = 1_000_000, require_isolation: bool = False,
                guard: bool = True) -> SandboxResult:
    """Run ``source``; ``guard=False`` disables the audit-hook layer (tests only)."""
    backend = os.environ.get("PROBATIO_SANDBOX", "process")
    isolated = backend == "docker" or network_isolation_available()
    if require_isolation and not isolated:
        return SandboxResult(False, error="network isolation unavailable on this host")
    with tempfile.TemporaryDirectory(prefix="probatio-sbx-") as tmp:
        path = os.path.join(tmp, "candidate.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write((GUARD + "\n" if guard else "") + source)
        if backend == "docker":
            cmd = _docker_cmd(tmp, mem_mb, cpu_s)
            if cmd is None:
                return SandboxResult(False, error="PROBATIO_SANDBOX=docker but docker not found")
        else:
            cmd = [sys.executable, "-I", "-S", path]
            if isolated:
                cmd = [shutil.which("unshare"), "-rn"] + cmd
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        try:
            proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    preexec_fn=_limits(cpu_s, mem_mb))
        except OSError as exc:
            return SandboxResult(False, error=f"spawn failed: {exc}", network_isolated=isolated)
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            return SandboxResult(False, error="timeout", network_isolated=isolated)
    tail = err.decode("utf-8", "replace")[-2000:]
    if proc.returncode != 0:
        return SandboxResult(False, error=f"exit code {proc.returncode}",
                             network_isolated=isolated, stderr_tail=tail)
    if len(out) > max_output:
        return SandboxResult(False, error="output too large", network_isolated=isolated)
    try:
        data = json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return SandboxResult(False, error="stdout is not a single JSON document",
                             network_isolated=isolated, stderr_tail=tail)
    return SandboxResult(True, output=data, network_isolated=isolated, stderr_tail=tail)
