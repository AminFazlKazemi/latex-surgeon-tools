#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LaTeX Surgeon
================================

A conservative, transactional, self-healing LaTeX build system.

Design principles
-----------------
1. Universal: works with arbitrary .tex files/projects.
2. Root-cause first: secondary TeX errors are never repaired blindly.
3. Transactional: every source modification is backed up and verified.
4. Minimal-diff: repairs are local and deterministic whenever possible.
5. Font-aware: detects installed fonts and provides safe fallbacks.
6. Multi-engine: XeLaTeX / LuaLaTeX / pdfLaTeX.
7. Evidence-driven repair: a repair must be supported by compiler context.
8. Regression memory: successful repair patterns are stored locally.
9. Rollback: failed repairs are automatically reverted.
10. No destructive "cleanup" of source text.

Python 3.10+ / Windows, Linux and macOS oriented.
"""

from __future__ import annotations

import argparse
import ast
import threading
from datetime import datetime
import copy
import difflib
import dataclasses
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path
from typing import Optional, Iterable

try:
    from tqdm import tqdm as _tqdm
except Exception:
    _tqdm = None


# =============================================================================
# Configuration
# =============================================================================

APP_NAME = "LaTeX Surgeon"
VERSION = "19.0.0-FINAL"

DEFAULT_ENGINES = ("xelatex", "lualatex", "pdflatex")
DEFAULT_MAIN_FONTS = (
    "TeX Gyre Termes",
    "Latin Modern Roman",
    "STIX Two Text",
    "DejaVu Serif",
)
DEFAULT_SANS_FONTS = (
    "TeX Gyre Heros",
    "Latin Modern Sans",
    "DejaVu Sans",
)
DEFAULT_MONO_FONTS = (
    "TeX Gyre Cursor",
    "Latin Modern Mono",
    "DejaVu Sans Mono",
)
DEFAULT_PERSIAN_FONTS = (
    "Vazirmatn",
    "Vazir",
    "Noto Sans Arabic",
    "Noto Naskh Arabic",
)

AUTO_BLOCK_BEGIN = "% === LaTeX Surgeon AUTO-REPAIR METADATA BEGIN ==="
AUTO_BLOCK_END = "% === LaTeX Surgeon AUTO-REPAIR METADATA END ==="


# =============================================================================
# Data model
# =============================================================================

@dataclass
class Diagnostic:
    kind: str
    severity: str
    line: Optional[int]
    message: str
    evidence: str = ""
    confidence: float = 0.0
    secondary: bool = False


@dataclass
class RepairProposal:
    rule_id: str
    description: str
    confidence: float
    old_text: str
    new_text: str
    line: Optional[int] = None
    rationale: str = ""
    reversible: bool = True


@dataclass
class RepairResult:
    applied: bool
    proposal: Optional[RepairProposal] = None
    reason: str = ""


@dataclass
class BuildResult:
    success: bool
    engine: str
    returncode: int
    log: str
    pdf: Optional[Path] = None
    elapsed: float = 0.0


@dataclass
class ProjectInfo:
    root: Path
    tex: Path
    engine: str
    has_persian: bool = False
    has_bibliography: bool = False
    has_graphics: bool = False
    documentclass: Optional[str] = None


@dataclass
class CompilerConfig:
    max_rounds: int = 60
    timeout: int = 180
    min_repair_confidence: float = 0.93
    backup_dirname: str = ".latex_surgeon_backups"
    memory_filename: str = ".latex_surgeon_repair_memory.json"
    keep_build_files: bool = False
    auto_backup: bool = True
    learn: bool = True
    strict: bool = True
    engines: tuple[str, ...] = DEFAULT_ENGINES

# =============================================================================
# V15 MEGA — persistent error taxonomy / maximum-diagnostic supervision
# =============================================================================

V15_MAX_STAGES = 60
V15_MAX_DIAGNOSTICS_PER_PASS = 1000
V15_MAX_UNIQUE_NEW_TYPES_PER_RUN = 10000
V15_MAX_REPAIR_ATTEMPTS_PER_RUN = 500
V15_DIAGNOSTIC_LOG_MAX_CHARS = 2_000_000
V15_SIGNATURE_MAX_LEN = 1200

# Console policy: repeat occurrences are silent; only genuinely new signatures
# are announced. Full evidence remains on disk.
V15_QUIET_REPEAT_ERRORS = True
V15_KEEP_ALL_OCCURRENCES = True



# =============================================================================
# Console
# =============================================================================

def say(text: str = "", level: str = "info") -> None:
    prefixes = {
        "ok": "✅",
        "warn": "⚠️",
        "error": "❌",
        "info": "ℹ️",
        "fix": "🔧",
        "scan": "🔎",
        "font": "🔤",
        "build": "🏗️",
        "learn": "🧠",
        "rollback": "↩️",
    }
    print(f"{prefixes.get(level, '')} {text}")


# =============================================================================
# File utilities
# =============================================================================

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".latex_surgeon.tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# =============================================================================
# Hidden Python self-diagnostics / failure observability
# =============================================================================

_SELF_STATE = {
    "stage": None,
    "stage_name": None,
    "module": None,
    "event": "startup",
    "started": time.time(),
    "last_heartbeat": time.time(),
}
_SELF_LOCK = threading.RLock()


def _self_dir(project: Optional[ProjectInfo] = None) -> Optional[Path]:
    try:
        if project is not None:
            path = project.root / ".latex_surgeon_internal"
        else:
            path = Path.cwd() / ".latex_surgeon_internal"
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def self_heartbeat(project: Optional[ProjectInfo], event: str, **data) -> None:
    """Hidden machine-readable heartbeat. Never prints and never raises."""
    try:
        with _SELF_LOCK:
            _SELF_STATE.update({"event": event, "last_heartbeat": time.time(), **data})
            state = dict(_SELF_STATE)
        root = _self_dir(project)
        if root is None:
            return
        record = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
            **state,
        }
        with (root / "supervisor_heartbeat.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def self_exception_report(project: Optional[ProjectInfo], label: str, exc: BaseException, **data) -> None:
    """Hidden forensic report for Python/LaTeX Surgeon failures; user console stays clean."""
    try:
        root = _self_dir(project)
        if root is None:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        payload = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
            "label": label,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "state": dict(_SELF_STATE),
            "data": data,
        }
        vpath = root / f"python_failure_{stamp}.json"
        vpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (root / "python_failures.jsonl").open("a", encoding="utf-8").write(
            json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        )
    except Exception:
        pass


def self_preflight(project: Optional[ProjectInfo] = None) -> None:
    """Silent preflight: syntax-check this Python file and record the result."""
    try:
        source_file = Path(__file__).resolve()
        source = source_file.read_text(encoding="utf-8", errors="replace")
        ast.parse(source, filename=str(source_file))
        compile(source, str(source_file), "exec")
        root = _self_dir(project)
        if root is not None:
            (root / "self_health.json").write_text(json.dumps({
                "time": datetime.now().isoformat(timespec="seconds"),
                "python": sys.version,
                "platform": platform.platform(),
                "source": str(source_file),
                "syntax_ok": True,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        self_exception_report(project, "self_preflight", exc)


def self_run_watchdog(project: ProjectInfo, timeout: int = 300):
    """Daemon watchdog: records where the supervisor is alive/stalled.

    It never kills the process; it only leaves forensic evidence for the next
    development cycle. This is deliberately hidden from normal user output.
    """
    stop = threading.Event()
    def worker():
        try:
            while not stop.wait(5.0):
                with _SELF_LOCK:
                    age = time.time() - float(_SELF_STATE.get("last_heartbeat", time.time()))
                    state = dict(_SELF_STATE)
                if age >= timeout:
                    self_heartbeat(project, "watchdog_stall", stall_seconds=age, state=state)
                    # reset marker so a long-running legitimate operation does
                    # not flood the forensic log every 5 seconds.
                    with _SELF_LOCK:
                        _SELF_STATE["last_heartbeat"] = time.time()
        except Exception as exc:
            self_exception_report(project, "watchdog", exc)
    thread = threading.Thread(target=worker, name="LaTeX-Surgeon-SelfWatchdog", daemon=True)
    thread.start()
    return stop


# =============================================================================
# TeX lexical helpers
# =============================================================================

def strip_tex_comments(text: str) -> str:
    """
    Remove comments without treating escaped percent signs as comments.
    Preserves line count.
    """
    out = []
    for line in normalize_newlines(text).splitlines(True):
        result = []
        escaped = False
        for ch in line:
            if ch == "%" and not escaped:
                break
            result.append(ch)
            if ch == "\\":
                escaped = not escaped
            else:
                escaped = False
        if line.endswith("\n") and (not result or not result[-1].endswith("\n")):
            result.append("\n")
        out.append("".join(result))
    return "".join(out)


def line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def document_signature(text: str) -> tuple[int, int]:
    clean = strip_tex_comments(text)
    return (
        len(re.findall(r"\\begin\s*\{document\}", clean)),
        len(re.findall(r"\\end\s*\{document\}", clean)),
    )


def preamble_end(text: str) -> int:
    m = re.search(r"\\begin\s*\{document\}", strip_tex_comments(text))
    return m.start() if m else -1


def find_documentclass(text: str) -> Optional[str]:
    m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^{}]+)\}", strip_tex_comments(text))
    return m.group(1).strip() if m else None


def brace_balance(text: str) -> tuple[int, int]:
    clean = strip_tex_comments(text)
    opens = closes = 0
    escaped = False
    for ch in clean:
        if ch == "\\" and not escaped:
            escaped = True
            continue
        if ch == "{" and not escaped:
            opens += 1
        elif ch == "}" and not escaped:
            closes += 1
        escaped = False
    return opens, closes


def environment_stack(text: str) -> tuple[list[str], list[tuple[str, str, int]]]:
    clean = strip_tex_comments(text)
    rx = re.compile(r"\\(begin|end)\s*\{([^{}]+)\}")
    stack: list[str] = []
    mismatches: list[tuple[str, str, int]] = []

    for m in rx.finditer(clean):
        action, env = m.group(1), m.group(2).strip()
        ln = line_number(clean, m.start())
        if action == "begin":
            stack.append(env)
        elif stack and stack[-1] == env:
            stack.pop()
        elif stack:
            mismatches.append((stack[-1], env, ln))
        else:
            mismatches.append(("<none>", env, ln))
    return stack, mismatches


def is_probably_persian(text: str) -> bool:
    sample = strip_tex_comments(text)
    arabic = len(re.findall(r"[\u0600-\u06FF]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    return arabic >= 30 and arabic > latin * 0.03


# =============================================================================
# Font detection
# =============================================================================

def run_command(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return p.returncode, p.stdout
    except Exception as exc:
        return 999, str(exc)


# =============================================================================
# Silent TeX package recovery
# =============================================================================

_PACKAGE_INSTALL_CACHE: dict[str, str] = {}
_PACKAGE_INSTALL_LOCK = threading.RLock()


def _windows_tex_executables() -> list[Path]:
    """Find MiKTeX/TeX Live package-manager executables without noisy discovery."""
    candidates: list[Path] = []
    names = ("mpm.exe", "mpm", "tlmgr.bat", "tlmgr.exe", "tlmgr")
    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX",
        Path(os.environ.get("PROGRAMFILES", "")) / "MiKTeX",
        Path(os.environ.get("PROGRAMFILES", "")) / "MiKTeX 2.9",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "TeX Live",
        Path(os.environ.get("PROGRAMFILES", "")) / "texlive",
    ]
    for root in roots:
        if not str(root) or not root.exists():
            continue
        # Keep this deliberately shallow/cheap; common Windows layouts are covered.
        for rel in (Path("miktex") / "bin" / "x64", Path("miktex") / "bin", Path("bin") / "windows", Path("bin")):
            base = root / rel
            for name in names:
                p = base / name
                if p.exists():
                    candidates.append(p)
    return candidates


def _find_tex_package_managers() -> list[list[str]]:
    managers: list[list[str]] = []
    for exe in ("mpm", "tlmgr"):
        found = shutil.which(exe)
        if found:
            managers.append([found])
    for p in _windows_tex_executables():
        if p.name.lower().startswith("mpm"):
            managers.insert(0, [str(p)])
        elif p.name.lower().startswith("tlmgr"):
            managers.append([str(p)])
    # De-duplicate while preserving preference order (MiKTeX first, then TeX Live).
    out: list[list[str]] = []
    seen: set[str] = set()
    for cmd in managers:
        key = os.path.normcase(str(cmd[0]))
        if key not in seen:
            seen.add(key)
            out.append(cmd)
    return out


def tex_package_available(package: str) -> bool:
    """Ask kpsewhich whether the package file is now visible to TeX."""
    package = Path(package).name
    if not package.endswith(".sty"):
        package += ".sty"
    kp = shutil.which("kpsewhich")
    if not kp:
        return False
    rc, out = run_command([kp, package], timeout=20)
    return rc == 0 and bool(out.strip()) and "not found" not in out.lower()


def install_tex_package_silently(package: str, project: Optional[ProjectInfo] = None) -> tuple[bool, str]:
    """Install a missing TeX package silently, never asking the user.

    MiKTeX's mpm is preferred, then TeX Live's tlmgr. All command output is
    captured, not printed. A successful installation is verified with kpsewhich.
    """
    package = Path(str(package).strip()).name
    package = re.sub(r"\.sty$", "", package, flags=re.I)
    if not re.fullmatch(r"[A-Za-z0-9_.+@-]+", package):
        return False, "unsafe package name"

    with _PACKAGE_INSTALL_LOCK:
        cached = _PACKAGE_INSTALL_CACHE.get(package)
        if cached == "installed":
            return True, "cached installed"
        if cached == "failed":
            return False, "cached failure"

    if tex_package_available(package):
        with _PACKAGE_INSTALL_LOCK:
            _PACKAGE_INSTALL_CACHE[package] = "installed"
        return True, "already available"

    managers = _find_tex_package_managers()
    if not managers:
        with _PACKAGE_INSTALL_LOCK:
            _PACKAGE_INSTALL_CACHE[package] = "failed"
        return False, "no MiKTeX mpm or TeX Live tlmgr found"

    last_reason = "package manager failed"
    for base in managers:
        exe = Path(base[0]).name.lower()
        if exe.startswith("mpm"):
            commands = [base + [f"--install={package}"], base + ["--install", package]]
        else:
            commands = [base + ["install", package]]

        for cmd in commands:
            try:
                rc, out = run_command(cmd, timeout=180)
                if rc == 0:
                    # Give the distribution a quiet database refresh where available.
                    for helper in ("initexmf", "mktexlsr"):
                        h = shutil.which(helper)
                        if h:
                            run_command([h, "--update-fndb"] if helper == "initexmf" else [h], timeout=60)
                    if tex_package_available(package):
                        with _PACKAGE_INSTALL_LOCK:
                            _PACKAGE_INSTALL_CACHE[package] = "installed"
                        return True, f"installed via {exe}"
                last_reason = (out or "")[-300:].replace("\n", " ") or f"return code {rc}"
            except Exception as exc:
                last_reason = f"{type(exc).__name__}: {exc}"

    with _PACKAGE_INSTALL_LOCK:
        _PACKAGE_INSTALL_CACHE[package] = "failed"
    return False, last_reason









def extract_missing_package_names(log: str) -> list[str]:
    found: list[str] = []
    patterns = (
        r"File `([^`]+)\.sty' not found",
        r"File `([^`]+)\.lbx' not found",
        r"LaTeX Error:\s*File `([^`]+)(?:\.sty)?' not found",
        r"I can't find file `([^`]+)(?:\.sty)?'",
        r"Package biblatex Warning: File '([^']+)\.lbx' not found",
    )
    for pattern in patterns:
        for m in re.finditer(pattern, log or "", re.I):
            name = Path(m.group(1)).name
            name = re.sub(r"\.(sty|lbx)$", "", name, flags=re.I)
            if name not in found and re.fullmatch(r"[A-Za-z0-9_.+@-]+", name):
                found.append(name)
    return found

def recover_missing_packages_from_log(project: ProjectInfo, log: str) -> tuple[int, list[str]]:
    """Install every package explicitly reported missing by the compiler.

    This happens BEFORE source-level package repairs. If a package can simply be
    installed, the source is left untouched and the compiler is retried.
    """
    installed = 0
    failed: list[str] = []
    for package in extract_missing_package_names(log):
        ok, reason = install_tex_package_silently(package, project)
        if ok:
            installed += 1
        else:
            failed.append(package)
            v9_journal(project, "package_recovery_failed", package=package, reason=reason)
    if installed:
        v9_journal(project, "packages_recovered", count=installed, packages=extract_missing_package_names(log))
    return installed, failed


def font_exists(font_name: str) -> bool:
    # fontconfig
    if shutil.which("fc-match"):
        rc, out = run_command(["fc-match", font_name], timeout=10)
        if rc == 0 and out.strip():
            first = out.strip().splitlines()[0]
            if "not found" not in first.lower():
                return True

    # Windows registry / PowerShell fallback
    if os.name == "nt":
        try:
            import winreg
            keys = [
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Fonts",
            ]
            target = font_name.lower()
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for key_name in keys:
                    try:
                        with winreg.OpenKey(root, key_name) as key:
                            for i in range(winreg.QueryInfoKey(key)[1]):
                                name, value, _ = winreg.EnumValue(key, i)
                                if target in name.lower():
                                    return True
                    except OSError:
                        pass
        except Exception:
            pass

    # TeX font database fallback
    if shutil.which("fc-list"):
        rc, out = run_command(["fc-list", ":", "family"], timeout=10)
        if rc == 0 and font_name.lower() in out.lower():
            return True

    return False


def choose_font(candidates: Iterable[str]) -> tuple[str, bool]:
    for name in candidates:
        if font_exists(name):
            return name, True
    first = tuple(candidates)[0]
    return first, False


def detect_fonts() -> dict[str, tuple[str, bool]]:
    main = choose_font(DEFAULT_MAIN_FONTS)
    sans = choose_font(DEFAULT_SANS_FONTS)
    mono = choose_font(DEFAULT_MONO_FONTS)
    persian = choose_font(DEFAULT_PERSIAN_FONTS)
    return {
        "main": main,
        "sans": sans,
        "mono": mono,
        "persian": persian,
    }


# =============================================================================
# Engine detection
# =============================================================================

def executable_exists(name: str) -> bool:
    return shutil.which(name) is not None


def select_engine(text: str, preferred: Optional[str], engines: tuple[str, ...]) -> Optional[str]:
    if preferred and executable_exists(preferred):
        return preferred

    clean = strip_tex_comments(text)

    if re.search(
        r"\\usepackage(?:\[[^\]]*\])?\{(?:fontspec|polyglossia|xepersian)\}",
        clean,
        re.I,
    ):
        for e in ("xelatex", "lualatex"):
            if executable_exists(e):
                return e

    if re.search(r"[\u0600-\u06FF]", clean):
        for e in ("xelatex", "lualatex"):
            if executable_exists(e):
                return e

    for e in engines:
        if executable_exists(e):
            return e

    return None


# =============================================================================
# Project discovery
# =============================================================================

def discover_main_tex(path: Path) -> Path:
    if path.is_file():
        return path

    candidates = sorted(path.glob("*.tex"))
    if not candidates:
        raise FileNotFoundError(f"No .tex file found in {path}")

    scored = []
    for p in candidates:
        text = read_text(p)
        score = 0
        if re.search(r"\\documentclass", text):
            score += 100
        if re.search(r"\\begin\s*\{document\}", text):
            score += 100
        if p.name.lower() in {"main.tex", "paper.tex", "article.tex"}:
            score += 20
        scored.append((score, p))

    return max(scored, key=lambda x: x[0])[1]


def make_project(tex: Path, preferred_engine: Optional[str], cfg: CompilerConfig) -> ProjectInfo:
    text = read_text(tex)
    engine = select_engine(text, preferred_engine, cfg.engines)
    if not engine:
        raise RuntimeError(
            "No usable LaTeX engine found. Install XeLaTeX, LuaLaTeX or pdfLaTeX."
        )

    return ProjectInfo(
        root=tex.parent,
        tex=tex,
        engine=engine,
        has_persian=is_probably_persian(text),
        has_bibliography=bool(re.search(r"\\(?:cite|parencite|textcite)\b", text)),
        has_graphics=bool(re.search(r"\\includegraphics\b", text)),
        documentclass=find_documentclass(text),
    )


# =============================================================================
# Build
# =============================================================================

def cleanup_aux(root: Path, stem: str) -> None:
    for ext in (
        ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls",
        ".fdb_latexmk", ".synctex.gz", ".bcf", ".run.xml",
        ".bbl", ".blg", ".nav", ".snm", ".vrb",
    ):
        p = root / f"{stem}{ext}"
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def compile_once(project: ProjectInfo, cfg: CompilerConfig) -> BuildResult:
    """
    Crash-resistant compiler invocation.

    Policy:
      * Never use -halt-on-error: collect as much diagnostic information as the
        TeX engine can produce in one pass.
      * Never allow a subprocess/OS/encoding exception to crash LaTeX Surgeon.
      * Return a BuildResult for every execution path.
    """
    start = time.perf_counter()
    cmd = [
        project.engine,
        "-interaction=nonstopmode",
        "-file-line-error",
        "-synctex=1",
        project.tex.name,
    ]

    try:
        p = subprocess.run(
            cmd,
            cwd=project.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout,
            shell=False,
        )
        log = p.stdout or ""
        pdf = project.tex.with_suffix(".pdf")
        success = p.returncode == 0 and pdf.exists()
        return BuildResult(
            success=success,
            engine=project.engine,
            returncode=p.returncode,
            log=log,
            pdf=pdf if pdf.exists() else None,
            elapsed=time.perf_counter() - start,
        )

    except subprocess.TimeoutExpired as exc:
        output = getattr(exc, "stdout", "") or getattr(exc, "output", "") or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return BuildResult(
            success=False,
            engine=project.engine,
            returncode=124,
            log=f"SHERAI_TIMEOUT: compiler exceeded {cfg.timeout}s\n{output}",
            elapsed=time.perf_counter() - start,
        )

    except FileNotFoundError as exc:
        return BuildResult(
            success=False,
            engine=project.engine,
            returncode=127,
            log=f"SHERAI_ENGINE_NOT_FOUND: {exc}",
            elapsed=time.perf_counter() - start,
        )

    except OSError as exc:
        return BuildResult(
            success=False,
            engine=project.engine,
            returncode=126,
            log=f"SHERAI_OS_ERROR: {type(exc).__name__}: {exc}",
            elapsed=time.perf_counter() - start,
        )

    except Exception as exc:
        # The compiler itself is untrusted from the supervisor's perspective.
        return BuildResult(
            success=False,
            engine=project.engine,
            returncode=125,
            log=(
                f"SHERAI_INTERNAL_COMPILE_EXCEPTION: "
                f"{type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            ),
            elapsed=time.perf_counter() - start,
        )


# =============================================================================
# Diagnostics: root-cause aware
# =============================================================================

ERROR_PATTERNS = [
    ("font_missing", re.compile(r'The font "([^"]+)" cannot be found', re.I)),
    ("font_missing", re.compile(r"font .*? cannot be found", re.I)),
    ("missing_package", re.compile(r"File `([^`]+)\.sty' not found", re.I)),
    ("undefined_command", re.compile(r"Undefined control sequence", re.I)),
    ("undefined_environment", re.compile(r"Environment\s+([^\s]+)\s+undefined", re.I)),
    ("missing_begin_document", re.compile(r"Missing \\begin\{document\}", re.I)),
    ("missing_brace", re.compile(r"Missing \} inserted", re.I)),
    ("extra_brace", re.compile(r"Extra },", re.I)),
    ("file_ended_scanning", re.compile(r"File ended while scanning", re.I)),
    ("emergency_stop", re.compile(r"Emergency stop", re.I)),
    ("option_clash", re.compile(r"Option clash for package", re.I)),
    ("undefined_reference", re.compile(r"There were undefined references", re.I)),
    ("undefined_citation", re.compile(r"There were undefined citations", re.I)),
    ("overfull", re.compile(r"Overfull \\[hv]box", re.I)),
    ("inputenc", re.compile(r"inputenc Error", re.I)),
    ("unicode_error", re.compile(r"Unicode character .*? not set up", re.I)),
    ("package_error", re.compile(r"! Package .*? Error:", re.I)),
    ("latex_error", re.compile(r"! LaTeX Error:", re.I)),
    ("fatal", re.compile(r"Fatal error occurred", re.I)),
]


def extract_error_line(line: str) -> Optional[int]:
    m = re.search(r":(\d+):", line)
    return int(m.group(1)) if m else None


def diagnostics_from_log(project: ProjectInfo, log: str) -> list[Diagnostic]:
    lines = log.splitlines()
    diagnostics: list[Diagnostic] = []

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        ln = extract_error_line(line)
        low = line.lower()

        for kind, rx in ERROR_PATTERNS:
            if rx.search(line):
                secondary = kind in {
                    "missing_begin_document",
                    "emergency_stop",
                    "fatal",
                    "undefined_reference",
                    "undefined_citation",
                    "overfull",
                }
                conf = 0.95
                if secondary:
                    conf = 0.55
                diagnostics.append(
                    Diagnostic(
                        kind=kind,
                        severity="error" if not secondary else "secondary",
                        line=ln,
                        message=line,
                        evidence="\n".join(lines[max(0, i-2):min(len(lines), i+3)]),
                        confidence=conf,
                        secondary=secondary,
                    )
                )
                break

    # Structural diagnostics are independently computed from the source.
    source = read_text(project.tex)
    opens, closes = brace_balance(source)
    if opens != closes:
        diagnostics.append(
            Diagnostic(
                kind="structural_brace_imbalance",
                severity="error",
                line=None,
                message=f"Brace imbalance: opens={opens}, closes={closes}",
                confidence=0.99,
            )
        )

    stack, mismatches = environment_stack(source)
    if mismatches:
        diagnostics.append(
            Diagnostic(
                kind="structural_environment_mismatch",
                severity="error",
                line=mismatches[0][2],
                message=f"Environment mismatch: {mismatches[0][0]} -> {mismatches[0][1]}",
                confidence=0.99,
            )
        )
    elif len(stack) > 1 or (len(stack) == 1 and stack[0] != "document"):
        diagnostics.append(
            Diagnostic(
                kind="structural_unclosed_environment",
                severity="error",
                line=None,
                message=f"Unclosed environment stack: {stack}",
                confidence=0.98,
            )
        )

    sig = document_signature(source)
    if sig != (1, 1):
        diagnostics.append(
            Diagnostic(
                kind="structural_document_boundary",
                severity="error",
                line=None,
                message=f"Document boundary signature is {sig}, expected (1, 1).",
                confidence=1.0,
            )
        )

    return deduplicate_diagnostics(diagnostics)


def deduplicate_diagnostics(items: list[Diagnostic]) -> list[Diagnostic]:
    seen = set()
    out = []
    for d in items:
        key = (d.kind, d.line, d.message[:160])
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# =============================================================================
# Root-cause analysis
# =============================================================================

def context_window(text: str, line: int, radius: int = 5) -> str:
    lines = text.splitlines()
    a = max(0, line - 1 - radius)
    b = min(len(lines), line - 1 + radius + 1)
    return "\n".join(
        f"{i+1:5d} | {lines[i]}" for i in range(a, b)
    )


def detect_root_cause(project: ProjectInfo, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """
    Rank primary causes. A secondary TeX error such as
    'Missing \\begin{document}' is not itself a repair target when a stronger
    upstream structural/font/package cause exists.
    """
    source = read_text(project.tex)

    structural = [
        d for d in diagnostics
        if d.kind.startswith("structural_")
    ]
    strong = [
        d for d in diagnostics
        if d.kind in {
            "font_missing", "missing_package", "undefined_command",
            "undefined_environment", "option_clash", "missing_brace",
            "extra_brace", "file_ended_scanning", "package_error",
            "latex_error", "unicode_error", "inputenc",
        }
    ]

    if structural or strong:
        for d in diagnostics:
            if d.kind == "missing_begin_document":
                d.secondary = True
                d.confidence = 0.25
                d.evidence += "\nROOT-CAUSE POLICY: treated as secondary."

    # Add source context to diagnostics with a line number.
    for d in diagnostics:
        if d.line and 1 <= d.line <= len(source.splitlines()):
            d.evidence += "\nSOURCE CONTEXT:\n" + context_window(source, d.line)

    return sorted(
        diagnostics,
        key=lambda d: (
            d.secondary,
            -d.confidence,
            d.line if d.line is not None else 10**9,
        ),
    )


# =============================================================================
# Conservative repair rules
# =============================================================================

KNOWN_COMMAND_PACKAGES = {
    "toprule": "booktabs",
    "midrule": "booktabs",
    "bottomrule": "booktabs",
    "includegraphics": "graphicx",
    "rowcolor": "xcolor",
    "cellcolor": "xcolor",
    "FloatBarrier": "placeins",
    "href": "hyperref",
    "url": "url",
    "SI": "siunitx",
    "qty": "siunitx",
    "num": "siunitx",
    "ce": "mhchem",
}

KNOWN_ENV_PACKAGES = {
    "align": "amsmath",
    "align*": "amsmath",
    "gather": "amsmath",
    "gather*": "amsmath",
    "equation": "amsmath",
    "split": "amsmath",
    "multline": "amsmath",
    "matrix": "amsmath",
    "pmatrix": "amsmath",
    "cases": "amsmath",
    "tabularx": "tabularx",
    "longtable": "longtable",
}

SAFE_FONT_REPLACEMENTS = {
    "Courier New": "TeX Gyre Cursor",
    "Times New Roman": "TeX Gyre Termes",
    "Arial": "TeX Gyre Heros",
}


def package_loaded(text: str, package: str) -> bool:
    return bool(re.search(
        rf"\\usepackage(?:\[[^\]]*\])?\{{{re.escape(package)}\}}",
        text,
        re.I,
    ))


def add_package_once(text: str, package: str) -> Optional[str]:
    if package_loaded(text, package):
        return None
    pos = preamble_end(text)
    if pos < 0:
        return None
    addition = f"\\usepackage{{{package}}}\n"
    return text[:pos] + addition + text[pos:]


def extract_missing_font(log: str) -> Optional[str]:
    m = re.search(r'The font "([^"]+)" cannot be found', log, re.I)
    return m.group(1).strip() if m else None


def extract_undefined_command(log: str) -> Optional[str]:
    m = re.search(
        r"Undefined control sequence.*?\\([A-Za-z@]+)",
        log,
        re.I | re.S,
    )
    return m.group(1) if m else None


def extract_undefined_environment(log: str) -> Optional[str]:
    m = re.search(
        r"Environment\s+([A-Za-z0-9*_-]+)\s+undefined",
        log,
        re.I,
    )
    return m.group(1) if m else None


def propose_font_repair(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    missing = extract_missing_font(log)
    if not missing:
        return None

    replacement = SAFE_FONT_REPLACEMENTS.get(missing)
    if not replacement or not font_exists(replacement):
        return None

    source = read_text(project.tex)

    # Exact font-name replacement only in font declarations. Never globally
    # replace prose or arbitrary text.
    patterns = [
        rf"(\\setmainfont(?:\[[^\]]*\])?\{{){re.escape(missing)}(\}})",
        rf"(\\setsansfont(?:\[[^\]]*\])?\{{){re.escape(missing)}(\}})",
        rf"(\\setmonofont(?:\[[^\]]*\])?\{{){re.escape(missing)}(\}})",
        r"(\\newfontfamily(?:\\[[^\\]]*\\])?\\{[^{}]+\\}\\s*\\{"
        + re.escape(missing)
        + r"(\\})",
    ]

    for pattern in patterns:
        m = re.search(pattern, source)
        if m:
            old = m.group(0)
            new = m.group(1) + replacement + m.group(2)
            return RepairProposal(
                rule_id="FONT_DECLARATION_FALLBACK",
                description=f"Replace unavailable font '{missing}' with installed '{replacement}'",
                confidence=0.995,
                old_text=old,
                new_text=new,
                line=line_number(source, m.start()),
                rationale="Compiler explicitly reported the font as missing and the replacement is installed.",
            )

    return None


def propose_dependency_repair(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    cmd = extract_undefined_command(log)
    source = read_text(project.tex)

    if cmd in KNOWN_COMMAND_PACKAGES:
        pkg = KNOWN_COMMAND_PACKAGES[cmd]
        new = add_package_once(source, pkg)
        if new:
            return RepairProposal(
                rule_id="MISSING_KNOWN_PACKAGE",
                description=f"Add package '{pkg}' for \\{cmd}",
                confidence=0.985,
                old_text=source,
                new_text=new,
                rationale=f"\\{cmd} has an unambiguous standard package dependency.",
            )

    env = extract_undefined_environment(log)
    if env in KNOWN_ENV_PACKAGES:
        pkg = KNOWN_ENV_PACKAGES[env]
        new = add_package_once(source, pkg)
        if new:
            return RepairProposal(
                rule_id="MISSING_KNOWN_ENV_PACKAGE",
                description=f"Add package '{pkg}' for environment '{env}'",
                confidence=0.985,
                old_text=source,
                new_text=new,
                rationale=f"Environment '{env}' has an unambiguous standard package dependency.",
            )

    return None


def propose_eof_environment_repair(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    source = read_text(project.tex)
    stack, mismatches = environment_stack(source)

    if mismatches or len(stack) != 1:
        return None

    env = stack[0]
    if env == "document":
        return None

    if env in {"verbatim", "Verbatim", "lstlisting", "minted"}:
        return None

    if not any(x in log.lower() for x in (
        "file ended while scanning",
        "missing \\end",
        "emergency stop",
        "runaway argument",
    )):
        return None

    old = source
    new = source.rstrip() + f"\n\\end{{{env}}}\n"

    return RepairProposal(
        rule_id="CLOSE_EOF_ENVIRONMENT",
        description=f"Close unclosed environment '{env}' at EOF",
        confidence=0.99,
        old_text=old,
        new_text=new,
        rationale="Only one environment remains open and the compiler indicates an EOF/runaway-argument failure.",
    )


def propose_eof_brace_repair(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    source = read_text(project.tex)
    opens, closes = brace_balance(source)

    if not any(x in log.lower() for x in (
        "missing } inserted",
        "file ended while scanning",
        "runaway argument",
        "emergency stop",
    )):
        return None

    if opens - closes == 1:
        return RepairProposal(
            rule_id="CLOSE_EOF_BRACE",
            description="Add one missing closing brace at EOF",
            confidence=0.975,
            old_text=source,
            new_text=source.rstrip() + "\n}\n",
            rationale="Exactly one unmatched opening brace remains and compiler context indicates a runaway/missing-brace failure.",
        )

    if closes - opens == 1:
        m = re.search(r"\n\s*}\s*\Z", source)
        if m:
            new = source[:m.start()] + "\n"
            if brace_balance(new)[0] == brace_balance(new)[1]:
                return RepairProposal(
                    rule_id="REMOVE_EOF_BRACE",
                    description="Remove one extra standalone closing brace at EOF",
                    confidence=0.975,
                    old_text=source,
                    new_text=new,
                    rationale="Exactly one extra standalone EOF brace is present.",
                )

    return None


def propose_duplicate_package_repair(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    if "option clash for package" not in log.lower():
        return None

    source = read_text(project.tex)
    pos = preamble_end(source)
    if pos < 0:
        return None

    pre = source[:pos]
    body = source[pos:]

    # Only identical, optionless declarations.
    rx = re.compile(r"^\s*\\usepackage\{([A-Za-z0-9_.-]+)\}\s*$", re.I)
    seen = set()
    lines = []
    duplicates = 0

    for line in pre.splitlines(True):
        m = rx.match(line)
        if not m:
            lines.append(line)
            continue
        pkg = m.group(1).lower()
        if pkg in seen:
            duplicates += 1
            continue
        seen.add(pkg)
        lines.append(line)

    if duplicates != 1:
        return None

    new = "".join(lines) + body
    return RepairProposal(
        rule_id="REMOVE_EXACT_DUPLICATE_PACKAGE",
        description="Remove one exact duplicate optionless package declaration",
        confidence=0.965,
        old_text=source,
        new_text=new,
        rationale="Only an exact duplicate package declaration is removed; option-bearing declarations are untouched.",
    )


# =============================================================================
# Transactional verifier
# =============================================================================

def semantic_fingerprint(text: str) -> dict[str, int]:
    """Conservative document-shape fingerprint used after every surgery.

    It deliberately ignores package declarations because package repairs are
    expected to change those, but protects document content topology from an
    accidental broad rewrite.
    """
    clean = strip_tex_comments(text)
    patterns = {
        "sections": r"\\(?:part|chapter|section|subsection|subsubsection)\\*?\s*\{",
        "figures": r"\\(?:includegraphics|includegraphics\*)",
        "tables": r"\\begin\s*\{(?:table|table\*|tabular|tabularx|longtable)\}",
        "citations": r"\\(?:cite|parencite|textcite|autocite|citep|citet)\b",
        "inputs": r"\\(?:input|include)\s*\{",
        "labels": r"\\label\s*\{",
        "references": r"\\(?:ref|pageref|autoref|cref)\s*\{",
    }
    return {k: len(re.findall(v, clean, re.I)) for k, v in patterns.items()}


def semantic_preservation_check(before: str, after: str) -> tuple[bool, str]:
    b = semantic_fingerprint(before)
    a = semantic_fingerprint(after)
    # A repair must not silently delete document-level semantic units.
    for key, old_count in b.items():
        if old_count > 0 and a.get(key, 0) < old_count:
            return False, f"semantic unit count decreased: {key} {old_count}->{a.get(key, 0)}"
    return True, "ok"


def source_safety_check(before: str, after: str) -> tuple[bool, str]:
    if document_signature(after) != (1, 1):
        return False, "document boundary changed"

    # A repair must not unexpectedly remove the document body.
    b = strip_tex_comments(before)
    a = strip_tex_comments(after)
    bdoc = re.search(r"\\begin\s*\{document\}", b)
    adoc = re.search(r"\\begin\s*\{document\}", a)
    if not bdoc or not adoc:
        return False, "document body boundary missing"

    if len(a) < max(1, int(len(b) * 0.75)):
        return False, "candidate removed more than 25% of source"

    semantic_ok, semantic_reason = semantic_preservation_check(before, after)
    if not semantic_ok:
        return False, semantic_reason

    return True, "ok"


def backup_file(path: Path, backup_root: Path) -> Path:
    """Create collision-proof immutable source backup before every mutation."""
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    try:
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except Exception:
        content_digest = "unknown"
    target = backup_root / f"{path.stem}_{stamp}_{content_digest}{path.suffix}.bak"
    shutil.copy2(path, target)
    return target


def create_run_snapshot(project: ProjectInfo, cfg: CompilerConfig, label: str = "run_start") -> Optional[Path]:
    """Keep a golden source snapshot for the entire run."""
    if not cfg.auto_backup:
        return None
    try:
        root = project.root / cfg.backup_dirname / "golden"
        return backup_file(project.tex, root)
    except Exception as exc:
        self_exception_report(project, "golden_backup", exc, label=label)
        return None


def apply_proposal(project: ProjectInfo, proposal: RepairProposal, cfg: CompilerConfig) -> RepairResult:
    current = read_text(project.tex)

    if current != proposal.old_text:
        return RepairResult(False, proposal, "source changed since proposal")

    safe, reason = source_safety_check(current, proposal.new_text)
    if not safe:
        return RepairResult(False, proposal, reason)

    backup = None
    if cfg.auto_backup:
        backup = backup_file(
            project.tex,
            project.root / cfg.backup_dirname,
        )

    write_text(project.tex, proposal.new_text)

    # Verify the exact expected source state after write.
    if read_text(project.tex) != proposal.new_text:
        if backup:
            shutil.copy2(backup, project.tex)
        return RepairResult(False, proposal, "write verification failed")

    return RepairResult(True, proposal, "applied")


def rollback(project: ProjectInfo, backup: Optional[Path]) -> None:
    if backup and backup.exists():
        shutil.copy2(backup, project.tex)
        say(f"Rollback complete: {project.tex.name}", "rollback")


# =============================================================================
# Learning memory
# =============================================================================

def memory_path(project: ProjectInfo, cfg: CompilerConfig) -> Path:
    return project.root / cfg.memory_filename


def load_memory(project: ProjectInfo, cfg: CompilerConfig) -> dict:
    path = memory_path(project, cfg)
    if not path.exists():
        return {"version": 1, "rules": {}}
    try:
        return json.loads(read_text(path))
    except Exception:
        return {"version": 1, "rules": {}}


def save_memory(project: ProjectInfo, cfg: CompilerConfig, memory: dict) -> None:
    if not cfg.learn:
        return
    write_text(memory_path(project, cfg), json.dumps(
        memory, ensure_ascii=False, indent=2
    ))


def learn_success(project: ProjectInfo, cfg: CompilerConfig, proposal: RepairProposal) -> None:
    if not cfg.learn:
        return

    memory = load_memory(project, cfg)
    # Learning must be side-effect free: do not create a second golden backup
    # or spawn another watchdog every time a repair succeeds. The supervisor
    # owns those lifecycle resources.
    rules = memory.setdefault("rules", {})
    item = rules.setdefault(proposal.rule_id, {
        "successes": 0,
        "failures": 0,
        "last_description": proposal.description,
    })
    item["successes"] += 1
    item["last_description"] = proposal.description
    item["last_success"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_memory(project, cfg, memory)
    say(f"Learned successful rule: {proposal.rule_id}", "learn")


def learn_failure(project: ProjectInfo, cfg: CompilerConfig, proposal: RepairProposal) -> None:
    if not cfg.learn:
        return

    memory = load_memory(project, cfg)
    rules = memory.setdefault("rules", {})
    item = rules.setdefault(proposal.rule_id, {
        "successes": 0,
        "failures": 0,
        "last_description": proposal.description,
    })
    item["failures"] += 1
    item["last_failure"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_memory(project, cfg, memory)


# =============================================================================
# Repair planner
# =============================================================================


def propose_missing_document_boundary(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    source = read_text(project.tex)
    begins, ends = document_signature(source)
    if begins == 1 and ends == 1:
        return None
    new_source = source
    if begins == 0:
        pos = preamble_end(source)
        if pos < 0:
            m = re.search(r"\\documentclass(?:\\[[^\\]]*\\])?\\{[^}]+\\}", source)
            if m:
                pos = m.end()
            else:
                pos = 0
        if pos >= 0:
            new_source = new_source[:pos] + "\\n\\begin{document}\\n" + new_source[pos:]
            begins += 1
    if ends == 0:
        new_source = new_source.rstrip() + "\\n\\end{document}\\n"
        ends += 1
    if new_source == source:
        return None
    safe, reason = source_safety_check(source, new_source)
    if not safe:
        return None
    return RepairProposal(
        rule_id="ADD_MISSING_DOCUMENT_BOUNDARY",
        description="Insert missing \\begin{document} and/or \\end{document}",
        confidence=0.99,
        old_text=source,
        new_text=new_source,
        rationale="Compiler reported missing document boundary; inserting it is safe and necessary."
    )



def propose_csquotes_persian_fix(project: ProjectInfo) -> Optional[RepairProposal]:
    source = read_text(project.tex)
    if not re.search(r"\\usepackage(?:\\[[^\\]]*\\])?\\{csquotes\\}", source, re.I):
        return None
    if not project.has_persian:
        return None
    # اگر polyglossia وجود نداشت، آن را اضافه کن
    if not re.search(r"\\usepackage(?:\\[[^\\]]*\\])?\\{polyglossia\\}", source, re.I):
        new_source = add_package_once(source, "polyglossia")
        if new_source:
            # اضافه کردن setmainlanguage{persian}
            pos = new_source.find("\\usepackage{polyglossia}") + len("\\usepackage{polyglossia}")
            new_source = new_source[:pos] + "\\n\\setmainlanguage{persian}\\n" + new_source[pos:]
            if source_safety_check(source, new_source)[0]:
                return RepairProposal(
                    rule_id="ADD_POLYGLOSSIA_PERSIAN",
                    description="Add polyglossia with Persian language for csquotes",
                    confidence=0.95,
                    old_text=source,
                    new_text=new_source,
                    rationale="csquotes needs language support; adding polyglossia fixes it."
                )
    return None


def propose_repairs(
    project: ProjectInfo,
    diagnostics: list[Diagnostic],
    log: str,
) -> list[RepairProposal]:
    """
    Order is intentional:
      1. hard structural/root causes
      2. missing dependencies
      3. font declarations
      4. EOF repairs
      5. duplicate packages

    'Missing \\begin{document}' is deliberately absent as a direct repair rule.
    """
    proposals: list[RepairProposal] = []

    if any(d.kind in {"font_missing"} for d in diagnostics):
        p = propose_font_repair(project, log)
        if p:
            proposals.append(p)

    if any(d.kind in {"missing_package", "undefined_command", "undefined_environment"} for d in diagnostics):
        p = propose_dependency_repair(project, log)
        if p:
            proposals.append(p)

    if any(d.kind in {
        "structural_unclosed_environment",
        "file_ended_scanning",
        "emergency_stop",
    } for d in diagnostics):
        p = propose_eof_environment_repair(project, log)
        if p:
            proposals.append(p)

    if any(d.kind in {
        "structural_brace_imbalance",
        "missing_brace",
        "file_ended_scanning",
        "emergency_stop",
    } for d in diagnostics):
        p = propose_eof_brace_repair(project, log)
        if p:
            proposals.append(p)

    p = propose_duplicate_package_repair(project, log)
    if p:
        proposals.append(p)

    # Highest confidence first; never use secondary diagnostics as primary
    # repair triggers.
    proposals.sort(key=lambda p: -p.confidence)
    return proposals


# =============================================================================
# Build controller
# =============================================================================

def build_until_clean(
    project: ProjectInfo,
    cfg: CompilerConfig,
) -> bool:
    say(f"Project: {project.tex.name}", "build")
    say(f"Engine: {project.engine}")
    say(f"Persian detected: {project.has_persian}")

    memory = load_memory(project, cfg)

    for round_no in range(1, cfg.max_rounds + 1):
        print()
        say(f"Round {round_no}/{cfg.max_rounds}", "build")

        result = compile_once(project, cfg)

        if result.success:
            say(
                f"BUILD CLEAN — {project.tex.name} "
                f"({result.elapsed:.2f}s)",
                "ok",
            )
            return True

        diagnostics = diagnostics_from_log(project, result.log)
        diagnostics = detect_root_cause(project, diagnostics)

        if not diagnostics:
            say("Compiler failed but no recognized diagnostic was extracted.", "error")
            save_log(project, result.log)
            return False

        print("Root-cause diagnostics:")
        for d in diagnostics[:8]:
            tag = "SECONDARY" if d.secondary else "PRIMARY"
            print(
                f"  • [{tag}] {d.kind} "
                f"@ {d.line or '?'} "
                f"(confidence={d.confidence:.2f})"
            )
            print(f"    {d.message[:220]}")

        # If there is a secondary-only failure, don't invent a repair.
        primary = [d for d in diagnostics if not d.secondary]
        if not primary:
            say(
                "Only secondary diagnostics remain; no blind repair will be attempted.",
                "warn",
            )
            save_log(project, result.log)
            return False

        proposals = propose_repairs(project, primary, result.log)

        if not proposals:
            say(
                "No high-confidence repair exists for the detected root cause.",
                "warn",
            )
            save_log(project, result.log)
            return False

        applied = False

        for proposal in proposals:
            if proposal.confidence < cfg.min_repair_confidence:
                continue

            say(
                f"{proposal.description} "
                f"[confidence={proposal.confidence:.3f}]",
                "fix",
            )
            if proposal.rationale:
                print(f"    rationale: {proposal.rationale}")

            before_hash = sha256_text(read_text(project.tex))
            rr = apply_proposal(project, proposal, cfg)

            if not rr.applied:
                learn_failure(project, cfg, proposal)
                say(f"Repair rejected: {rr.reason}", "warn")
                continue

            # Compile immediately to validate the repair.
            verify = compile_once(project, cfg)

            if verify.success:
                learn_success(project, cfg, proposal)
                say("Repair verified by successful compilation.", "ok")
                applied = True
                break

            # Failed repair => restore exact source.
            backup_candidates = sorted(
                (project.root / cfg.backup_dirname).glob(
                    f"{project.tex.stem}_*{project.tex.suffix}.bak"
                ),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            backup = backup_candidates[0] if backup_candidates else None
            rollback(project, backup)
            learn_failure(project, cfg, proposal)

            # Save the failed log, but continue to the next independent proposal.
            save_log(project, verify.log, suffix=f"failed_{proposal.rule_id}")

        if not applied:
            say(
                "No proposed repair survived compile-time verification.",
                "error",
            )
            save_log(project, result.log)
            return False

    say("Maximum repair rounds reached.", "error")
    return False


# =============================================================================
# Logs and reporting
# =============================================================================

def save_log(project: ProjectInfo, log: str, suffix: str = "last_failure") -> Path:
    log_dir = project.root / ".latex_surgeon_logs"
    log_dir.mkdir(exist_ok=True)
    path = log_dir / f"{project.tex.stem}_{suffix}.log"
    write_text(path, log)
    return path


def detect_korean_font_requirement(source: str) -> tuple[bool, str, bool]:
    """Detect Hangul text and report whether a Korean-capable font is available."""
    needs_korean = bool(re.search(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]", source or ""))
    if not needs_korean:
        return False, "", True
    candidates = ("Noto Sans CJK KR", "Noto Serif CJK KR", "Malgun Gothic", "NanumGothic")
    name, ok = choose_font(candidates)
    return True, name, ok


def print_font_report(fonts: dict[str, tuple[str, bool]]) -> None:
    print()
    say("Font environment", "font")
    for key, (name, installed) in fonts.items():
        status = "installed" if installed else "fallback candidate unavailable"
        print(f"  {key:8s}: {name} [{status}]")


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="LaTeX Surgeon"
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="A .tex file or project directory. If omitted, the configured 3-file batch is processed.",
    )
    p.add_argument(
        "--engine",
        choices=("xelatex", "lualatex", "pdflatex"),
        default=None,
    )
    p.add_argument("--rounds", type=int, default=60, help="Maximum adaptive treatment stages (default: 60)")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--no-learn", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--keep-build", action="store_true")
    p.add_argument(
        "--confidence",
        type=float,
        default=0.93,
        help="Minimum confidence required for automatic repair",
    )
    p.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    return p.parse_args()



# =============================================================================
# LaTeX Surgeon v7 — EXTENSIBLE ERROR INTELLIGENCE LAYER
# =============================================================================
#
# This layer is intentionally additive. It does not replace the original
# compiler core. It extends the knowledge base, diagnostics, structural
# analysis, project forensics, repair planning, verification and learning.
#
# Design goal:
#   Every newly observed failure should become reusable knowledge, not a
#   one-off patch for a particular document.
#
# Safety rule:
#   UNKNOWN != SAFE TO GUESS
#
# The engine may diagnose broadly, but automatic mutation remains conservative.
# =============================================================================

V7_VERSION = "7.0.0"
# Keep the public engine version independent from the legacy V7 layer.
VERSION = "19.0.0-FINAL"

# -----------------------------------------------------------------------------
# Extended LaTeX ecosystem knowledge
# -----------------------------------------------------------------------------

V7_PACKAGE_KNOWLEDGE = {
    # Mathematics
    "amsmath": {"commands": {
        "dfrac","tfrac","binom","dbinom","tbinom","text","operatorname",
        "DeclareMathOperator","overset","underset","boxed","tag","eqref",
        "substack","genfrac","doteq","mod","pmod","bmod","DeclareMathSizes",
    }, "environments": {
        "align","align*","alignat","alignat*","aligned","alignedat",
        "cases","dcases","dcases*","gather","gather*","gathered",
        "multline","multline*","split","equation*","smallmatrix",
    }},
    "amssymb": {"commands": {
        "mathbb","mathfrak","mathscr","Bbbk","therefore","because",
        "leqslant","geqslant","lesssim","gtrsim","nexists","varnothing",
        "checkmark","square","triangleq","shortmid","shortparallel",
    }, "environments": set()},
    "amsthm": {"commands": {
        "newtheorem","theoremstyle","theoremseparator","swapnumbers",
        "newtheoremstyle","proof","qedhere",
    }, "environments": {"proof"}},
    "mathtools": {"commands": {
        "DeclarePairedDelimiter","DeclarePairedDelimiterX","coloneqq",
        "xleftrightarrow","xrightarrow","xleftarrow","mathclap",
        "mathllap","mathrlap","prescript",
    }, "environments": {"multlined","dcases","dcases*"}},
    "bm": {"commands": {"bm","boldsymbol"}, "environments": set()},
    "physics": {"commands": {
        "qty","dv","ddv","pdv","bra","ket","braket","eval","commutator",
        "anticommutator","norm","abs","tr","rank","vb","va","vu","curl",
        "div","grad","laplacian",
    }, "environments": set()},

    # Tables
    "booktabs": {"commands": {
        "toprule","midrule","bottomrule","cmidrule","specialrule",
        "addlinespace","morecmidrules",
    }, "environments": set()},
    "array": {"commands": {
        "newcolumntype","extrarowheight","firsthline","lasthline",
        "extrarowheight",
    }, "environments": set()},
    "tabularx": {"commands": {"tabularxcolumn","TX","newcolumntype"}, "environments":{"tabularx"}},
    "longtable": {"commands": {
        "endfirsthead","endhead","endfoot","endlastfoot",
    }, "environments":{"longtable"}},
    "multirow": {"commands": {"multirow","multicolumn"}, "environments": set()},
    "makecell": {"commands": {"makecell","thead","makecellbox"}, "environments": set()},
    "colortbl": {"commands": {"rowcolor","cellcolor","columncolor"}, "environments": set()},

    # Graphics / figures
    "graphicx": {"commands": {
        "includegraphics","rotatebox","scalebox","resizebox","reflectbox",
        "graphicspath","DeclareGraphicsExtensions",
    }, "environments": set()},
    "float": {"commands": {"newfloat","floatstyle","restylefloat"}, "environments": set()},
    "placeins": {"commands": {"FloatBarrier"}, "environments": set()},
    "wrapfig": {"commands": set(), "environments":{"wrapfigure","wraptable"}},
    "subcaption": {"commands": {
        "subcaptionbox","subref","DeclareCaptionSubType","captionlistentry",
    }, "environments":{"subfigure","subtable"}},
    "caption": {"commands": {
        "captionof","captionsetup","DeclareCaptionFormat","DeclareCaptionLabelFormat",
    }, "environments": set()},
    "adjustbox": {"commands": {
        "adjustbox","includegraphics","minsizebox","maxsizebox",
    }, "environments":{"adjustbox"}},
    "tikz": {"commands": {
        "tikz","tikzset","usetikzlibrary","foreach","path","draw",
    }, "environments":{"tikzpicture"}},
    "pgfplots": {"commands": {
        "pgfplotsset","addplot","addplot3","nextgroupplot",
    }, "environments":{"axis","semilogxaxis","semilogyaxis","loglogaxis"}},
    "floatrow": {"commands": {
        "floatsetup","ffigbox","ttabbox","capbeside",
    }, "environments": set()},

    # Color
    "xcolor": {"commands": {
        "color","textcolor","colorbox","fcolorbox","definecolor",
        "providecolor","colorlet","definecolorset","rowcolor","cellcolor",
    }, "environments": set()},

    # Hyperlinks
    "hyperref": {"commands": {
        "href","url","nolinkurl","hyperref","autoref","hypersetup",
        "hyperlink","hypertarget","texorpdfstring",
    }, "environments": set()},
    "url": {"commands": {"url","nolinkurl","path"}, "environments": set()},

    # Bibliography
    "natbib": {"commands": {
        "citep","citet","citealt","citealp","citeauthor","citeyear",
        "citeyearpar","defcitealias","citetalias","citepalias",
    }, "environments": set()},
    "biblatex": {"commands": {
        "parencite","textcite","autocite","footcite","citeauthor",
        "citetitle","printbibliography","addbibresource","DeclareFieldFormat",
        "DeclareBibliographyDriver","AtEveryBibitem","AtNextCite",
    }, "environments": set()},
    "bibunits": {"commands": {"bibliographyunit","putbib","defaultbibliography"}, "environments":{"bibunit"}},
    "chapterbib": {"commands": set(), "environments": set()},

    # Units / science
    "siunitx": {"commands": {
        "SI","qty","num","unit","ang","qtyrange","numrange","complexqty",
        "complexnum","si","DeclareSIUnit","DeclareSIPrefix",
    }, "environments": set()},
    "mhchem": {"commands": {"ce","pu"}, "environments": set()},
    "chemfig": {"commands": {"chemfig","definesubmol","setatomsep"}, "environments": set()},
    "physics": {"commands": {
        "qty","dv","pdv","bra","ket","braket","commutator","anticommutator",
        "norm","abs","eval","vb","va","vu",
    }, "environments": set()},

    # Lists
    "enumitem": {"commands": {
        "setlist","newlist","renewlist","setlistdepth","restartlist",
    }, "environments":{"enumerate","itemize","description"}},
    "paralist": {"commands": set(), "environments":{
        "compactitem","compactenum","compactdesc","inparaenum","inparaitem",
    }},
    "tasks": {"commands": {"settasks","task","NewTasks"}, "environments":{"tasks"}},

    # Typography / fonts
    "fontspec": {"commands": {
        "setmainfont","setsansfont","setmonofont","newfontfamily",
        "newfontface","fontspec","defaultfontfeatures","addfontfeatures",
        "setmathrm","setmathsf","setmathtt","setboldmathrm","setitalicfont",
    }, "environments": set()},
    "polyglossia": {"commands": {
        "setmainlanguage","setotherlanguage","setotherlanguages",
        "setdefaultlanguage","setkeys",
    }, "environments": set()},
    "babel": {"commands": {"selectlanguage","foreignlanguage","babelprovide"}, "environments": set()},
    "xepersian": {"commands": {
        "settextfont","setlatintextfont","setdigitfont","setmathdigitfont",
        "setiranicfont","setiranicfont","setpersianfont",
        "lr","rl","LTR","RTL","setlatintextfont",
    }, "environments": set()},
    "bidi": {"commands": {"LTR","RTL","lr","rl"}, "environments": set()},
    "microtype": {"commands": {"microtypesetup","textls","lsstyle"}, "environments": set()},
    "setspace": {"commands": {"singlespacing","onehalfspacing","doublespacing","setstretch"}, "environments": set()},

    # Page layout
    "geometry": {"commands": {"geometry","newgeometry","restoregeometry","savegeometry","loadgeometry"}, "environments": set()},
    "fancyhdr": {"commands": {
        "pagestyle","fancyhf","fancyhead","fancyfoot","fancypagestyle",
        "fancyheadoffset","fancyfootoffset","headrulewidth","footrulewidth",
    }, "environments": set()},
    "titlesec": {"commands": {
        "titleformat","titlespacing","titlelabel","newpagestyle",
    }, "environments": set()},
    "titletoc": {"commands": {"titlecontents","dottedcontents"}, "environments": set()},
    "tocloft": {"commands": {
        "cftsetindents","cftsetpnumwidth","cftchapfont","cftsecfont",
        "cftchappagefont","cftsecleader",
    }, "environments": set()},
    "setspace": {"commands": {"onehalfspacing","doublespacing","singlespacing"}, "environments": set()},

    # References / cross references
    "cleveref": {"commands": {
        "cref","Cref","cpageref","Cpageref","crefrange","Crefrange",
        "crefmultiformat","crefname","Crefname","creflabelformat",
    }, "environments": set()},
    "nameref": {"commands": {"nameref"}, "environments": set()},
    "xr": {"commands": {"externaldocument"}, "environments": set()},
    "xr-hyper": {"commands": {"externaldocument"}, "environments": set()},

    # Index / glossary
    "makeidx": {"commands": {"makeindex","index","printindex"}, "environments": set()},
    "imakeidx": {"commands": {
        "makeindex","indexsetup","indexprologue","index","printindex",
        "printbibliography",
    }, "environments": set()},
    "glossaries": {"commands": {
        "newglossaryentry","newacronym","gls","Gls","glspl","Glspl",
        "printglossary","makeglossaries","glsadd",
    }, "environments": set()},
    "glossaries-extra": {"commands": {
        "newabbreviation","newterm","gls","glsxtrshort","glsxtrlong",
        "printglossary","glsxtrnewsymbol",
    }, "environments": set()},

    # Algorithms / code
    "listings": {"commands": {
        "lstinputlisting","lstset","lstinline","lstnewenvironment",
    }, "environments":{"lstlisting"}},
    "minted": {"commands": {
        "inputminted","newminted","newmintinline","setminted",
    }, "environments":{"minted"}},
    "algorithm": {"commands": {
        "floatname","listofalgorithms",
    }, "environments":{"algorithm"}},
    "algorithmicx": {"commands": {
        "algnewcommand","algdef","algnewenvironment",
    }, "environments":{"algorithmic"}},
    "algpseudocode": {"commands": {
        "State","For","EndFor","If","ElsIf","Else","EndIf","While","EndWhile",
        "Require","Ensure","Function","EndFunction","Procedure","EndProcedure",
        "Return","Comment",
    }, "environments":{"algorithmic"}},

    # PDF / metadata
    "bookmark": {"commands": {"bookmarksetup","bookmark","bookmarksetup"}, "environments": set()},
    "pdfpages": {"commands": {"includepdf","includepdfmerge"}, "environments": set()},
    "lastpage": {"commands": {"pageref"}, "environments": set()},
    "zref": {"commands": {
        "zlabel","zref","zrefused","zpageref","zcref","zsavepos",
    }, "environments": set()},

    # Linguistics / text
    "csquotes": {"commands": {
        "enquote","foreignquote","blockquote","textquote","DeclareQuoteStyle",
    }, "environments":{"displayquote","displaycquote","quoteblock"}},
    "ulem": {"commands": {"uline","uuline","uwave","sout","xout","dashuline"}, "environments": set()},
    "soul": {"commands": {"ul","st","so","hl","caps"}, "environments": set()},
    "textpos": {"commands": {"textblockorigin","TPMargin"}, "environments":{"textblock"}},
    "footmisc": {"commands": {"footnotelayout","setfnsymbol"}, "environments": set()},

    # Diagrams
    "forest": {"commands": {"forestset"}, "environments":{"forest"}},
    "qtree": {"commands": {"Tree","qroof"}, "environments": set()},
    "tikz-cd": {"commands": {"arrow","tikzcdset"}, "environments":{"tikzcd"}},

    # Units / dates
    "datetime2": {"commands": {"DTMnow","DTMdate","DTMsavetimestamp"}, "environments": set()},
    "datenumber": {"commands": {"datedifference","daycount"}, "environments": set()},
}

V7_COMMAND_TO_PACKAGE = {}
for _pkg, _info in V7_PACKAGE_KNOWLEDGE.items():
    for _cmd in _info["commands"]:
        V7_COMMAND_TO_PACKAGE.setdefault(_cmd, []).append(_pkg)

V7_ENV_TO_PACKAGE = {}
for _pkg, _info in V7_PACKAGE_KNOWLEDGE.items():
    for _env in _info["environments"]:
        V7_ENV_TO_PACKAGE.setdefault(_env, []).append(_pkg)


V7_ERROR_PATTERNS = [
    # Fonts / encodings
    ("font_missing", re.compile(r"(fontspec).{0,120}(font .* cannot be found|cannot be found|not found)", re.I|re.S)),
    ("font_missing", re.compile(r"The font [`\"]?([^`\"\n]+)[`\"]? cannot be found", re.I)),
    ("unicode_error", re.compile(r"(Unicode character|Unicode.*not set up|inputenc Error|invalid UTF-8)", re.I)),
    ("encoding_error", re.compile(r"(inputenc|Invalid UTF-8|Unicode character .* not set up)", re.I)),

    # Core parser
    ("missing_begin_document", re.compile(r"Missing\s+\\begin\{document\}", re.I)),
    ("missing_end_document", re.compile(r"(\\end\{document\}.*missing|document ended before|Emergency stop)", re.I)),
    ("brace_error", re.compile(r"(Missing\s*\}|Missing\s*\{|Too many \}|Extra \}|Argument of .* has an extra \})", re.I)),
    ("runaway_argument", re.compile(r"(Runaway argument|File ended while scanning use of)", re.I)),
    ("file_ended_scanning", re.compile(r"(File ended while scanning|File ended while.*argument)", re.I)),
    ("missing_end", re.compile(r"(Missing \\end\{|\\begin\{[^}]+\}.*ended by \\end\{|\begingroup ended by)", re.I)),
    ("extra_end", re.compile(r"(\\end\{[^}]+\}.*doesn't match|Extra \\end)", re.I)),
    ("misplaced_alignment", re.compile(r"(Misplaced alignment tab character|Extra alignment tab)", re.I)),
    ("misplaced_noalign", re.compile(r"(Misplaced \\noalign)", re.I)),
    ("misplaced_span", re.compile(r"(Misplaced \\omit|Misplaced \\span)", re.I)),
    ("illegal_parameter", re.compile(r"(Illegal parameter number|Parameters must be numbered)", re.I)),
    ("macro_delimited_argument", re.compile(r"(Use of .* doesn't match its definition|Illegal parameter number)", re.I)),

    # Commands/environments/packages
    ("undefined_command", re.compile(r"Undefined control sequence", re.I)),
    ("undefined_environment", re.compile(r"(Environment .* undefined|Unknown environment)", re.I)),
    ("missing_package", re.compile(r"(File `[^`]+\.sty' not found|LaTeX Error: File `[^`]+` not found)", re.I)),
    ("package_not_found", re.compile(r"(File `[^`]+\.sty' not found|I can't find file)", re.I)),
    ("option_clash", re.compile(r"Option clash for package", re.I)),
    ("unknown_option", re.compile(r"(Unknown option|LaTeX Error: Unknown option)", re.I)),
    ("package_error", re.compile(r"Package .* Error:", re.I)),
    ("package_warning", re.compile(r"Package .* Warning:", re.I)),

    # References
    ("undefined_reference", re.compile(r"(LaTeX Warning: Reference `[^`]+` undefined|There were undefined references)", re.I)),
    ("undefined_citation", re.compile(r"(Citation `[^`]+` undefined|There were undefined citations)", re.I)),
    ("multiply_defined_label", re.compile(r"(multiply-defined labels|Label `[^`]+` multiply defined)", re.I)),
    ("rerun_needed", re.compile(r"(Rerun to get cross-references right|Rerun LaTeX)", re.I)),
    ("bibtex_error", re.compile(r"(I couldn't open database file|I was not able to find the bibliography style|BibTeX error)", re.I)),
    ("biber_error", re.compile(r"(Biber error|ERROR -.*biber|Cannot find control file)", re.I)),
    ("biblatex_error", re.compile(r"Package biblatex Error:", re.I)),
    ("empty_bibliography", re.compile(r"(Empty `thebibliography' environment|Empty bibliography)", re.I)),

    # Graphics/files
    ("file_not_found", re.compile(r"(File `[^`]+` not found|I can't find file|No file .* found)", re.I)),
    ("graphics_not_found", re.compile(r"(File `[^`]+\.(png|jpg|jpeg|pdf|eps)' not found|Unknown graphics extension)", re.I)),
    ("pdf_inclusion_error", re.compile(r"(pdfTeX error.*PDF|cannot include graphics|PDF inclusion)", re.I)),
    ("shell_escape", re.compile(r"(shell escape|not allowed|restricted \\write18)", re.I)),

    # Layout / floats
    ("float_too_large", re.compile(r"(Float too large|Too many unprocessed floats)", re.I)),
    ("overfull_hbox", re.compile(r"Overfull \\[hv]box", re.I)),
    ("underfull_hbox", re.compile(r"Underfull \\[hv]box", re.I)),
    ("overfull_vbox", re.compile(r"Overfull \\vbox", re.I)),
    ("underfull_vbox", re.compile(r"Underfull \\vbox", re.I)),

    # Math
    ("math_shift_error", re.compile(r"(Missing \$ inserted|Display math should end with|Bad math environment delimiter)", re.I)),
    ("math_delimiter_error", re.compile(r"(Missing \\right|Missing \\left|Extra \\right|\\left.*\\right)", re.I)),
    ("math_mode_error", re.compile(r"(You can't use `macro:.*in math mode|Command .* invalid in math mode)", re.I)),
    ("display_math_error", re.compile(r"(Display math should end with|Bad math environment delimiter)", re.I)),

    # Tables
    ("tabular_error", re.compile(r"(Extra alignment tab|Misplaced \\noalign|Missing number.*tabular|Illegal pream-token)", re.I)),
    ("column_spec_error", re.compile(r"(Illegal pream-token|Missing # inserted|Extra alignment tab)", re.I)),

    # Engine / system
    ("engine_mismatch", re.compile(r"(requires XeTeX|requires LuaTeX|This package requires.*TeX|pdfTeX error.*fontspec)", re.I)),
    ("shell_command_failed", re.compile(r"(Command .* failed|system returned|spawn.*failed)", re.I)),
    ("memory_error", re.compile(r"(TeX capacity exceeded|main memory size|pool size|save size)", re.I)),
    ("recursion_error", re.compile(r"(TeX capacity exceeded.*input stack|input stack size)", re.I)),
    ("internal_tex_error", re.compile(r"(Fatal error occurred|Emergency stop|! LaTeX Error:)", re.I)),
]


# -----------------------------------------------------------------------------
# Source scanner
# -----------------------------------------------------------------------------

V7_COMMENT_RE = re.compile(r"(?<!\\)%.*$")
V7_COMMAND_RE = re.compile(r"\\([A-Za-z@][A-Za-z0-9@:_-]*|.)")
V7_BEGIN_RE = re.compile(r"\\begin\s*\{([^}]+)\}")
V7_END_RE = re.compile(r"\\end\s*\{([^}]+)\}")
V7_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")
V7_DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")
V7_GRAPHIC_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
V7_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
V7_BIB_RE = re.compile(r"\\(?:addbibresource|bibliography)\s*\{([^}]+)\}")
V7_CITE_RE = re.compile(r"\\(?:cite|citep|citet|parencite|textcite|autocite|footcite)\s*(?:\[[^\]]*\])*(?:\{([^}]+)\})")


def v7_strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        out.append(V7_COMMENT_RE.sub("", line))
    return "\n".join(out)


def v7_balanced_delimiters(text: str) -> dict:
    clean = v7_strip_comments(text)
    pairs = {"{": "}", "[": "]"}
    stacks = {k: [] for k in pairs}
    mismatches = []
    escaped = False
    for i, ch in enumerate(clean):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in stacks:
            stacks[ch].append(i)
        elif ch in "}]":
            op = "{" if ch == "}" else "["
            if not stacks[op]:
                mismatches.append((ch, i, "extra"))
            else:
                stacks[op].pop()
    return {
        "unclosed": {k: len(v) for k, v in stacks.items()},
        "mismatches": mismatches[:100],
        "balanced": not any(stacks.values()) and not mismatches,
    }


def v7_environment_stack(text: str) -> dict:
    clean = v7_strip_comments(text)
    stack = []
    mismatches = []
    for line_no, line in enumerate(clean.splitlines(), 1):
        for token in re.finditer(r"\\(begin|end)\s*\{([^}]+)\}", line):
            action, env = token.group(1), token.group(2).strip()
            if action == "begin":
                stack.append((env, line_no))
            elif not stack:
                mismatches.append({
                    "line": line_no, "environment": env, "type": "extra_end"
                })
            elif stack[-1][0] == env:
                stack.pop()
            else:
                # Search downward in stack. Do not mutate; this is diagnostic.
                idx = next(
                    (i for i in range(len(stack)-1, -1, -1)
                     if stack[i][0] == env), None
                )
                mismatches.append({
                    "line": line_no,
                    "environment": env,
                    "type": "mismatched_end",
                    "opened": stack[-1] if stack else None,
                    "matching_index": idx,
                })
                if idx is not None:
                    stack.pop(idx)
    return {
        "open": stack,
        "mismatches": mismatches,
        "balanced": not stack and not mismatches,
    }


def v7_extract_commands(text: str) -> dict[str, list[int]]:
    result = {}
    clean = v7_strip_comments(text)
    for line_no, line in enumerate(clean.splitlines(), 1):
        for m in V7_COMMAND_RE.finditer(line):
            cmd = m.group(1)
            if len(cmd) > 1 and cmd not in {"begin", "end"}:
                result.setdefault(cmd, []).append(line_no)
    return result


def v7_extract_environments(text: str) -> dict[str, list[int]]:
    result = {}
    clean = v7_strip_comments(text)
    for line_no, line in enumerate(clean.splitlines(), 1):
        for m in V7_BEGIN_RE.finditer(line):
            result.setdefault(m.group(1), []).append(line_no)
    return result


def v7_extract_packages(text: str) -> dict[str, list[int]]:
    result = {}
    for line_no, line in enumerate(v7_strip_comments(text).splitlines(), 1):
        for m in V7_USEPACKAGE_RE.finditer(line):
            for pkg in m.group(1).split(","):
                result.setdefault(pkg.strip(), []).append(line_no)
    return result


def v7_defined_macros(text: str) -> set[str]:
    patterns = [
        r"\\(?:newcommand|renewcommand|providecommand)\s*\{\\([A-Za-z@][\w@:_-]*)\}",
        r"\\DeclareRobustCommand\s*\{\\([A-Za-z@][\w@:_-]*)\}",
        r"\\def\s*\\([A-Za-z@][\w@:_-]*)",
        r"\\DeclareMathOperator\*?\s*\{\\([A-Za-z@][\w@:_-]*)\}",
        r"\\NewDocumentCommand\s*\{\\([A-Za-z@][\w@:_-]*)\}",
    ]
    found = set()
    for pat in patterns:
        found.update(re.findall(pat, text))
    return found


def v7_document_profile(project: ProjectInfo) -> dict:
    text = read_text(project.tex)
    clean = v7_strip_comments(text)
    return {
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "documentclass": next(
            iter(V7_DOCUMENTCLASS_RE.findall(clean)), None
        ),
        "packages": v7_extract_packages(clean),
        "commands": v7_extract_commands(clean),
        "environments": v7_extract_environments(clean),
        "defined_macros": v7_defined_macros(clean),
        "delimiter": v7_balanced_delimiters(clean),
        "environment_stack": v7_environment_stack(clean),
        "has_document_begin": bool(re.search(r"\\begin\s*\{document\}", clean)),
        "has_document_end": bool(re.search(r"\\end\s*\{document\}", clean)),
        "graphics": V7_GRAPHIC_RE.findall(clean),
        "inputs": V7_INPUT_RE.findall(clean),
        "bibliographies": V7_BIB_RE.findall(clean),
        "citations": [
            k.strip()
            for group in V7_CITE_RE.findall(clean)
            for k in group.split(",")
        ],
    }


# -----------------------------------------------------------------------------
# Log forensics
# -----------------------------------------------------------------------------

def v7_extract_line_numbers(log: str) -> list[int]:
    nums = []
    for pat in (
        r"\bl\.(\d+)\b",
        r":(\d+):\s*(?:LaTeX|Package|Undefined|!|Emergency)",
        r"line\s+(\d+)",
    ):
        nums.extend(int(x) for x in re.findall(pat, log, re.I))
    return sorted(set(n for n in nums if n > 0))


def v7_extract_quoted_file(log: str) -> Optional[str]:
    pats = [
        r"File [`']([^`']+)[`']",
        r"\(([^()\s]+\.sty)\b",
        r"\(([^()\s]+\.tex)\b",
    ]
    for pat in pats:
        m = re.search(pat, log, re.I)
        if m:
            return m.group(1)
    return None


def v7_extract_unknown_command(log: str, source: str) -> Optional[str]:
    # The command can occur after several lines of TeX's diagnostic context.
    m = re.search(
        r"Undefined control sequence.*?(?:\n|\r\n)+.*?\\([A-Za-z@][A-Za-z0-9@:_-]*)",
        log, re.I | re.S
    )
    if m:
        return m.group(1)

    # Generic fallback: locate the compiler-reported line.
    lines = source.splitlines()
    candidates = v7_extract_line_numbers(log)
    for line_no in candidates:
        if 1 <= line_no <= len(lines):
            context = "\n".join(lines[max(0, line_no-2):min(len(lines), line_no+2)])
            commands = re.findall(
                r"\\([A-Za-z@][A-Za-z0-9@:_-]*)", context
            )
            if commands:
                # Prefer a non-core command.
                return commands[-1]
    return None


def v7_extract_unknown_environment(log: str) -> Optional[str]:
    patterns = [
        r"Environment\s+([A-Za-z*_-][A-Za-z0-9*_-]*)\s+undefined",
        r"Unknown environment\s+([A-Za-z*_-][A-Za-z0-9*_-]*)",
    ]
    for pat in patterns:
        m = re.search(pat, log, re.I)
        if m:
            return m.group(1)
    return None


def v7_extract_missing_file(log: str) -> Optional[str]:
    patterns = [
        r"File [`']([^`']+)[`']\s+not found",
        r"I can't find file [`']?([^`'\s]+)",
        r"No file [`']?([^`'\s]+)\s+found",
    ]
    for pat in patterns:
        m = re.search(pat, log, re.I)
        if m:
            return m.group(1)
    return None


def v7_classify_log(log: str, profile: dict) -> list[dict]:
    findings = []
    for kind, pattern in V7_ERROR_PATTERNS:
        m = pattern.search(log)
        if not m:
            continue
        lines = v7_extract_line_numbers(log)
        confidence = 0.82
        if kind in {"undefined_command","undefined_environment","missing_package"}:
            confidence = 0.94
        if kind in {"missing_begin_document","runaway_argument","file_ended_scanning"}:
            confidence = 0.98
        findings.append({
            "kind": kind,
            "confidence": confidence,
            "line": lines[0] if lines else None,
            "evidence": m.group(0)[:700],
        })

    # Add source-derived structural findings even if the log is vague.
    if not profile["delimiter"]["balanced"]:
        findings.append({
            "kind": "source_unbalanced_delimiter",
            "confidence": 0.96,
            "line": None,
            "evidence": str(profile["delimiter"]),
        })
    if not profile["environment_stack"]["balanced"]:
        findings.append({
            "kind": "source_unbalanced_environment",
            "confidence": 0.97,
            "line": None,
            "evidence": str(profile["environment_stack"]),
        })

    # Deduplicate by kind, keeping highest confidence.
    best = {}
    for f in findings:
        old = best.get(f["kind"])
        if old is None or f["confidence"] > old["confidence"]:
            best[f["kind"]] = f
    return sorted(best.values(), key=lambda x: (-x["confidence"], x["kind"]))


# -----------------------------------------------------------------------------
# Dependency reasoning
# -----------------------------------------------------------------------------

def v7_package_candidates_for_command(command: str) -> list[str]:
    return V7_COMMAND_TO_PACKAGE.get(command, [])


def v7_package_candidates_for_environment(env: str) -> list[str]:
    return V7_ENV_TO_PACKAGE.get(env, [])


def v7_is_package_loaded(text: str, package: str) -> bool:
    return bool(re.search(
        rf"\\usepackage(?:\[[^\]]*\])?\{{[^}}]*\b{re.escape(package)}\b[^}}]*\}}",
        text
    ))


def v7_find_duplicate_packages(text: str) -> list[tuple[str, list[int]]]:
    pkgs = v7_extract_packages(text)
    return [(p, lines) for p, lines in pkgs.items() if len(lines) > 1]


def v7_find_option_clashes(text: str) -> list[dict]:
    # This is static suspicion, not proof. Runtime compiler evidence remains
    # the authority before automatic mutation.
    result = []
    occurrences = {}
    for line_no, line in enumerate(v7_strip_comments(text).splitlines(), 1):
        m = re.search(r"\\usepackage\[([^\]]+)\]\{([^}]+)\}", line)
        if not m:
            continue
        pkg = m.group(2).strip()
        opts = {x.strip() for x in m.group(1).split(",")}
        occurrences.setdefault(pkg, []).append((line_no, opts))
    for pkg, items in occurrences.items():
        if len(items) > 1:
            union = set().union(*(x[1] for x in items))
            result.append({"package": pkg, "occurrences": items, "options": sorted(union)})
    return result


def v7_suggest_package_for_command(command: str, loaded: set[str]) -> Optional[str]:
    candidates = [
        p for p in v7_package_candidates_for_command(command)
        if p not in loaded
    ]
    if len(candidates) == 1:
        return candidates[0]
    # Multiple packages may expose the same command. Never guess.
    return None


def v7_suggest_package_for_environment(env: str, loaded: set[str]) -> Optional[str]:
    candidates = [
        p for p in v7_package_candidates_for_environment(env)
        if p not in loaded
    ]
    return candidates[0] if len(candidates) == 1 else None


# -----------------------------------------------------------------------------
# Asset / project forensics
# -----------------------------------------------------------------------------

V7_ASSET_EXTS = {
    ".png",".jpg",".jpeg",".jpe",".jfif",".webp",".pdf",".eps",".svg",
    ".tif",".tiff",".bmp",".gif",".csv",".txt",".dat",".bib",".sty",".cls",
}


def v7_project_files(project: ProjectInfo) -> list[Path]:
    try:
        return [
            x for x in project.root.rglob("*")
            if x.is_file() and ".latex_surgeon_backups" not in x.parts
        ]
    except Exception:
        return []


def v7_case_insensitive_lookup(project: ProjectInfo, requested: str) -> list[Path]:
    target = requested.replace("\\", "/").lstrip("./")
    exact = project.root / target
    candidates = []
    if exact.exists():
        candidates.append(exact)
    low = target.lower()
    for p in v7_project_files(project):
        try:
            rel = p.relative_to(project.root).as_posix()
        except ValueError:
            continue
        if rel.lower() == low and p not in candidates:
            candidates.append(p)
    return candidates


def v7_find_asset(project: ProjectInfo, requested: str) -> list[Path]:
    base = requested.replace("\\", "/")
    stem = Path(base).stem
    suffix = Path(base).suffix.lower()
    candidates = v7_case_insensitive_lookup(project, base)
    if candidates:
        return candidates

    # TeX's graphicx can resolve extensionless graphics.
    for p in v7_project_files(project):
        if p.stem.lower() == stem.lower():
            if not suffix or p.suffix.lower() == suffix or p.suffix.lower() in V7_ASSET_EXTS:
                candidates.append(p)
    return candidates[:30]


def v7_extract_all_graphic_requests(project: ProjectInfo) -> list[dict]:
    text = read_text(project.tex)
    result = []
    for line_no, line in enumerate(v7_strip_comments(text).splitlines(), 1):
        for m in V7_GRAPHIC_RE.finditer(line):
            requested = m.group(1).strip()
            matches = v7_find_asset(project, requested)
            result.append({
                "line": line_no,
                "requested": requested,
                "matches": [str(x.relative_to(project.root)) for x in matches],
                "resolved": bool(matches),
            })
    return result


# -----------------------------------------------------------------------------
# Bibliography / citation forensics
# -----------------------------------------------------------------------------

V7_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)", re.I)


def v7_find_bib_files(project: ProjectInfo) -> list[Path]:
    return [p for p in v7_project_files(project) if p.suffix.lower() == ".bib"]


def v7_collect_bib_keys(project: ProjectInfo) -> set[str]:
    keys = set()
    for bib in v7_find_bib_files(project):
        try:
            text = bib.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        keys.update(V7_BIB_KEY_RE.findall(text))
    return keys


def v7_collect_citations(text: str) -> set[str]:
    keys = set()
    for m in V7_CITE_RE.finditer(v7_strip_comments(text)):
        keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    return keys


def v7_bibliography_report(project: ProjectInfo) -> dict:
    source = read_text(project.tex)
    citations = v7_collect_citations(source)
    bib_keys = v7_collect_bib_keys(project)
    return {
        "citation_count": len(citations),
        "bib_key_count": len(bib_keys),
        "undefined": sorted(citations - bib_keys),
        "unused": sorted(bib_keys - citations),
    }


# -----------------------------------------------------------------------------
# Cross-reference forensics
# -----------------------------------------------------------------------------

V7_LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")
V7_REF_RE = re.compile(r"\\(?:ref|pageref|autoref|cref|Cref|cpageref)\s*\{([^}]+)\}")


def v7_reference_report(project: ProjectInfo) -> dict:
    text = v7_strip_comments(read_text(project.tex))
    labels = V7_LABEL_RE.findall(text)
    refs = V7_REF_RE.findall(text)
    label_set = set(labels)
    ref_set = set(refs)
    duplicates = sorted({x for x in labels if labels.count(x) > 1})
    return {
        "labels": len(label_set),
        "references": len(ref_set),
        "undefined": sorted(ref_set - label_set),
        "duplicates": duplicates,
    }


# -----------------------------------------------------------------------------
# Engine / toolchain intelligence
# -----------------------------------------------------------------------------

V7_ENGINE_PACKAGE_RULES = {
    "fontspec": {"xelatex", "lualatex"},
    "xepersian": {"xelatex"},
    "bidi": {"xelatex", "lualatex"},
    "polyglossia": {"xelatex", "lualatex"},
    "unicode-math": {"xelatex", "lualatex"},
    "luatexja": {"lualatex"},
    "luatexja-fontspec": {"lualatex"},
    "inputenc": {"pdflatex","xelatex","lualatex"},
}


def v7_engine_compatibility(project: ProjectInfo) -> list[dict]:
    profile = v7_document_profile(project)
    engine = project.engine.lower()
    issues = []
    for pkg in profile["packages"]:
        allowed = V7_ENGINE_PACKAGE_RULES.get(pkg)
        if allowed and engine not in allowed:
            issues.append({
                "package": pkg,
                "engine": engine,
                "allowed": sorted(allowed),
            })
    return issues


def v7_detect_bibliography_backend(project: ProjectInfo) -> str:
    text = v7_strip_comments(read_text(project.tex))
    if "\\usepackage{biblatex}" in text or "\\addbibresource" in text:
        return "biber"
    if "\\bibliography" in text or "\\bibliographystyle" in text:
        return "bibtex"
    return "none"


# -----------------------------------------------------------------------------
# Advanced repair proposal helpers
# -----------------------------------------------------------------------------

def v7_add_package_safely(source: str, package: str) -> Optional[str]:
    if v7_is_package_loaded(source, package):
        return None

    lines = source.splitlines(True)
    insert_at = 0
    for i, line in enumerate(lines):
        if "\\documentclass" in line:
            insert_at = i + 1
            continue
        if i > insert_at and "\\usepackage" in line:
            insert_at = i + 1

    newline = "\\usepackage{" + package + "}\n"
    lines.insert(insert_at, newline)
    candidate = "".join(lines)

    safe, _ = source_safety_check(source, candidate)
    return candidate if safe else None


def v7_propose_known_dependency(project: ProjectInfo, findings: list[dict]) -> list[RepairProposal]:
    source = read_text(project.tex)
    loaded = set(v7_extract_packages(source))
    proposals = []

    for f in findings:
        if f["kind"] == "undefined_command":
            cmd = v7_extract_unknown_command(
                f["evidence"], source
            )
            if not cmd:
                continue
            if cmd in v7_defined_macros(source):
                continue
            pkg = v7_suggest_package_for_command(cmd, loaded)
            if not pkg:
                continue
            new = v7_add_package_safely(source, pkg)
            if new:
                proposals.append(RepairProposal(
                    rule_id="V7_KNOWN_COMMAND_DEPENDENCY",
                    description=f"Add unambiguous package '{pkg}' for '\\{cmd}'",
                    confidence=0.985,
                    old_text=source,
                    new_text=new,
                    rationale=f"Compiler reported undefined '\\{cmd}'; knowledge base maps it uniquely to '{pkg}'.",
                ))

        elif f["kind"] == "undefined_environment":
            env = v7_extract_unknown_environment(f["evidence"])
            if not env:
                continue
            pkg = v7_suggest_package_for_environment(env, loaded)
            if not pkg:
                continue
            new = v7_add_package_safely(source, pkg)
            if new:
                proposals.append(RepairProposal(
                    rule_id="V7_KNOWN_ENV_DEPENDENCY",
                    description=f"Add unambiguous package '{pkg}' for environment '{env}'",
                    confidence=0.985,
                    old_text=source,
                    new_text=new,
                    rationale=f"Compiler reported undefined environment '{env}'; dependency is unambiguous.",
                ))
    return proposals


def v7_propose_utf8_bom(project: ProjectInfo) -> Optional[RepairProposal]:
    raw = project.tex.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        return None
    source = raw.decode("utf-8", errors="replace")
    new = source.lstrip("\ufeff")
    if new == source:
        return None
    return RepairProposal(
        rule_id="V7_REMOVE_UTF8_BOM",
        description="Remove UTF-8 BOM before TeX source",
        confidence=0.995,
        old_text=source,
        new_text=new,
        rationale="A BOM at byte zero can confuse TeX engines or generated preambles.",
    )


def v7_propose_duplicate_package(project: ProjectInfo) -> list[RepairProposal]:
    source = read_text(project.tex)
    proposals = []
    for package, lines in v7_find_duplicate_packages(source):
        # Only exact duplicate declarations with no options are candidates.
        occurrences = list(re.finditer(
            rf"^[ \t]*\\usepackage\{{{re.escape(package)}\}}[ \t]*\r?$",
            source, re.M
        ))
        if len(occurrences) < 2:
            continue
        keep = True
        out = []
        seen = False
        changed = False
        for line in source.splitlines(True):
            if re.match(
                rf"^[ \t]*\\usepackage\{{{re.escape(package)}\}}[ \t]*\r?$",
                line
            ):
                if not seen:
                    seen = True
                    out.append(line)
                else:
                    changed = True
            else:
                out.append(line)
        if changed:
            new = "".join(out)
            safe, _ = source_safety_check(source, new)
            if safe:
                proposals.append(RepairProposal(
                    rule_id="V7_REMOVE_EXACT_DUPLICATE_PACKAGE",
                    description=f"Remove exact duplicate package declaration: {package}",
                    confidence=0.995,
                    old_text=source,
                    new_text=new,
                    rationale="Only byte-equivalent package declarations are deduplicated.",
                ))
    return proposals


# -----------------------------------------------------------------------------
# Non-mutating forensic report
# -----------------------------------------------------------------------------

def v7_forensic_report(project: ProjectInfo, compile_log: str = "") -> dict:
    profile = v7_document_profile(project)
    report = {
        "version": V7_VERSION,
        "project": str(project.root),
        "source": str(project.tex),
        "engine": project.engine,
        "profile": {
            "lines": profile["lines"],
            "bytes": profile["bytes"],
            "documentclass": profile["documentclass"],
            "package_count": len(profile["packages"]),
            "command_count": len(profile["commands"]),
            "environment_count": len(profile["environments"]),
            "defined_macro_count": len(profile["defined_macros"]),
        },
        "structure": {
            "delimiter": profile["delimiter"],
            "environment_stack": profile["environment_stack"],
            "document_begin": profile["has_document_begin"],
            "document_end": profile["has_document_end"],
        },
        "assets": v7_extract_all_graphic_requests(project),
        "bibliography": v7_bibliography_report(project),
        "references": v7_reference_report(project),
        "engine_compatibility": v7_engine_compatibility(project),
        "bibliography_backend": v7_detect_bibliography_backend(project),
    }
    if compile_log:
        report["compiler_findings"] = v7_classify_log(compile_log, profile)
    return report


def v7_write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# -----------------------------------------------------------------------------
# Knowledge memory: every successful/failed rule becomes reusable evidence.
# -----------------------------------------------------------------------------

def v7_update_learning_memory(project: ProjectInfo, memory: dict, rule_id: str, success: bool, context: dict) -> dict:
    bucket = memory.setdefault("v7_rules", {})
    item = bucket.setdefault(rule_id, {
        "success": 0,
        "failure": 0,
        "last": None,
        "contexts": [],
    })
    item["success" if success else "failure"] += 1
    item["last"] = datetime.now().isoformat(timespec="seconds")
    if len(item["contexts"]) < 50:
        item["contexts"].append(context)

    # Empirical score is informational and bounded. It never overrides the
    # hard confidence threshold by itself.
    total = item["success"] + item["failure"]
    item["empirical_success_rate"] = item["success"] / total if total else 0.0
    return memory


# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# V9 resilience / transaction helpers
# -----------------------------------------------------------------------------

def v9_safe_json_write(path: Path, payload: dict) -> None:
    """Best-effort atomic-ish JSON journal. Never raises into the supervisor."""
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        pass


def v9_journal(project: ProjectInfo, event: str, **data) -> None:
    """Append a machine-readable event without ever stopping the build."""
    try:
        path = project.root / ".latex_surgeon_runtime_journal.jsonl"
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **data,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def v9_call(label, fn, *args, default=None, **kwargs):
    """
    Runtime isolation boundary.

    A faulty intelligence module is quarantined for this call instead of
    terminating the entire build.
    """
    project = args[0] if args and isinstance(args[0], ProjectInfo) else None
    self_heartbeat(project, "module_enter", module=label)
    with _SELF_LOCK:
        _SELF_STATE["module"] = label
    try:
        value = fn(*args, **kwargs)
        self_heartbeat(project, "module_exit", module=label, ok=True)
        return value
    except Exception as exc:
        self_exception_report(project, label, exc)
        v9_journal(
            project,
            "module_exception",
            module=label,
            exception=type(exc).__name__,
            message=str(exc),
            traceback=traceback.format_exc(),
        )
        try:
            say(f"{label} isolated after runtime error: {exc}", "warn")
        except Exception:
            pass
        self_heartbeat(project, "module_quarantined", module=label, ok=False)
        return default


def v9_changed_ranges(old: str, new: str):
    """Return source intervals changed by a proposal."""
    if old == new:
        return []
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    ranges = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            ranges.append((i1, i2, new[j1:j2]))
    return ranges


def v9_merge_proposals(source: str, proposals: list[RepairProposal]):
    """
    Merge independent whole-source proposals into one transaction.

    Two candidates are batch-compatible only when their source edits do not
    overlap. Conflicting candidates are left for individual verification.
    """
    if not proposals:
        return None

    edits = []
    seen_rules = set()

    for proposal in proposals:
        if proposal.old_text != source:
            continue
        if proposal.rule_id in seen_rules:
            continue
        seen_rules.add(proposal.rule_id)

        for i1, i2, replacement in v9_changed_ranges(
            source, proposal.new_text
        ):
            edits.append((i1, i2, replacement, proposal))

    if not edits:
        return None

    edits.sort(key=lambda x: (x[0], x[1]))

    # Detect conflicts. Insertions at the same location conflict as well.
    for a, b in zip(edits, edits[1:]):
        a1, a2 = a[0], a[1]
        b1, b2 = b[0], b[1]
        if a2 > b1 or (a1 == a2 == b1 == b2):
            return None

    merged = source
    for i1, i2, replacement, _proposal in reversed(edits):
        merged = merged[:i1] + replacement + merged[i2:]

    if merged == source:
        return None

    rules = sorted({e[3].rule_id for e in edits})
    descriptions = " + ".join(e[3].description for e in edits[:6])
    confidence = min(e[3].confidence for e in edits)

    return RepairProposal(
        rule_id="BATCH[" + ",".join(rules) + "]",
        description=f"Batch independent repairs ({len(rules)}): {descriptions}",
        confidence=confidence,
        old_text=source,
        new_text=merged,
        rationale="Non-overlapping source edits merged into one transaction.",
    )


def v9_save_failure(project: ProjectInfo, round_no: int, result: BuildResult,
                    diagnostics: list[Diagnostic], proposals=None) -> None:
    """Persist failure evidence even when higher-level intelligence fails."""
    try:
        payload = {
            "round": round_no,
            "engine": result.engine,
            "returncode": result.returncode,
            "elapsed": result.elapsed,
            "diagnostics": [
                {
                    "kind": d.kind,
                    "severity": d.severity,
                    "line": d.line,
                    "message": d.message,
                    "confidence": d.confidence,
                    "secondary": d.secondary,
                }
                for d in diagnostics
            ],
            "proposals": [
                {
                    "rule_id": p.rule_id,
                    "confidence": p.confidence,
                    "description": p.description,
                }
                for p in (proposals or [])
            ],
            "log_tail": result.log[-20000:],
        }
        v9_safe_json_write(
            project.root / f".latex_surgeon_failure_round_{round_no}.json",
            payload,
        )
    except Exception:
        pass


def v9_accept_learning(project, memory, cfg, proposal, success, context):
    """Learning is advisory: corrupt learning must never stop compilation."""
    if not cfg.learn:
        return memory
    try:
        memory = v7_update_learning_memory(
            project, memory, proposal.rule_id, success, context
        )
        save_memory(project, cfg, memory)
    except Exception as exc:
        v9_journal(
            project,
            "learning_exception",
            rule_id=proposal.rule_id,
            exception=type(exc).__name__,
            message=str(exc),
        )
        try:
            say(f"Learning isolated: {exc}", "warn")
        except Exception:
            pass
    return memory



def v12_diagnostic_snapshot(project: ProjectInfo, result: BuildResult):
    """Best-effort normalized error snapshot used for progress scoring."""
    try:
        profile = v7_document_profile(project) or {}
    except Exception:
        profile = {}
    try:
        findings = v7_classify_log(result.log, profile) or []
    except Exception:
        findings = []
    try:
        diagnostics = diagnostics_from_log(project, result.log) or []
    except Exception:
        diagnostics = []
    try:
        diagnostics = detect_root_cause(project, diagnostics) or diagnostics
    except Exception:
        pass

    primary = []
    for d in diagnostics:
        try:
            kind = str(getattr(d, 'kind', '')).lower()
            sev = str(getattr(d, 'severity', '')).lower()
            # These are not source-fix blockers by themselves.
            if kind in {'rerun_needed', 'shell_escape', 'package_warning'}:
                continue
            if sev == 'error' and not getattr(d, 'secondary', False):
                primary.append(d)
        except Exception:
            continue

    # If the legacy parser missed an obvious TeX error, use V7 findings as a
    # fallback, but never double count by kind+line.
    seen = {(getattr(d, 'kind', ''), getattr(d, 'line', None)) for d in primary}
    for f in findings:
        try:
            kind = str(f.get('kind', ''))
            if kind in {'rerun_needed', 'shell_escape', 'package_warning'}:
                continue
            if str(f.get('severity', 'error')).lower() != 'error':
                continue
            key = (kind, f.get('line'))
            if key not in seen:
                primary.append(f)
                seen.add(key)
        except Exception:
            continue

    # Lower is better. Large penalties keep a real compiler failure distinct
    # from a successful PDF build while still allowing partial progress.
    n = len(primary)
    kinds = {str(getattr(d, 'kind', d.get('kind', '') if isinstance(d, dict) else '')).lower() for d in primary}
    hard = sum(1 for d in primary if str(getattr(d, 'kind', d.get('kind', '') if isinstance(d, dict) else '')).lower() in {
        'undefined_command', 'missing_file', 'missing_begin_document',
        'missing_end_document', 'unbalanced_braces', 'environment_error',
        'fatal_error', 'package_error', 'encoding_error'
    })
    score = hard * 1000 + n * 100 + (0 if result.success else 10)
    return {
        'score': score,
        'primary_count': n,
        'hard_count': hard,
        'kinds': sorted(kinds),
        'diagnostics': primary,
        'findings': findings,
    }


def v12_progressed(before, after) -> bool:
    """Accept a candidate when it measurably improves the compiler state."""
    if after.get('score', 10**9) < before.get('score', 10**9):
        return True
    if after.get('hard_count', 10**9) < before.get('hard_count', 10**9):
        return True
    if after.get('primary_count', 10**9) < before.get('primary_count', 10**9):
        return True
    return False


def v12_verify_candidate(project, cfg, proposal, before_snapshot=None):
    """Apply, compile and accept *progress*, not only a perfect build.

    This is the central convergence upgrade: a repair that removes one root
    error but exposes a later error is retained. Only non-improving candidates
    are rolled back.
    """
    try:
        applied = apply_proposal(project, proposal, cfg)
    except Exception as exc:
        return False, None, f"repair apply exception: {type(exc).__name__}: {exc}", False
    if not applied.applied:
        return False, None, applied.reason, False

    try:
        verification = compile_once(project, cfg)
    except Exception as exc:
        return False, None, f"compiler exception: {type(exc).__name__}: {exc}", False

    if verification.success:
        return True, verification, "verified clean", True

    try:
        after = v12_diagnostic_snapshot(project, verification)
        before = before_snapshot or {'score': 10**9, 'hard_count': 10**9, 'primary_count': 10**9}
        if v12_progressed(before, after):
            delta = before.get('score', 0) - after.get('score', 0)
            return True, verification, f"partial progress accepted (score improvement {delta})", True
    except Exception as exc:
        v9_journal(project, 'progress_scoring_exception', exception=type(exc).__name__, message=str(exc))

    return False, verification, "candidate did not improve compiler state", False


# -----------------------------------------------------------------------------
# V11 adaptive repair strategies
# -----------------------------------------------------------------------------

def v11_make_package_candidates(project: ProjectInfo, findings: list[dict],
                                source: str, min_confidence: float = 0.90
                                ) -> list[RepairProposal]:
    """Generate transactionally testable package candidates even when the
    knowledge base has more than one possible package.

    Ambiguity is not treated as permission to guess: every candidate is tested
    in a transaction and rolled back if the compiler rejects it.
    """
    loaded = set(v7_extract_packages(source))
    proposals = []
    seen = set()

    for f in findings:
        if f.get("kind") != "undefined_command":
            continue
        cmd = v7_extract_unknown_command(f.get("evidence", ""), source)
        if not cmd or cmd in v7_defined_macros(source):
            continue
        candidates = [p for p in v7_package_candidates_for_command(cmd)
                      if p not in loaded]
        for pkg in candidates:
            if pkg in seen:
                continue
            new = v7_add_package_safely(source, pkg)
            if not new or new == source:
                continue
            seen.add(pkg)
            ambiguous = len(candidates) > 1
            proposals.append(RepairProposal(
                rule_id=f"V11_PROBE_PACKAGE_{pkg}_{cmd}",
                description=(
                    f"Probe package '{pkg}' for undefined '\\{cmd}'"
                    + (" (ambiguous mapping; transactional test)" if ambiguous else "")
                ),
                confidence=0.905 if ambiguous else 0.955,
                old_text=source,
                new_text=new,
                rationale=(
                    f"Compiler reported undefined '\\{cmd}'. "
                    f"Knowledge base candidates: {', '.join(candidates)}. "
                    "Candidate is never trusted without compilation verification."
                ),
            ))
    return proposals


def v11_remove_inputenc_for_xelatex(project: ProjectInfo) -> Optional[RepairProposal]:
    """Safe normalization: inputenc is obsolete with XeLaTeX/LuaLaTeX.
    Only remove an explicit inputenc declaration; no other source changes."""
    if project.engine.lower() not in {"xelatex", "lualatex"}:
        return None
    source = read_text(project.tex)
    pat = re.compile(
        r"^[ \t]*\\usepackage(?:\[[^\]]*\])?\{inputenc\}[ \t]*\r?\n?",
        re.I | re.M,
    )
    new, n = pat.subn("", source)
    if n == 0 or new == source:
        return None
    safe, _ = source_safety_check(source, new)
    if not safe:
        return None
    return RepairProposal(
        rule_id="V11_REMOVE_INPUTENC_XETEX",
        description="Remove obsolete inputenc package for XeLaTeX/LuaLaTeX",
        confidence=0.975,
        old_text=source,
        new_text=new,
        rationale="XeLaTeX/LuaLaTeX natively consume UTF-8; transactional verification decides acceptance.",
    )


def v11_missing_package_candidates(project: ProjectInfo, result_log: str,
                                   source: str) -> list[RepairProposal]:
    """Turn explicit '.sty not found' errors into transactional package probes
    using a conservative local package knowledge table."""
    proposals = []
    loaded = set(v7_extract_packages(source))
    for m in re.finditer(r"File `([^`]+)\.sty' not found", result_log, re.I):
        name = Path(m.group(1)).name
        if name in loaded:
            continue
        # Only probe package names that are syntactically safe and known to
        # TeX's conventional package naming. The compiler remains authoritative.
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            continue
        candidate = v7_add_package_safely(source, name)
        if candidate and candidate != source:
            proposals.append(RepairProposal(
                rule_id=f"V11_PROBE_MISSING_PACKAGE_{name}",
                description=f"Probe missing package '{name}'",
                confidence=0.935,
                old_text=source,
                new_text=candidate,
                rationale="Compiler explicitly reported the .sty file missing; insertion is tested transactionally.",
            ))
    return proposals



# =============================================================================
# V15 MEGA — persistent error taxonomy
# =============================================================================

class V15ErrorKnowledge:
    """
    Persistent taxonomy of compiler/runtime error signatures.

    It intentionally separates:
      * signature = reusable error type
      * occurrence = concrete instance
      * repair history = what happened when a repair was tried

    This is the learning substrate for future code-generation passes.
    """

    def __init__(self, project: ProjectInfo):
        self.root = project.root / ".latex_surgeon_internal"
        self.root.mkdir(parents=True, exist_ok=True)
        self.signatures_path = self.root / "error_signatures_v15.json"
        self.occurrences_path = self.root / "error_occurrences_v15.jsonl"
        self.discovery_path = self.root / "new_error_types_v15.jsonl"
        self.runtime_path = self.root / "runtime_failures_v15.jsonl"
        self.repair_path = self.root / "repair_learning_v15.jsonl"

        try:
            self.signatures = json.loads(
                self.signatures_path.read_text(encoding="utf-8")
            ) if self.signatures_path.exists() else {}
            if not isinstance(self.signatures, dict):
                self.signatures = {}
        except Exception:
            self.signatures = {}

    @staticmethod
    def normalize(text: str) -> str:
        s = text or ""
        s = re.sub(r"[A-Za-z]:[\\/][^ \n:]+", "<PATH>", s)
        s = re.sub(r"/[^ \n:]+", "<PATH>", s)
        s = re.sub(r"\b\d{2,}\b", "<N>", s)
        s = re.sub(r":\d+(?::\d+)?", ":<N>", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:V15_SIGNATURE_MAX_LEN]

    def signature(self, d: Diagnostic, context: str = "") -> str:
        family = getattr(d, "kind", "unknown")
        msg = self.normalize(getattr(d, "message", ""))
        context = self.normalize(context)

        # Stable semantic tokens are more useful than source line numbers.
        commands = sorted(set(re.findall(r"\\[A-Za-z@]+", context)))
        packages = sorted(set(
            re.findall(r"(?:Package|package)\s+([A-Za-z0-9_.-]+)", context, re.I)
        ))

        sig = f"{family}::{msg}"
        if commands:
            sig += "::cmd=" + ",".join(commands[:12])
        if packages:
            sig += "::pkg=" + ",".join(packages[:12])
        return sig[:V15_SIGNATURE_MAX_LEN]

    def observe(self, d: Diagnostic, project: ProjectInfo, context: str = "") -> tuple[str, bool]:
        sig = self.signature(d, context)
        now = datetime.now().isoformat(timespec="milliseconds")
        item = self.signatures.get(sig)
        is_new = item is None

        if item is None:
            item = {
                "signature": sig,
                "family": getattr(d, "kind", "unknown"),
                "first_seen": now,
                "last_seen": now,
                "occurrences": 0,
                "files": [],
                "engines": [],
                "severity": {},
                "sample_messages": [],
                "repair_rules": [],
                "solved": False,
            }
            self.signatures[sig] = item

        item["last_seen"] = now
        item["occurrences"] = int(item.get("occurrences", 0)) + 1

        name = str(project.tex)
        if name not in item.setdefault("files", []):
            item["files"].append(name)

        engine = project.engine
        if engine not in item.setdefault("engines", []):
            item["engines"].append(engine)

        sev = getattr(d, "severity", "unknown")
        item.setdefault("severity", {})
        item["severity"][sev] = item["severity"].get(sev, 0) + 1

        msg = getattr(d, "message", "")
        if msg and msg not in item.setdefault("sample_messages", []) and len(item["sample_messages"]) < 5:
            item["sample_messages"].append(msg)

        if V15_KEEP_ALL_OCCURRENCES:
            with self.occurrences_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": now,
                    "signature": sig,
                    "family": getattr(d, "kind", "unknown"),
                    "severity": sev,
                    "line": getattr(d, "line", None),
                    "message": msg,
                    "source": name,
                    "engine": engine,
                    "context": context[:4000],
                }, ensure_ascii=False, default=str) + "\n")

        if is_new:
            with self.discovery_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": now,
                    "signature": sig,
                    "family": getattr(d, "kind", "unknown"),
                    "message": msg,
                    "source": name,
                    "engine": engine,
                }, ensure_ascii=False, default=str) + "\n")

        return sig, is_new

    def save(self):
        tmp = self.signatures_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.signatures, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, self.signatures_path)

    def record_runtime(self, label: str, exc: BaseException, **context):
        try:
            with self.runtime_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": datetime.now().isoformat(timespec="milliseconds"),
                    "label": label,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                    "context": context,
                }, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def record_repair(self, payload: dict):
        try:
            with self.repair_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def stats(self):
        return {
            "unique_error_types": len(self.signatures),
            "total_occurrences": sum(
                int(x.get("occurrences", 0)) for x in self.signatures.values()
            ),
            "solved_types": sum(
                1 for x in self.signatures.values() if x.get("solved")
            ),
        }


# Run-level disease ledger.
# It is intentionally in-memory: persistent learning remains in the KB files,
# while the console receives only one compact end-of-run summary.
RUN_NEW_DISEASES: dict[str, dict] = {}
RUN_UNTREATED_DISEASES: dict[str, dict] = {}
RUN_RUNTIME_DISEASES: dict[str, dict] = {}


def reset_run_disease_ledger() -> None:
    RUN_NEW_DISEASES.clear()
    RUN_UNTREATED_DISEASES.clear()
    RUN_RUNTIME_DISEASES.clear()


def record_runtime_disease(project: Optional[ProjectInfo], label: str, exc: BaseException) -> None:
    """Classify internal Python failures as named diseases without exposing them
    as anonymous crashes. The complete traceback is already stored separately."""
    family = f"python_runtime_{type(exc).__name__.lower()}"
    message = re.sub(r"\s+", " ", str(exc)).strip()[:180]
    signature = hashlib.sha1(f"{family}|{label}|{message}".encode("utf-8", "replace")).hexdigest()[:16]
    item = RUN_RUNTIME_DISEASES.setdefault(signature, {
        "family": family,
        "component": label,
        "message": message,
        "occurrences": 0,
        "sources": set(),
    })
    item["occurrences"] += 1
    if project is not None:
        item["sources"].add(Path(project.tex).name)


def classify_diagnostic_family(kind: str, message: str, evidence: str = "") -> str:
    """Return a concrete disease family for every diagnostic; never expose an
    anonymous/unknown family. Existing classifier families have priority; if a
    parser produced no family, re-run the authoritative pattern KB against the
    combined evidence. As a final fallback, derive a stable message family so
    the next treatment-design pass still has an actionable diagnosis.
    """
    raw_kind = (kind or "").strip()
    if raw_kind and raw_kind.lower() not in {"unknown", "unclassified", "none", "null"}:
        return raw_kind
    text = f"{message or ''}\n{evidence or ''}"
    for family, pattern in V7_ERROR_PATTERNS:
        try:
            if pattern.search(text):
                return family
        except Exception:
            continue
    # Concrete deterministic fallback: this is still a named disease family,
    # not an "unknown" bucket, and the original message remains attached.
    compact = re.sub(r"[^a-z0-9]+", "_", (message or "latex_compiler_diagnostic").lower()).strip("_")
    compact = compact[:72] or "latex_compiler_diagnostic"
    return f"compiler_diagnostic_{compact}"


def record_unresolved_diseases(project: ProjectInfo, diagnostics: list[Diagnostic]) -> None:
    """Aggregate only diseases still present after the final authoritative build."""
    for d in diagnostics or []:
        msg = re.sub(r"\s+", " ", getattr(d, "message", "") or "").strip()
        family = classify_diagnostic_family(
            getattr(d, "kind", ""), msg, getattr(d, "evidence", "") or ""
        )
        signature = hashlib.sha1(f"{family}|{msg}".encode("utf-8", "replace")).hexdigest()[:16]
        item = RUN_UNTREATED_DISEASES.setdefault(signature, {
            "family": family, "message": msg[:180], "sources": set(), "occurrences": 0
        })
        item["sources"].add(Path(project.tex).name)
        item["occurrences"] += 1


def v15_quiet_observe(
    kb: V15ErrorKnowledge,
    project: ProjectInfo,
    diagnostics: list[Diagnostic],
    printed_this_run: set[str],
) -> int:
    new_count = 0

    for d in diagnostics:
        try:
            context = getattr(d, "evidence", "") or ""
            sig, is_new = kb.observe(d, project, context)
            if is_new:
                new_count += 1
                # IMPORTANT: never print one line per new occurrence.
                # A genuinely new ERROR TYPE is collected in the run ledger and
                # shown once, in the compact final report after ALL files finish.
                if sig not in printed_this_run:
                    printed_this_run.add(sig)
                    RUN_NEW_DISEASES.setdefault(sig, {
                        "number": len(RUN_NEW_DISEASES) + 1,
                        "family": getattr(d, "kind", "unknown"),
                        "message": getattr(d, "message", ""),
                        "source": str(project.tex),
                        "occurrences": 0,
                    })
                RUN_NEW_DISEASES[sig]["occurrences"] = int(
                    RUN_NEW_DISEASES[sig].get("occurrences", 0)
                ) + 1
        except Exception as exc:
            kb.record_runtime(
                "knowledge_observe",
                exc,
                source=str(project.tex),
            )

    try:
        kb.save()
    except Exception as exc:
        kb.record_runtime("knowledge_save", exc, source=str(project.tex))

    return new_count


def v15_forensic_diagnostics(
    project: ProjectInfo,
    result: BuildResult,
) -> list[Diagnostic]:
    """
    High-recall diagnostic merger.

    V14 already has multiple classifiers. V15 combines them and deduplicates
    semantically so one error repeated 500 times becomes one console event.
    """
    items: list[Diagnostic] = []

    try:
        profile = v7_document_profile(project)
    except Exception:
        profile = {}

    try:
        findings = v7_classify_log(result.log, profile)
    except Exception:
        findings = []

    try:
        base = diagnostics_from_log(project, result.log)
    except Exception:
        base = []

    try:
        base = detect_root_cause(project, base)
    except Exception:
        pass

    items.extend(base)

    for f in findings:
        try:
            items.append(Diagnostic(
                kind=classify_diagnostic_family(f.get("kind", ""), f.get("evidence", ""), f.get("evidence", "")),
                severity=f.get("severity", "error"),
                line=f.get("line"),
                message=f.get("evidence", ""),
                confidence=float(f.get("confidence", 0.0)),
                evidence=f.get("evidence", ""),
                secondary=bool(f.get("secondary", False)),
            ))
        except Exception:
            continue

    # Extra high-recall textual families.
    extra_patterns = [
        ("fatal_structure", r"(Runaway argument|File ended while scanning|Fatal error)"),
        ("resource_missing", r"(cannot find|not found|does not exist)"),
        ("generic_package_warning", r"Package .* Warning"),
        ("generic_latex_warning", r"LaTeX Warning"),
    ]

    lines = result.log.splitlines()
    for idx, line in enumerate(lines):
        for kind, pattern in extra_patterns:
            try:
                if not re.search(pattern, line, re.I):
                    continue
            except re.error:
                continue

            context = "\n".join(lines[max(0, idx-2):min(len(lines), idx+4)])
            items.append(Diagnostic(
                kind=kind,
                severity="warning" if "warning" in kind else "error",
                line=extract_error_line(line),
                message=line.strip(),
                evidence=context,
                confidence=0.80,
                secondary=False,
            ))
            break

    # Semantic deduplication.
    unique = {}
    for d in items:
        key = (
            getattr(d, "kind", "unknown"),
            V15ErrorKnowledge.normalize(getattr(d, "message", "")),
            V15ErrorKnowledge.normalize(getattr(d, "evidence", ""))[:500],
        )
        if key not in unique:
            unique[key] = d

    out = list(unique.values())
    out.sort(key=lambda x: (
        bool(getattr(x, "secondary", False)),
        -float(getattr(x, "confidence", 0.0)),
        getattr(x, "line", None) or 10**9,
    ))
    return out[:V15_MAX_DIAGNOSTICS_PER_PASS]


# =============================================================================
# V15.1 MEGA — Global Error Family Sweep
# =============================================================================

V151_GLOBAL_SWEEP_MIN_OCCURRENCES = 2
V151_GLOBAL_SWEEP_MIN_CONFIDENCE = 0.97
V151_GLOBAL_SWEEP_MAX_REPLACEMENTS = 5000
V151_GLOBAL_SWEEP_DENY = (
    "structural", "eof", "brace", "environment", "package", "dependency",
    "font", "bibliography", "reference", "inputenc", "bom", "encoding",
    "duplicate", "documentclass", "begin_document", "end_document",
)


def v151_patch_fingerprint(old_fragment: str, new_fragment: str) -> str:
    return hashlib.sha256(
        (old_fragment + "\x00" + new_fragment).encode("utf-8", errors="replace")
    ).hexdigest()[:24]


def v151_extract_local_patch(source: str, candidate: RepairProposal):
    """Extract one conservative local replacement from a whole-source proposal.

    Global sweep is deliberately disabled for structural insertions/deletions and
    multi-hunk edits. This prevents a useful local repair from becoming a blind
    global mutation.
    """
    try:
        matcher = difflib.SequenceMatcher(a=source, b=candidate.new_text, autojunk=False)
        ops = [op for op in matcher.get_opcodes() if op[0] != "equal"]
        if len(ops) != 1:
            return None
        tag, i1, i2, j1, j2 = ops[0]
        if tag != "replace" or i1 >= i2:
            return None
        old = source[i1:i2]
        new = candidate.new_text[j1:j2]
        if not old or old == new:
            return None
        return old, new
    except Exception:
        return None


def v151_should_globalize(candidate: RepairProposal, old: str, new: str, source: str) -> bool:
    rid = (candidate.rule_id or "").lower()
    desc = (candidate.description or "").lower()
    rationale = (candidate.rationale or "").lower()
    combined = " ".join((rid, desc, rationale))

    if any(x in combined for x in V151_GLOBAL_SWEEP_DENY):
        return False
    if candidate.confidence < V151_GLOBAL_SWEEP_MIN_CONFIDENCE:
        return False
    if source.count(old) < V151_GLOBAL_SWEEP_MIN_OCCURRENCES:
        return False
    if source.count(old) > V151_GLOBAL_SWEEP_MAX_REPLACEMENTS:
        return False

    # Global replacement should look like a local textual correction, not a
    # document-wide structural operation.
    if len(old) > 4000 or len(new) > 4000:
        return False
    if "\\begin{" in new or "\\end{" in new:
        return False
    if "\\usepackage" in new or "\\documentclass" in new:
        return False
    return True


def v151_globalize_candidate(
    project: ProjectInfo,
    source: str,
    candidate: RepairProposal,
    diagnostics: list[Diagnostic],
):
    """Turn a safe local correction into a whole-file family correction.

    Example: if a candidate fixes one occurrence of the exact bad token and the
    same token occurs 37 times, all 37 are changed in ONE transaction.
    """
    patch = v151_extract_local_patch(source, candidate)
    if not patch:
        return candidate, 1, False, "not a safe single-hunk local patch"

    old, new = patch
    count = source.count(old)
    if not v151_should_globalize(candidate, old, new, source):
        return candidate, 1, False, "global sweep safety gate rejected"

    # If diagnostics identify a concrete command, require that command to be
    # represented by the patch. This protects unrelated repeated text.
    commands = set()
    for d in diagnostics:
        cmd = getattr(d, "command", None)
        if cmd:
            commands.add(cmd)
    if commands and not any(cmd in old or cmd in new for cmd in commands):
        return candidate, 1, False, "diagnostic command not represented in patch"

    new_source = source.replace(old, new)
    if new_source == source:
        return candidate, 1, False, "no effective global change"

    fp = v151_patch_fingerprint(old, new)
    global_candidate = RepairProposal(
        rule_id=f"{candidate.rule_id}__GLOBAL_SWEEP_{fp}",
        description=(
            f"GLOBAL FAMILY SWEEP: {count} identical occurrences; "
            f"apply one verified transaction"
        ),
        confidence=min(0.999, candidate.confidence + 0.005),
        old_text=source,
        new_text=new_source,
        line=candidate.line,
        rationale=(
            candidate.rationale +
            f" | V15.1 global sweep: {count} exact occurrences"
        ),
        reversible=True,
    )
    return global_candidate, count, True, "global family sweep prepared"


def v151_family_inventory(source: str, diagnostics: list[Diagnostic]) -> list[dict]:
    """Count concrete source occurrences belonging to each diagnostic family."""
    families = defaultdict(lambda: {"count": 0, "commands": set(), "lines": set()})
    for d in diagnostics:
        fam = getattr(d, "kind", "unknown")
        item = families[fam]
        item["count"] += 1
        cmd = getattr(d, "command", None)
        if cmd:
            item["commands"].add(cmd)
        line = getattr(d, "line", None)
        if line:
            item["lines"].add(line)

    result = []
    for fam, item in families.items():
        result.append({
            "family": fam,
            "diagnostics": item["count"],
            "commands": sorted(item["commands"]),
            "lines": sorted(item["lines"]),
        })
    return sorted(result, key=lambda x: (-x["diagnostics"], x["family"]))


# =============================================================================
# V15 MEGA — complete replacement supervisor
# =============================================================================

def build_until_clean_v15(project: ProjectInfo, cfg: CompilerConfig) -> bool:
    """
    V15 policy:

    * Every configured stage runs unless the file is genuinely clean.
    * "No repair candidate" is NEVER a termination condition.
    * The same source state is not blindly mutated repeatedly.
    * Every source mutation is transactional and verified by the existing V12
      verifier.
    * New error signatures are harvested continuously.
    * One Python failure is isolated and recorded; the batch continues.
    * The final answer is based on a fresh authoritative compile.
    """
    say(f"Project: {project.tex.name}", "build")
    say(f"Engine: {project.engine}")
    say(f"Persian detected: {project.has_persian}")
    say("V15 MEGA Resilient Supervisor: ON", "info")
    say("20-stage maximum-diagnostic pipeline: ON", "info")
    say("NEW-error-only console: ON", "info")
    say("Persistent error taxonomy: ON", "info")
    say("Hidden Python Auto-Debug: ON", "info")
    say("Transactional rollback: ON", "info")
    say("Three-file batch isolation: ON", "info")

    try:
        memory = load_memory(project, cfg)
    except Exception:
        memory = {"version": 5, "rules": {}}

    kb = V15ErrorKnowledge(project)
    printed_types: set[str] = set()
    attempted: set[tuple[str, str]] = set()
    seen_states: set[str] = set()
    module_failures: dict[str, int] = {}
    mutation_count = 0
    new_types_total = 0
    repair_attempts = 0
    stall_count = 0
    last_result = None
    last_diagnostics: list[Diagnostic] = []
    last_proposals: list[RepairProposal] = []

    stage_names = [
        "baseline maximum-diagnostic scan", "root-cause + dependency intelligence",
        "structural source analysis", "package / command knowledge expansion",
        "font / encoding / Unicode analysis", "asset / reference / bibliography analysis",
        "batch independent repairs", "exploratory dependency candidates",
        "XeLaTeX encoding cleanup", "macro / command-context analysis",
        "environment dependency recovery", "reference / citation recovery",
        "bibliography / toolchain recovery", "package conflict / option analysis",
        "deep command-dependency sweep", "safe source normalization",
        "isolated single-candidate probes", "regression / secondary-error cleanup",
        "deep forensic recovery", "final recovery + evidence consolidation",
        "global error-family sweep", "cross-document knowledge replay",
        "runtime quarantine and checkpoint recovery", "semantic preservation guard",
        "regression matrix verification", "adaptive treatment laboratory",
    ]
    stage_names.extend(
        [f"adaptive treatment strategy {i:02d}" for i in range(1, V15_MAX_STAGES - len(stage_names) + 1)]
    )

    golden = create_run_snapshot(project, cfg, "run_start")
    self_preflight(project)
    watchdog_stop = self_run_watchdog(project, timeout=max(300, cfg.timeout * 2))
    self_heartbeat(
        project,
        "build_start",
        golden_backup=str(golden) if golden else None,
        max_stages=V15_MAX_STAGES,
    )

    def isolated(label, fn, *args, default=None, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            module_failures[label] = module_failures.get(label, 0) + 1
            try:
                self_exception_report(
                    project, label, exc,
                    failure_count=module_failures[label],
                )
            except Exception:
                pass
            kb.record_runtime(
                label, exc,
                source=str(project.tex),
                failure_count=module_failures[label],
            )
            record_runtime_disease(project, label, exc)
            try:
                v9_journal(
                    project,
                    "v15_module_exception",
                    module=label,
                    count=module_failures[label],
                    exception=type(exc).__name__,
                    message=str(exc),
                )
            except Exception:
                pass
            # Runtime failures are deliberately hidden from the normal console.
            # They remain fully recorded in .latex_surgeon_self for the next
            # development pass. The production user sees only the final
            # diagnosed disease handoff.
            return default

    stage_iter = range(1, V15_MAX_STAGES + 1)
    progress = _tqdm(stage_iter, total=V15_MAX_STAGES, desc="🩺 Surgical convergence", unit="stage", leave=True) if _tqdm else stage_iter
    for stage_no in progress:
        stage_name = stage_names[stage_no - 1] if stage_no <= len(stage_names) else f"adaptive treatment strategy {stage_no:02d}"
        with _SELF_LOCK:
            _SELF_STATE["stage"] = stage_no
            _SELF_STATE["stage_name"] = stage_name
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")

        self_heartbeat(
            project,
            "stage_start",
            stage=stage_no,
            stage_name=stage_name,
        )
        if _tqdm is None and stage_no in {1, 20, 40, 60}:
            print()
            say(f"STAGE {stage_no}/{V15_MAX_STAGES} — {stage_name}", "build")

        source = isolated(
            "source_reader",
            read_text,
            project.tex,
            default=None,
        )
        if source is None:
            continue

        state_hash = sha256_text(source)

        # Never trust stale evidence after a source mutation.
        if state_hash in seen_states and last_result is not None:
            result = last_result
            say("Reusing evidence for unchanged source state.", "scan")
        else:
            seen_states.add(state_hash)
            result = isolated(
                "compiler",
                compile_once,
                project,
                cfg,
                default=None,
            )
            if result is None:
                result = BuildResult(
                    False,
                    project.engine,
                    125,
                    "LATEX_SURGEON_COMPILER_MODULE_EXCEPTION",
                    elapsed=0.0,
                )
            last_result = result

        if result.success:
            say(
                f"BUILD CLEAN — {project.tex.name} ({result.elapsed:.2f}s)",
                "ok",
            )
            self_heartbeat(
                project,
                "build_end",
                clean=True,
                stage=stage_no,
                mutations=mutation_count,
                new_error_types=new_types_total,
            )
            watchdog_stop.set()
            return True

        # Dependency-first rule: if TeX explicitly says a package is missing,
        # silently install every missing package BEFORE source-level repairs.
        recovered_packages, failed_packages = recover_missing_packages_from_log(
            project, result.log
        )
        if recovered_packages:
            # Recompile immediately; do not waste a surgical stage on a problem
            # that the package manager itself can solve.
            refreshed = isolated("post-package-recovery compiler", compile_once, project, cfg, default=None)
            if refreshed is not None:
                result = refreshed
                last_result = refreshed
                if refreshed.success:
                    say(f"Package recovery completed — {recovered_packages} package(s) installed.", "ok")
                    self_heartbeat(project, "package_recovery_clean", packages=recovered_packages)
                    watchdog_stop.set()
                    return True

        diagnostics = isolated(
            "V15 forensic classifier",
            v15_forensic_diagnostics,
            project,
            result,
            default=[],
        ) or []

        last_diagnostics = diagnostics

        # Inventory is persisted even when no repair candidate exists. This is
        # how the next code-generation pass learns that one family appeared in
        # many places rather than seeing a wall of duplicate console errors.
        family_inventory = isolated(
            "family inventory",
            v151_family_inventory,
            source,
            diagnostics,
            default=[],
        ) or []
        try:
            v9_journal(
                project,
                "v151_family_inventory",
                stage=stage_no,
                families=family_inventory,
            )
        except Exception:
            pass

        new_types_total += v15_quiet_observe(
            kb,
            project,
            diagnostics,
            printed_types,
        )

        # Keep console quiet: show only counts, not repeated diagnostics.
        if _tqdm is None and stage_no in {1, 20, 40, 60}:
            say(f"Forensic scan checkpoint: {len(diagnostics)} diagnostics | KB={kb.stats()['unique_error_types']}", "scan")

        # Root-cause scorer.
        snapshot = isolated(
            "diagnostic scorer",
            v12_diagnostic_snapshot,
            project,
            result,
            default={
                "score": 10**9,
                "primary_count": 9999,
                "hard_count": 9999,
                "kinds": [],
            },
        )

        # Candidate planning from ALL available intelligence layers.
        findings = isolated(
            "v7 log classifier",
            v7_classify_log,
            result.log,
            isolated(
                "document profiler",
                v7_document_profile,
                project,
                default={},
            ),
            default=[],
        ) or []

        proposals: list[RepairProposal] = []

        planners = [
            ("legacy repair planner", propose_repairs, (project, diagnostics, result.log)),
            ("known dependency planner", v7_propose_known_dependency, (project, findings)),
            ("BOM planner", v7_propose_utf8_bom, (project,)),
            ("duplicate package planner", v7_propose_duplicate_package, (project,)),
        ]

        for label, fn, args in planners:
            value = isolated(label, fn, *args, default=[])
            if value:
                proposals.extend(
                    value if isinstance(value, list) else [value]
                )

        # Escalating exploration. These are still transactional.
        if stage_no >= 8:
            value = isolated(
                "dependency probes",
                v11_make_package_candidates,
                project,
                findings,
                source,
                max(0.86, cfg.min_repair_confidence - 0.08),
                default=[],
            )
            if value:
                proposals.extend(value)

        if stage_no >= 9:
            value = isolated(
                "XeLaTeX inputenc cleanup",
                v11_remove_inputenc_for_xelatex,
                project,
                default=None,
            )
            if value:
                proposals.append(value)

        if stage_no >= 14:
            value = isolated(
                "deep dependency sweep",
                v11_make_package_candidates,
                project,
                findings,
                source,
                0.84,
                default=[],
            )
            if value:
                proposals.extend(value)

        # Candidate gate + semantic deduplication.
        clean = []
        for p in proposals:
            try:
                if not isinstance(p, RepairProposal):
                    continue
                if p.new_text == source or p.old_text != source:
                    continue

                key = (state_hash, p.rule_id)
                probe = p.rule_id.startswith("V11_PROBE_")
                gate = (
                    0.84
                    if stage_no >= 14 and probe
                    else cfg.min_repair_confidence
                )

                if p.confidence >= gate and key not in attempted:
                    clean.append(p)
            except Exception as exc:
                kb.record_runtime(
                    "candidate_filter",
                    exc,
                    source=str(project.tex),
                    stage=stage_no,
                )

        unique = {}
        for p in clean:
            unique[p.new_text] = p
        proposals = sorted(
            unique.values(),
            key=lambda x: x.confidence,
            reverse=True,
        )

        # -------------------------------------------------------------
        # V15.1 GLOBAL ERROR FAMILY SWEEP
        # -------------------------------------------------------------
        # One diagnosis can have many physical occurrences. Before trying a
        # candidate, look for an exact, safe local patch and lift it to the
        # whole file. The entire family is then verified in ONE transaction.
        # -------------------------------------------------------------
        globalized = []
        sweep_total = 0
        for candidate in proposals:
            try:
                gp, occurrence_count, did_globalize, sweep_reason = (
                    v151_globalize_candidate(
                        project, source, candidate, diagnostics
                    )
                )
                if did_globalize:
                    sweep_total += occurrence_count
                    if _tqdm is None:
                        say(f"Global family sweep prepared: {occurrence_count} occurrences", "learn")
                    globalized.append(gp)
                else:
                    globalized.append(candidate)
            except Exception as exc:
                isolated(
                    "global family sweep",
                    lambda: (_ for _ in ()).throw(exc),
                    default=None,
                )
                globalized.append(candidate)

        # Prefer a global family repair over its one-occurrence counterpart.
        proposals = sorted(
            globalized,
            key=lambda x: ("__GLOBAL_SWEEP_" in x.rule_id, x.confidence),
            reverse=True,
        )
        last_proposals = proposals

        isolated(
            "failure evidence writer",
            v9_save_failure,
            project,
            stage_no,
            result,
            diagnostics,
            proposals,
            default=None,
        )

        if not proposals:
            stall_count += 1
            # This is deliberately NOT a return/break.
            if _tqdm is None and stage_no in {1, 20, 40, 60}:
                say("No safe candidate — escalating; error harvesting continues.", "warn")
            self_heartbeat(
                project,
                "stage_no_candidate",
                stage=stage_no,
                stalls=stall_count,
            )
            continue

        # Try candidates one at a time. The next stage always recompiles from
        # the newly accepted source state, preventing stale diagnostic stacking.
        stage_progress = False

        for candidate in proposals:
            if repair_attempts >= V15_MAX_REPAIR_ATTEMPTS_PER_RUN:
                break

            key = (state_hash, candidate.rule_id)
            if key in attempted:
                continue
            attempted.add(key)
            repair_attempts += 1

            if _tqdm is None:
                say(f"Repair probe: {candidate.rule_id} (confidence={candidate.confidence:.3f})", "fix")

            before = snapshot
            verified, verification, reason, changed = isolated(
                "candidate transaction",
                v12_verify_candidate,
                project,
                cfg,
                candidate,
                before,
                default=(
                    False,
                    None,
                    "candidate transaction isolated",
                    False,
                ),
            )

            payload = {
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "source": str(project.tex),
                "stage": stage_no,
                "rule_id": candidate.rule_id,
                "confidence": candidate.confidence,
                "verified": bool(verified),
                "reason": reason,
                "changed": bool(changed),
            }
            kb.record_repair(payload)

            if verified:
                mutation_count += 1
                stage_progress = True
                stall_count = 0

                memory = isolated(
                    "learning success",
                    v9_accept_learning,
                    project,
                    memory,
                    cfg,
                    candidate,
                    True,
                    {
                        "stage": stage_no,
                        "reason": reason,
                    },
                    default=memory,
                ) or memory

                if _tqdm is None:
                    say(f"Accepted: {reason}", "ok")
                self_heartbeat(
                    project,
                    "repair_accepted",
                    stage=stage_no,
                    rule_id=candidate.rule_id,
                    mutations=mutation_count,
                )
                break

            memory = isolated(
                "learning failure",
                v9_accept_learning,
                project,
                memory,
                cfg,
                candidate,
                False,
                {
                    "stage": stage_no,
                    "reason": reason,
                },
                default=memory,
            ) or memory

            # Exact rollback to the source state before this candidate.
            isolated(
                "rollback",
                write_text,
                project.tex,
                source,
                default=None,
            )

            if _tqdm is None:
                say(f"Rejected + rolled back: {reason}", "rollback")

        if not stage_progress:
            stall_count += 1
            if _tqdm is None and stage_no in {1, 20, 40, 60}:
                say("No measurable repair progress — escalating.", "warn")
        else:
            if _tqdm is None:
                say("Progress accepted — next stage exposes the next error layer.", "ok")

        self_heartbeat(
            project,
            "stage_end",
            stage=stage_no,
            progress=stage_progress,
            mutations=mutation_count,
            stalls=stall_count,
            new_error_types=new_types_total,
        )

    # ALWAYS perform a fresh final authoritative compilation.
    final_result = isolated(
        "final compiler",
        compile_once,
        project,
        cfg,
        default=None,
    )

    if final_result and final_result.success:
        say("FINAL STATUS: CLEAN", "ok")
        self_heartbeat(
            project,
            "build_end",
            clean=True,
            mutations=mutation_count,
            new_error_types=new_types_total,
        )
        watchdog_stop.set()
        return True

    say(
        "FINAL STATUS: NOT CLEAN — all configured stages completed; source preserved.",
        "warn",
    )

    if final_result:
        final_diags = isolated("final unresolved classifier", v15_forensic_diagnostics, project, final_result, default=[]) or []
        record_unresolved_diseases(project, final_diags)
        isolated(
            "final failure writer",
            v9_save_failure,
            project,
            V15_MAX_STAGES,
            final_result,
            last_diagnostics,
            last_proposals,
            default=None,
        )
        isolated(
            "final log writer",
            save_log,
            project,
            final_result.log,
            suffix="final_v15",
            default=None,
        )

    try:
        v9_journal(
            project,
            "v15_max_stages_completed",
            max_stages=V15_MAX_STAGES,
            final_clean=False,
            mutations=mutation_count,
            new_error_types=new_types_total,
            knowledge_base=kb.stats(),
        )
    except Exception:
        pass

    self_heartbeat(
        project,
        "build_end",
        clean=False,
        mutations=mutation_count,
        new_error_types=new_types_total,
    )
    watchdog_stop.set()
    return False


# =============================================================================
# V15.2 SURGICAL CONVERGENCE SUPERVISOR
# =============================================================================
# The previous V15 supervisor already performs Global Error Family Sweeps.
# V15.2 adds the missing "one execution" convergence rule:
#
#   one supervisor pass may repair many families;
#   if that pass changed the source but is not yet clean, immediately start
#   another complete diagnostic/repair pass in the SAME program execution.
#
# This prevents a hard ceiling of one repair per stage/pass.  The only normal
# stopping condition before BUILD CLEAN is: no source mutation occurred during
# the entire pass, meaning the current knowledge base has no safe treatment
# left.  The source remains at its best verified state.

V152_MAX_SURGICAL_PASSES = 250
V152_MAX_NO_PROGRESS_PASSES = 2

# Preserve the full V15 intelligence engine as the inner surgical procedure.
_v152_inner_supervisor = build_until_clean_v15


def build_until_clean_v152(project: ProjectInfo, cfg: CompilerConfig) -> bool:
    """Run repeated verified surgical passes until clean or genuinely stalled.

    A pass is allowed to discover and repair many error families.  When the
    source changes, the whole diagnostic pipeline is restarted immediately so
    newly exposed errors are treated in the same user invocation.

    Every mutation is still protected by the inner transactional verifier and
    backup mechanism.  Therefore repeated passes never replace the safety
    model with blind editing.
    """
    say("V15.2 SURGICAL CONVERGENCE: ON", "build")
    say("Global Error Family Sweep: ON", "learn")
    say("One execution = repeated diagnose → treat → verify cycles", "learn")
    say("Old verified errors remain fixed for the next execution", "learn")

    no_progress = 0
    previous_hash = None
    total_passes = 0

    # One golden backup protects the exact state entering the complete run.
    # Inner transactions create their own timestamped backups as well.
    try:
        golden = create_run_snapshot(project, cfg, "v152_run_start")
        if golden:
            say(f"Golden backup: {golden.name}", "info")
    except Exception as exc:
        self_exception_report(project, "v152_golden_backup", exc)

    for pass_no in range(1, V152_MAX_SURGICAL_PASSES + 1):
        total_passes = pass_no
        try:
            before = sha256_text(read_text(project.tex))
        except Exception as exc:
            self_exception_report(project, "v152_read_before_pass", exc)
            break

        if before == previous_hash:
            no_progress += 1
        else:
            no_progress = 0
        previous_hash = before

        print()
        say(
            f"SURGICAL PASS {pass_no}/{V152_MAX_SURGICAL_PASSES} — "
            "full forensic treatment",
            "build",
        )
        self_heartbeat(
            project,
            "v152_surgical_pass_start",
            pass_no=pass_no,
            max_passes=V152_MAX_SURGICAL_PASSES,
        )

        try:
            clean = _v152_inner_supervisor(project, cfg)
        except Exception as exc:
            # The hidden runtime debugger must not turn one Python failure into
            # a batch failure.  Record it and try one clean re-entry only when
            # the source was actually changed before the exception.
            self_exception_report(
                project,
                "v152_inner_supervisor",
                exc,
                pass_no=pass_no,
            )
            clean = False

        try:
            after = sha256_text(read_text(project.tex))
        except Exception as exc:
            self_exception_report(project, "v152_read_after_pass", exc)
            break

        changed = before != after

        try:
            v9_journal(
                project,
                "v152_surgical_pass_end",
                pass_no=pass_no,
                clean=bool(clean),
                source_changed=changed,
            )
        except Exception:
            pass

        if clean:
            say(
                f"SURGICAL CONVERGENCE COMPLETE after {pass_no} pass(es)",
                "ok",
            )
            self_heartbeat(
                project,
                "v152_converged",
                pass_no=pass_no,
                clean=True,
            )
            return True

        if changed:
            no_progress = 0
            say(
                "Source changed and was verified — immediately exposing the "
                "next error layer in the SAME execution.",
                "ok",
            )
            continue

        no_progress += 1
        say(
            "No source mutation in this complete pass — no safe known treatment "
            "remains; preserving the best verified source.",
            "warn",
        )

        # A second identical no-progress pass protects against transient tool
        # behavior without allowing an infinite loop.
        if no_progress >= V152_MAX_NO_PROGRESS_PASSES:
            break

    say(
        "SURGICAL CONVERGENCE STOPPED: unresolved diagnostics remain, but no "
        "verified mutation is available in the current knowledge base.",
        "warn",
    )
    say(
        "The unresolved error families have been retained for the next "
        "knowledge-base/code-generation pass.",
        "learn",
    )
    self_heartbeat(
        project,
        "v152_convergence_stalled",
        passes=total_passes,
    )
    return False


def v16_record_regression(project: ProjectInfo, before: str, after: str, clean: bool, passes: int) -> None:
    """Persist compact before/after evidence for future regression tests."""
    try:
        root = project.root / ".latex_surgeon_internal"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "regression_history_v16.jsonl"
        payload = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "source": str(project.tex),
            "before_hash": sha256_text(before),
            "after_hash": sha256_text(after),
            "changed": before != after,
            "clean": bool(clean),
            "passes": passes,
            "before_semantics": semantic_fingerprint(before),
            "after_semantics": semantic_fingerprint(after),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        self_exception_report(project, "regression_history", exc)


# V16 public convergence wrapper: record one complete execution as a reusable
# regression specimen while keeping V15.2's surgical engine unchanged.
_v16_surgical_engine = build_until_clean_v152



def run_biber(project: ProjectInfo) -> tuple[bool, str]:
    bcf = project.root / f"{project.tex.stem}.bcf"
    if not bcf.exists():
        return False, "no .bcf file"
    try:
        subprocess.run(["biber", project.tex.stem], cwd=project.root, check=True, timeout=60,
                       capture_output=True, text=True)
        return True, "biber ran successfully"
    except Exception as exc:
        return False, str(exc)



def compile_once_enhanced(project: ProjectInfo, cfg: CompilerConfig) -> BuildResult:
    start = time.perf_counter()
    cmd = [
        project.engine,
        "-interaction=nonstopmode",
        "-file-line-error",
        "-synctex=1",
    ]
    # اضافه کردن --shell-escape در صورت استفاده از biblatex
    source = read_text(project.tex)
    if re.search(r"\\usepackage(?:\\[[^\\]]*\\])?\\{biblatex\\}", source, re.I):
        cmd.append("--shell-escape")
    cmd.append(project.tex.name)

    try:
        p = subprocess.run(
            cmd,
            cwd=project.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout,
            shell=False,
        )
        log = p.stdout or ""
        pdf = project.tex.with_suffix(".pdf")
        success = p.returncode == 0 and pdf.exists()
        return BuildResult(
            success=success,
            engine=project.engine,
            returncode=p.returncode,
            log=log,
            pdf=pdf if pdf.exists() else None,
            elapsed=time.perf_counter() - start,
        )
    except Exception as exc:
        return BuildResult(
            success=False,
            engine=project.engine,
            returncode=125,
            log=f"COMPILE_ENHANCED_EXCEPTION: {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            elapsed=time.perf_counter() - start,
        )


def build_until_clean_v16(project: ProjectInfo, cfg: CompilerConfig) -> bool:
    before = read_text(project.tex)
    try:
        clean = _v16_surgical_engine(project, cfg)
    except Exception as exc:
        self_exception_report(project, "v16_surgical_engine", exc)
        clean = False
    try:
        after = read_text(project.tex)
    except Exception as exc:
        self_exception_report(project, "v16_final_read", exc)
        after = before
    v16_record_regression(project, before, after, clean, V152_MAX_SURGICAL_PASSES)
    return bool(clean)


# V16 is the production supervisor. Legacy/V15/V15.2 implementations remain
# available as internal fallback layers, but execution always enters V16.
build_until_clean = build_until_clean_v16

# V7 orchestration layer
# -----------------------------------------------------------------------------

def build_until_clean(project: ProjectInfo, cfg: CompilerConfig) -> bool:
    """V12 adaptive, self-healing, failure-tolerant supervisor.

    Key invariants:
      * Never stop merely because a stage has no candidate.
      * Never require a candidate to produce a clean build immediately.
      * Accept measurable progress and continue from the new state.
      * Retry candidates per *source state*, not globally forever.
      * Isolate every intelligence module and every transaction.
      * Use all 20 stages as genuinely cumulative escalation.
    """
    say(f"Project: {project.tex.name}", "build")
    say(f"Engine: {project.engine}")
    say(f"Persian detected: {project.has_persian}")
    say("V12 Adaptive Convergence Supervisor: ON", "info")
    say("20-stage escalation + adaptive progress acceptance: ON", "info")
    say("Maximum-diagnostic compilation: ON", "info")
    say("Batch independent repairs: ON", "info")
    say("Runtime isolation + module quarantine: ON", "info")
    say("Transactional rollback: ON", "info")
    say("Partial-progress acceptance: ON", "info")
    say("Learning memory: " + ("ON" if cfg.learn else "OFF"), "info")

    try:
        memory = load_memory(project, cfg)
    except Exception:
        memory = {"version": 3, "rules": {}}

    stage_names = [
        "baseline diagnostics", "root-cause + dependency intelligence",
        "structural source analysis", "package / command knowledge expansion",
        "font / encoding / Unicode analysis", "asset / reference / bibliography analysis",
        "batch repair + conflict resolution", "exploratory dependency candidates",
        "XeLaTeX encoding cleanup", "macro / command-context analysis",
        "environment dependency recovery", "reference / citation recovery",
        "bibliography / toolchain recovery", "package conflict / option analysis",
        "deep command-dependency sweep", "safe source normalization",
        "isolated single-candidate probes", "regression / secondary-error cleanup",
        "deep forensic recovery", "final recovery + evidence consolidation",
    ]

    golden = create_run_snapshot(project, cfg, "run_start")
    self_preflight(project)
    watchdog_stop = self_run_watchdog(project, timeout=max(300, cfg.timeout * 2))
    self_heartbeat(project, "build_start", golden_backup=str(golden) if golden else None, max_stages=cfg.max_rounds)

    failed_candidates: set[tuple[str, str]] = set()
    seen_states: set[str] = set()
    module_failures: dict[str, int] = {}
    last_result = None
    last_snapshot = None
    last_diagnostics: list[Diagnostic] = []
    last_proposals: list[RepairProposal] = []
    mutation_count = 0
    stall_count = 0

    def isolated(label, fn, *args, default=None):
        try:
            return fn(*args)
        except Exception as exc:
            module_failures[label] = module_failures.get(label, 0) + 1
            self_exception_report(project, label, exc, failure_count=module_failures[label])
            self_heartbeat(project, "module_quarantined", module=label, failure_count=module_failures[label])
            v9_journal(project, "module_exception", module=label,
                       count=module_failures[label], exception=type(exc).__name__,
                       message=str(exc), traceback=traceback.format_exc())
            try: say(f"{label} quarantined: {type(exc).__name__}: {exc}", "warn")
            except Exception: pass
            return default

    for stage_no in range(1, max(1, cfg.max_rounds) + 1):
        stage_name = stage_names[min(stage_no - 1, len(stage_names) - 1)]
        with _SELF_LOCK:
            _SELF_STATE["stage"] = stage_no
            _SELF_STATE["stage_name"] = stage_name
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")
        self_heartbeat(project, "stage_start", stage=stage_no, stage_name=stage_name)
        print()
        say(f"STAGE {stage_no}/{cfg.max_rounds} — {stage_name}", "build")
        v9_journal(project, "stage_start", stage=stage_no, stage_name=stage_name)

        source = isolated("source reader", read_text, project.tex, default=None)
        if source is None:
            say("Source could not be read; advancing without mutation.", "error")
            continue
        state_hash = sha256_text(source)

        if state_hash in seen_states and last_result is not None:
            result = last_result
            say("Reusing authoritative evidence for unchanged source state.", "scan")
        else:
            seen_states.add(state_hash)
            result = isolated("compiler", compile_once, project, cfg, default=None)
            if result is None:
                result = BuildResult(False, project.engine, 125,
                    "SHERAI_COMPILE_MODULE_EXCEPTION", elapsed=0.0)
            last_result = result

        if result.success:
            say(f"BUILD CLEAN — {project.tex.name} ({result.elapsed:.2f}s)", "ok")
            v9_journal(project, "build_clean", stage=stage_no, mutations=mutation_count)
            self_heartbeat(project, "build_end", clean=True, stage=stage_no, mutations=mutation_count)
            watchdog_stop.set()
            return True

        profile = isolated("document profiler", v7_document_profile, project, default={}) or {}
        findings = isolated("log classifier", v7_classify_log, result.log, profile, default=[]) or []
        diagnostics = isolated("legacy diagnostics", diagnostics_from_log, project, result.log, default=[]) or []
        diagnostics = isolated("root cause detector", detect_root_cause, project, diagnostics, default=diagnostics) or diagnostics

        existing = {(getattr(d, 'kind', None), getattr(d, 'line', None)) for d in diagnostics}
        for f in findings:
            try:
                key = (f.get('kind'), f.get('line'))
                if key not in existing:
                    diagnostics.append(Diagnostic(
                        kind=f.get('kind', 'unknown'), severity=f.get('severity', 'error'),
                        line=f.get('line'), message=f.get('evidence', ''),
                        confidence=f.get('confidence', 0.0), evidence=f.get('evidence', ''),
                        secondary=f.get('secondary', False)))
            except Exception as exc:
                v9_journal(project, 'diagnostic_merge_exception', exception=type(exc).__name__, message=str(exc))

        try: diagnostics.sort(key=lambda d: (-d.confidence, d.line or 10**9))
        except Exception: pass
        last_diagnostics = diagnostics
        for d in diagnostics[:40]:
            try:
                say(f"[{d.kind}][{d.severity}]" + (f" @ {d.line}" if d.line else '') +
                    f" confidence={d.confidence:.3f} :: {d.message[:260]}", "scan")
            except Exception: pass

        snapshot = isolated("diagnostic scorer", v12_diagnostic_snapshot, project, result,
                            default={'score': 10**9, 'primary_count': 9999, 'hard_count': 9999, 'kinds': []})
        last_snapshot = snapshot
        v9_journal(project, 'state_snapshot', stage=stage_no, state=state_hash,
                   score=snapshot.get('score'), primary_count=snapshot.get('primary_count'),
                   hard_count=snapshot.get('hard_count'))

        proposals: list[RepairProposal] = []
        planners = [
            ("legacy repair planner", propose_repairs, (project, diagnostics, result.log)),
            ("dependency planner", v7_propose_known_dependency, (project, findings)),
            ("BOM planner", v7_propose_utf8_bom, (project,)),
            ("duplicate package planner", v7_propose_duplicate_package, (project,)),
        ]
        for label, fn, args in planners:
            value = isolated(label, fn, *args, default=[])
            if value:
                proposals.extend(value if isinstance(value, list) else [value])

        if stage_no >= 8:
            value = isolated("exploratory dependency probes", v11_make_package_candidates,
                             project, findings, source, max(0.88, cfg.min_repair_confidence - .06), default=[])
            if value: proposals.extend(value)
        if stage_no >= 9:
            value = isolated("XeLaTeX inputenc normalizer", v11_remove_inputenc_for_xelatex, project, default=None)
            if value: proposals.append(value)
        if stage_no >= 10:
            value = isolated("missing package probes", v11_missing_package_candidates,
                             project, result.log, source, default=[])
            if value: proposals.extend(value)
        if stage_no >= 14:
            # Repeat package inference only after conservative stages have had
            # their chance; candidate verification is now progress-based.
            value = isolated("deep dependency sweep", v11_make_package_candidates,
                             project, findings, source, .88, default=[])
            if value: proposals.extend(value)

        # Late stages deliberately lower the gate slightly, but only for
        # explicitly probe-labelled candidates. This creates exploration without
        # turning the engine into a blind text mutator.
        clean = []
        for p in proposals:
            try:
                if not isinstance(p, RepairProposal) or p.new_text == source or p.old_text != source:
                    continue
                key = (state_hash, p.rule_id)
                probe = p.rule_id.startswith("V11_PROBE_")
                gate = .88 if (stage_no >= 8 and probe) else cfg.min_repair_confidence
                if p.confidence >= gate and key not in failed_candidates:
                    clean.append(p)
            except Exception:
                continue

        unique = {}
        for p in clean:
            unique[p.new_text] = p
        proposals = sorted(unique.values(), key=lambda p: p.confidence, reverse=True)
        last_proposals = proposals

        isolated("failure evidence writer", v9_save_failure,
                 project, stage_no, result, diagnostics, proposals, default=None)

        if not proposals:
            stall_count += 1
            say("No candidate at this stage; escalation continues.", "warn")
            v9_journal(project, 'stage_no_candidate', stage=stage_no, stall_count=stall_count)
            self_heartbeat(project, "stage_no_candidate", stage=stage_no, stall_count=stall_count)
            continue

        # Batch first. If it is not better, fall back to individual candidates.
        batch = isolated("batch merger", v9_merge_proposals, source, proposals, default=None)
        candidates = ([batch] if batch else []) + proposals
        stage_progress = False

        for candidate in candidates:
            key = (state_hash, candidate.rule_id)
            if key in failed_candidates:
                continue
            say(f"Candidate: {candidate.rule_id} (confidence={candidate.confidence:.3f})", "fix")
            before = snapshot
            ok, verification, reason, changed = isolated(
                "candidate transaction", v12_verify_candidate, project, cfg, candidate, before,
                default=(False, None, "transaction supervisor exception", False))
            if ok:
                mutation_count += 1
                stage_progress = True
                stall_count = 0
                memory = isolated("learning success", v9_accept_learning, project, memory, cfg,
                                  candidate, True, {'stage': stage_no, 'reason': reason}, default=memory) or memory
                say(f"Accepted: {reason}", "ok")
                v9_journal(project, 'repair_accepted', stage=stage_no, rule_id=candidate.rule_id,
                           partial=not (verification and verification.success), mutations=mutation_count)
                # Do not perform another candidate against stale source. The
                # next stage compiles the new authoritative state.
                break

            failed_candidates.add(key)
            memory = isolated("learning failure", v9_accept_learning, project, memory, cfg,
                              candidate, False, {'stage': stage_no, 'reason': reason}, default=memory) or memory
            # Transaction verifier leaves the candidate source in place on a
            # failed verification; restore exact pre-candidate source.
            isolated("rollback", write_text, project.tex, source, default=None)
            say(f"Rejected + rolled back: {reason}", "rollback")
            v9_journal(project, 'repair_rejected', stage=stage_no, rule_id=candidate.rule_id, reason=reason)
            self_heartbeat(project, "candidate_rejected", stage=stage_no, rule_id=candidate.rule_id, reason=reason)

        if not stage_progress:
            stall_count += 1
            say("Stage produced no measurable improvement; escalating.", "warn")
        else:
            say("Progress accepted; next stage will recompile the new state.", "ok")
        self_heartbeat(project, "stage_end", stage=stage_no, progress=stage_progress, mutations=mutation_count, stalls=stall_count)

    # Final authoritative compile regardless of whether the last state was seen
    # before. This avoids a stale cached result deciding the final verdict.
    final_result = isolated("final compiler", compile_once, project, cfg, default=None)
    if final_result and final_result.success:
        self_heartbeat(project, "build_end", clean=True, mutations=mutation_count, stalls=stall_count)
        watchdog_stop.set()
        say("FINAL STATUS: CLEAN", "ok")
        return True

    say("FINAL STATUS: NOT CLEAN — all configured stages completed; source preserved.", "warn")
    if final_result:
        isolated("final failure writer", v9_save_failure, project, cfg.max_rounds,
                 final_result, last_diagnostics, last_proposals, default=None)
        isolated("final log writer", save_log, project, final_result.log, suffix="final", default=None)
    self_heartbeat(project, "build_end", clean=False, mutations=mutation_count, stalls=stall_count)
    watchdog_stop.set()
    self_heartbeat(project, "build_end", clean=False, mutations=mutation_count, stalls=stall_count)
    watchdog_stop.set()
    v9_journal(project, 'max_stages_completed', max_stages=cfg.max_rounds,
               final_clean=False, mutations=mutation_count, stalls=stall_count)
    return False

# =============================================================================
# V14 MULTI-FILE BATCH SUPERVISOR
# =============================================================================

# These are the three production targets for the current She-rAI project.
# The list is deliberately explicit: no automatic discovery can accidentally
# select english.tex/about.tex/etc. instead of the intended final documents.
DEFAULT_BATCH_TARGETS = (
    Path(r"K:\kazemi\papers\poetry\She-rAI\SherAI_Paper_English_Final.tex"),
    Path(r"K:\kazemi\papers\poetry\She-rAI\sherai_guide_final.tex"),
    Path(r"K:\kazemi\papers\poetry\She-rAI\SherAI_Paper_Persian_Final.tex"),
)


def _safe_batch_record(base: Path, payload: dict) -> None:
    """Write a batch-level JSON record without ever interrupting the batch."""
    try:
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        write_text(
            base / f"batch_{stamp}.json",
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )
    except Exception as exc:
        # This is deliberately silent to the end user; self-debug captures it.
        try:
            self_exception_report(base.parent if base.parent.exists() else Path.cwd(),
                                  "batch_report_writer", exc, failure_count=1)
        except Exception:
            pass


def run_one_target(tex_path: Path, cfg: CompilerConfig, index: int, total: int) -> dict:
    """Run one complete transactional build. Never raises into the batch loop."""
    started = time.perf_counter()
    result = {
        "index": index,
        "total": total,
        "source": str(tex_path),
        "name": tex_path.name,
        "status": "NOT_STARTED",
        "clean": False,
        "elapsed": 0.0,
        "error": None,
    }

    try:
        tex_path = tex_path.expanduser().resolve()
        result["source"] = str(tex_path)
        result["name"] = tex_path.name

        if not tex_path.exists():
            result["status"] = "MISSING_SOURCE"
            result["error"] = "Source file does not exist."
            return result
        if tex_path.suffix.lower() != ".tex":
            result["status"] = "INVALID_TARGET"
            result["error"] = "Target is not a .tex file."
            return result

        say("", "info")
        print("=" * 78)
        say(f"BATCH TARGET {index}/{total}: {tex_path.name}", "build")
        say(f"Source: {tex_path}", "info")
        print("=" * 78)

        fonts = detect_fonts()
        print_font_report(fonts)

        project = make_project(tex_path, None, cfg)
        source_for_font_scan = read_text(tex_path)
        needs_korean, korean_font, korean_ok = detect_korean_font_requirement(source_for_font_scan)
        if needs_korean:
            if korean_ok:
                say(f"Korean text detected — font: {korean_font} [installed]", "font")
            else:
                say("Korean text detected — no Korean-capable font found; continuing and recording dependency.", "warn")
        result["engine"] = project.engine
        result["documentclass"] = project.documentclass
        result["has_persian"] = project.has_persian

        say(f"Engine: {project.engine}")
        say("Transactional backups: ON" if cfg.auto_backup else "Transactional backups: OFF")
        say("Per-file isolation: ON", "info")
        say("Failure in this file will NOT stop the next file.", "info")

        if not cfg.keep_build_files:
            cleanup_aux(project.root, project.tex.stem)

        ok = build_until_clean(project, cfg)
        result["clean"] = bool(ok)
        result["status"] = "BUILD_CLEAN" if ok else "NOT_CLEAN"
        return result

    except KeyboardInterrupt:
        # Do not let Ctrl+C become an accidental partial batch continuation.
        result["status"] = "INTERRUPTED"
        result["error"] = "Interrupted by user."
        return result
    except Exception as exc:
        result["status"] = "INTERNAL_ERROR_ISOLATED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        try:
            self_exception_report(
                tex_path.parent if tex_path.parent.exists() else Path.cwd(),
                "batch_target_supervisor",
                exc,
                failure_count=1,
            )
            v9_journal(
                tex_path.parent if tex_path.parent.exists() else Path.cwd(),
                "batch_target_exception",
                target=str(tex_path),
                exception=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
            )
        except Exception:
            pass
        return result
    finally:
        result["elapsed"] = round(time.perf_counter() - started, 3)


def print_compact_new_disease_report() -> None:
    """Print one compact handoff: unresolved diseases first, new types second."""
    print()
    print("=" * 78)
    print("🩺 LATEX SURGEON — TREATMENT HANDOFF / UNTREATED DISEASES")
    print("=" * 78)
    if RUN_UNTREATED_DISEASES:
        print(f"⚠️ Untreated disease types: {len(RUN_UNTREATED_DISEASES)}")
        print("ℹ️ Repeated occurrences are aggregated; console diagnostics remain quiet.")
        print("-")
        for i, item in enumerate(RUN_UNTREATED_DISEASES.values(), 1):
            sources = ", ".join(sorted(item["sources"]))
            print(f"🩹 #{i:03d} [{item['family']}] ×{item['occurrences']} — {sources}")
            if item.get("message"):
                print(f"    {item['message']}")
    else:
        print("🎉 No untreated disease remains after the final verified pass.")
    if RUN_RUNTIME_DISEASES:
        print("-")
        print(f"🧠 Python runtime disease families isolated: {len(RUN_RUNTIME_DISEASES)}")
        for i, item in enumerate(RUN_RUNTIME_DISEASES.values(), 1):
            sources = ", ".join(sorted(item["sources"]))
            print(f"🧩 R#{i:03d} [{item['family']}] ×{item['occurrences']} — {item['component']} — {sources}")
            if item.get("message"):
                print(f"    {item['message']}")
    print("-")
    print(f"🧬 New disease types discovered this run: {len(RUN_NEW_DISEASES)}")
    print("📌 Every item has a diagnosed disease family and evidence for the next treatment-design pass.")
    print("=" * 78)


def run_batch(targets: Iterable[Path], cfg: CompilerConfig) -> tuple[list[dict], int]:
    """Process every target independently and always continue to the next one."""
    targets = [Path(p).expanduser() for p in targets]
    total = len(targets)
    reports: list[dict] = []
    batch_started = time.perf_counter()
    reset_run_disease_ledger()

    print()
    print("#" * 78)
    print(f"🩺 LaTeX Surgeon v{VERSION} — PRODUCTION BATCH MODE")
    print("#" * 78)
    say(f"Targets: {total}", "build")
    say("Each .tex file has an independent transaction, backup, memory and failure boundary.", "info")
    say("A failed target NEVER terminates the batch.", "info")
    say("Every diagnostic is classified and harvested for the NEXT treatment-design pass.", "learn")
    say("Global family treatment + surgical convergence: ON", "learn")
    say("Repeated error occurrences stay silent on the console.", "learn")
    say("Each target is treated to convergence before the next target starts.", "learn")

    # One batch-level self-debug location, while each target keeps its own logs.
    batch_root = targets[0].parent / ".latex_surgeon_batch" if targets else Path.cwd() / ".latex_surgeon_batch"
    try:
        batch_root.mkdir(parents=True, exist_ok=True)
        self_heartbeat(batch_root, "batch_start", total=total, version=VERSION)
    except Exception:
        pass

    for i, target in enumerate(targets, 1):
        report = run_one_target(target, cfg, i, total)
        reports.append(report)

        # Human-readable checkpoint after EVERY file.
        status = report.get("status", "UNKNOWN")
        if status == "BUILD_CLEAN":
            say(f"BATCH CHECKPOINT {i}/{total}: CLEAN — {report.get('name')}", "ok")
        elif status == "NOT_CLEAN":
            say(f"BATCH CHECKPOINT {i}/{total}: NOT CLEAN — {report.get('name')}", "warn")
        else:
            say(f"BATCH CHECKPOINT {i}/{total}: {status} — {report.get('name')}", "error")
        say("Continuing to next target...", "info")

        try:
            self_heartbeat(batch_root, "target_end", **report)
        except Exception:
            pass

    clean_count = sum(1 for r in reports if r.get("clean"))
    failed_count = total - clean_count
    elapsed = round(time.perf_counter() - batch_started, 3)

    final_report = {
        "version": VERSION,
        "mode": "production_batch",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "clean": clean_count,
        "not_clean": failed_count,
        "elapsed_seconds": elapsed,
        "targets": reports,
    }

    try:
        batch_root.mkdir(parents=True, exist_ok=True)
        write_text(
            batch_root / "latest_batch_report.json",
            json.dumps(final_report, ensure_ascii=False, indent=2, default=str),
        )
        self_heartbeat(batch_root, "batch_end", total=total, clean=clean_count,
                       not_clean=failed_count, elapsed=elapsed)
    except Exception as exc:
        try:
            self_exception_report(batch_root, "batch_final_report", exc, failure_count=1)
        except Exception:
            pass

    print()
    print("#" * 78)
    print("🩺 LATEX SURGEON FINAL BATCH REPORT")
    print("#" * 78)
    for r in reports:
        icon = "✅" if r.get("clean") else "❌"
        print(f"{icon} {r.get('name')} — {r.get('status')} — {r.get('elapsed', 0):.2f}s")
        if r.get("error"):
            print(f"   {r['error']}")
    print("-" * 78)
    print(f"CLEAN: {clean_count}/{total}")
    print(f"NOT CLEAN / ISOLATED FAILURE: {failed_count}/{total}")
    print(f"TOTAL TIME: {elapsed:.2f}s")
    if clean_count == total and total > 0:
        print("🎉 COMPILE COMPLETED SUCCESSFULLY — ALL TARGETS VERIFIED CLEAN")
    else:
        print("⚠️ COMPILE FINISHED — SOME TARGETS STILL HAVE DIAGNOSED UNTREATED DISEASES")
    print("#" * 78)

    # One compact disease block is the handoff artifact for the next
    # code-generation pass. It deliberately appears only after ALL targets.
    print_compact_new_disease_report()

    # Nonzero means at least one production document still needs work, but the
    # batch has nevertheless completed ALL targets. Spyder may display this as
    # SystemExit: 1; that is a final batch status, never an internal crash.
    return reports, (0 if clean_count == total else 1)


def v15_startup_integrity_check():
    required = [
        "ProjectInfo", "CompilerConfig", "BuildResult",
        "RepairProposal", "V15ErrorKnowledge",
        "build_until_clean_v15", "build_until_clean_v152", "build_until_clean_v16", "run_batch",
        "v151_globalize_candidate", "v151_family_inventory"
    ]
    missing = [x for x in required if x not in globals()]
    if missing:
        raise RuntimeError("V15 startup integrity failure: " + ", ".join(missing))




# FINAL V19 OVERRIDE: production execution uses the complete adaptive surgical supervisor.
build_until_clean = build_until_clean_v16


def main() -> int:
    v15_startup_integrity_check()
    args = parse_args()

    print()
    print("=" * 78)
    print(f"🧠 {APP_NAME} v{VERSION}")
    print("=" * 78)

    cfg = CompilerConfig(
        max_rounds=max(1, args.rounds),
        timeout=max(30, args.timeout),
        min_repair_confidence=min(0.99, max(0.50, args.confidence)),
        auto_backup=not args.no_backup,
        learn=not args.no_learn,
        keep_build_files=args.keep_build,
    )

    # No positional path = the three production documents.
    if args.path is None:
        return run_batch(DEFAULT_BATCH_TARGETS, cfg)[1]

    # Explicit path remains available for laboratory/single-file debugging.
    target = Path(args.path).expanduser().resolve()
    try:
        tex = discover_main_tex(target)
    except Exception as exc:
        say(str(exc), "error")
        return 2

    report = run_one_target(tex, cfg, 1, 1)
    print()
    print("=" * 78)
    if report.get("clean"):
        say("FINAL STATUS: BUILD CLEAN", "ok")
        return 0
    say("FINAL STATUS: NOT CLEAN — source preserved", "error")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
