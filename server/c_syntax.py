"""Bounded, compile-only C diagnostics for the classroom editor."""

import json
import os

from exception import JudgeClientError


MAX_SOURCE_BYTES = 16_000
MAX_DIAGNOSTIC_BYTES = 64 * 1024
MAX_DIAGNOSTICS = 8
MAX_MESSAGE_CHARS = 300


def parse_diagnostics(output, source_path):
    """Convert GCC's JSON diagnostics to a small editor-safe response."""
    try:
        items = json.loads(output.strip() or "[]")
    except (TypeError, ValueError):
        items = []
    if not isinstance(items, list):
        items = []

    diagnostics = []
    for item in items[:MAX_DIAGNOSTICS]:
        if not isinstance(item, dict):
            continue
        location = (item.get("locations") or [{}])[0]
        caret = location.get("caret", {}) if isinstance(location, dict) else {}
        if not isinstance(caret, dict):
            caret = {}
        severity = item.get("kind", "error")
        if severity not in ("error", "warning", "note"):
            severity = "error"
        message = str(item.get("message", "C syntax error"))
        message = message.replace(source_path, "answer.c")[:MAX_MESSAGE_CHARS]
        diagnostics.append({"line": max(0, int(caret.get("line", 0) or 0)),
                            "column": max(0, int(caret.get("column", 0) or 0)),
                            "severity": severity, "message": message})
    return diagnostics


def run_c_syntax(source_path, output_dir):
    """Run GCC's parser as the unprivileged compiler user; never execute student code."""
    import _judger
    from config import COMPILER_LOG_PATH, COMPILER_USER_UID, COMPILER_GROUP_GID

    output_path = os.path.join(output_dir, "syntax-diagnostics.json")
    result = _judger.run(
        max_cpu_time=5000,
        max_real_time=10000,
        max_memory=256 * 1024 * 1024,
        max_stack=64 * 1024 * 1024,
        max_output_size=MAX_DIAGNOSTIC_BYTES,
        max_process_number=16,
        exe_path="/usr/bin/gcc",
        input_path=source_path,
        output_path=output_path,
        error_path=output_path,
        args=["-fsyntax-only", "-std=c17", "-Wall", "-Wextra", "-Wno-unused-parameter",
              "-Werror=implicit-function-declaration", "-Werror=implicit-int",
              "-fdiagnostics-color=never", "-fdiagnostics-format=json", "-fmax-errors=8",
              source_path],
        env=["PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C"],
        log_path=COMPILER_LOG_PATH,
        seccomp_rule_name=None,
        uid=COMPILER_USER_UID,
        gid=COMPILER_GROUP_GID,
    )
    try:
        with open(output_path, "r", encoding="utf-8", errors="replace") as stream:
            output = stream.read(MAX_DIAGNOSTIC_BYTES + 1)
    except OSError:
        output = ""
    if len(output) > MAX_DIAGNOSTIC_BYTES:
        raise JudgeClientError("C compiler diagnostics exceeded the limit")

    diagnostics = parse_diagnostics(output, source_path)
    if result["result"] == _judger.RESULT_SUCCESS:
        return {"ok": True, "diagnostics": diagnostics}
    if (result["result"] == _judger.RESULT_RUNTIME_ERROR and
            result.get("signal", 0) == 0 and
            any(item["severity"] == "error" for item in diagnostics)):
        return {"ok": False, "diagnostics": diagnostics}
    raise JudgeClientError("C compiler temporarily unavailable")
