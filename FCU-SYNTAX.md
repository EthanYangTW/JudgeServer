# FCU C editor sandbox

Build both judge containers from this JudgeServer fork. The syntax container uses
`FCU_SYNTAX_ONLY=1`; it never registers a heartbeat, rejects `/judge` and
`/compile_spj`, and accepts only authenticated `/ping`, `/check_c_syntax`, and
`/run_c`. The grading container uses the normal mode and does not expose either
editor endpoint.

| Container | Required environment | Private port | Writable mounts | Test cases |
| --- | --- | --- | --- | --- |
| `oj-judge` | `TOKEN`, `SERVICE_URL`, `BACKEND_URL` | 8080 | its own `/judger`, `/log`, `/tmp` | `/test_case:ro` |
| `oj-syntax` | `TOKEN`, `FCU_SYNTAX_ONLY=1` | 8080 | separate `/judger`, `/log`, `/tmp` | **No `/test_case` mount** |

Use the same private raw `TOKEN` in both containers and the backend's
`JUDGE_SERVER_TOKEN`. Set `FCU_SYNTAX_SERVER_URL=http://oj-syntax:8080/` on the
backend. Keep port 8080 on the private Compose network; do not publish it to
students or put the token in frontend code. The syntax service needs separate
volumes because its startup script clears `/judger`. A read-only root filesystem
with a writable `/tmp` tmpfs and the listed writable mounts is supported.

The backend sends `POST /check_c_syntax` with the
`X-Judge-Server-Token: sha256(TOKEN)` header and JSON `{"src":"C source"}`. A
valid check returns:

```json
{"err":null,"data":{"ok":true,"diagnostics":[]}}
```

Diagnostics have `line`, `column`, `severity` (`error`, `warning`, or `note`),
and `message`. A C syntax error returns `ok:false` with diagnostics. Invalid
input or compiler infrastructure failure returns an `err` value; the backend
should show a retryable service error rather than record a student score.
Source is limited to 16,000 UTF-8 bytes. The service invokes a fixed
`/usr/bin/gcc -fsyntax-only` command under the compiler UID with a 5-second CPU,
10-second real-time, 256 MiB memory, 16-process, and 64 KiB compiler-output
limit. It returns at most eight diagnostics of 300 characters each. No C binary
is linked or run by the syntax-check endpoint.

The editor's **Run** action sends `POST /run_c` with JSON `{"src":"C source",
"input":"custom stdin"}` through the authenticated backend. The sandbox
compiles a C17 program with fixed GCC arguments, then runs it with only the
student's supplied input under Judger's `c_cpp` seccomp profile, an unprivileged
UID, a 2-second CPU limit, 5-second wall limit, 128 MiB memory limit, one
process, and 64 KiB output limit. Source is limited to 16,000 UTF-8 bytes;
input is limited to 32,000 bytes. `status`, `stdout`, `stderr`, `exitCode`, and
`timeMs` are returned. Compile errors are visible to that student. This route
never reads hidden grading inputs or expected outputs, never assigns a score,
and cannot replace a formal submission.

Build prerequisite: initialize the pinned `Judger` submodule with
`git submodule update --init --recursive` before building the Docker image.
