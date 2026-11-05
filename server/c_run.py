"""Bounded C17 execution against caller-provided standard input only."""

import os
import signal

from exception import JudgeClientError


MAX_SOURCE_BYTES = 16_000
MAX_INPUT_BYTES = 32_000
MAX_OUTPUT_BYTES = 64 * 1024
MAX_COMPILER_BYTES = 12 * 1024


def _read_text(path, limit, source_path=None):
    try:
        with open(path, "rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        return ""
    result = data[:limit].decode("utf-8", errors="replace")
    if source_path:
        result = result.replace(source_path, "answer.c")
    if len(data) > limit:
        result += "\n[output truncated]"
    return result


def run_c_source(source_path, workspace, stdin_text):
    """Compile and run as unprivileged users under the pinned Judger sandbox."""
    import _judger
    from config import (COMPILER_GROUP_GID, COMPILER_LOG_PATH, COMPILER_USER_UID,
                        JUDGER_RUN_LOG_PATH, RUN_GROUP_GID, RUN_USER_UID)

    exe_path = os.path.join(workspace, "answer")
    compile_output = os.path.join(workspace, "compile.txt")
    input_path = os.path.join(workspace, "stdin.txt")
    stdout_path = os.path.join(workspace, "stdout.txt")
    stderr_path = os.path.join(workspace, "stderr.txt")

    with open(input_path, "w", encoding="utf-8") as stream:
        stream.write(stdin_text)
    os.chown(input_path, RUN_USER_UID, RUN_GROUP_GID)
    os.chmod(input_path, 0o400)

    compile_result = _judger.run(
        max_cpu_time=5000,
        max_real_time=10000,
        max_memory=256 * 1024 * 1024,
        max_stack=64 * 1024 * 1024,
        # Judger applies this as RLIMIT_FSIZE to both diagnostics and the linked binary.
        max_output_size=4 * 1024 * 1024,
        max_process_number=32,
        exe_path="/usr/bin/gcc",
        input_path=source_path,
        output_path=compile_output,
        error_path=compile_output,
        args=["-DONLINE_JUDGE", "-O2", "-std=c17", "-Wall", "-Wextra",
              "-Wno-unused-parameter", "-fmax-errors=8", source_path,
              "-lm", "-o", exe_path],
        env=["PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C"],
        log_path=COMPILER_LOG_PATH,
        seccomp_rule_name=None,
        uid=COMPILER_USER_UID,
        gid=COMPILER_GROUP_GID,
    )
    if compile_result["result"] != _judger.RESULT_SUCCESS:
        if (compile_result["result"] == _judger.RESULT_RUNTIME_ERROR and
                compile_result.get("signal", 0) == 0):
            return {"status": "compile_error", "stdout": "",
                    "stderr": _read_text(compile_output, MAX_COMPILER_BYTES, source_path),
                    "exitCode": compile_result.get("exit_code", 1), "timeMs": 0}
        if compile_result["result"] in (_judger.RESULT_CPU_TIME_LIMIT_EXCEEDED,
                                        _judger.RESULT_REAL_TIME_LIMIT_EXCEEDED):
            return {"status": "compile_error", "stdout": "",
                    "stderr": "Compilation exceeded the time limit.",
                    "exitCode": None, "timeMs": 0}
        raise JudgeClientError("C compiler temporarily unavailable")
    if not os.path.isfile(exe_path):
        raise JudgeClientError("C compiler did not produce an executable")
    if os.path.getsize(exe_path) > 4 * 1024 * 1024:
        return {"status": "compile_error", "stdout": "",
                "stderr": "Compiled program exceeds the size limit.",
                "exitCode": None, "timeMs": 0}

    os.chown(exe_path, RUN_USER_UID, 0)
    os.chmod(exe_path, 0o500)
    run_result = _judger.run(
        max_cpu_time=2000,
        max_real_time=5000,
        max_memory=128 * 1024 * 1024,
        max_stack=64 * 1024 * 1024,
        max_output_size=MAX_OUTPUT_BYTES,
        max_process_number=1,
        exe_path=exe_path,
        input_path=input_path,
        output_path=stdout_path,
        error_path=stderr_path,
        args=[],
        env=["PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C"],
        log_path=JUDGER_RUN_LOG_PATH,
        seccomp_rule_name="c_cpp",
        uid=RUN_USER_UID,
        gid=RUN_GROUP_GID,
    )
    verdict = run_result["result"]
    if verdict == _judger.RESULT_SUCCESS:
        status = "ok"
    elif verdict in (_judger.RESULT_CPU_TIME_LIMIT_EXCEEDED,
                     _judger.RESULT_REAL_TIME_LIMIT_EXCEEDED):
        status = "time_limit"
    elif verdict == _judger.RESULT_MEMORY_LIMIT_EXCEEDED:
        status = "memory_limit"
    elif verdict == _judger.RESULT_RUNTIME_ERROR:
        oversized = any(os.path.isfile(path) and os.path.getsize(path) >= MAX_OUTPUT_BYTES
                        for path in (stdout_path, stderr_path))
        status = ("output_limit" if oversized or run_result.get("signal") == signal.SIGXFSZ
                  else "runtime_error")
    else:
        raise JudgeClientError("C runner temporarily unavailable")

    return {"status": status,
            "stdout": _read_text(stdout_path, MAX_OUTPUT_BYTES),
            "stderr": _read_text(stderr_path, MAX_OUTPUT_BYTES),
            "exitCode": run_result.get("exit_code"),
            "timeMs": max(0, int(run_result.get("real_time", 0)))}
