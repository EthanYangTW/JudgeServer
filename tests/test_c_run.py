"""Tests for the isolated custom-input C runner."""

import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock


SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

from c_run import run_c_source  # noqa: E402


def fake_modules():
    judger = ModuleType("_judger")
    judger.RESULT_SUCCESS = 0
    judger.RESULT_CPU_TIME_LIMIT_EXCEEDED = 1
    judger.RESULT_REAL_TIME_LIMIT_EXCEEDED = 2
    judger.RESULT_MEMORY_LIMIT_EXCEEDED = 3
    judger.RESULT_RUNTIME_ERROR = 4
    judger.run = mock.Mock()
    config = ModuleType("config")
    config.COMPILER_GROUP_GID = 901
    config.COMPILER_LOG_PATH = "/log/compile.log"
    config.COMPILER_USER_UID = 901
    config.JUDGER_RUN_LOG_PATH = "/log/judger.log"
    config.RUN_GROUP_GID = 902
    config.RUN_USER_UID = 902
    return judger, config


class CRunTests(unittest.TestCase):
    def test_compile_and_run_use_fixed_sandbox_limits_and_custom_stdin(self):
        judger, config = fake_modules()

        def invoke(**kwargs):
            if kwargs["exe_path"] == "/usr/bin/gcc":
                Path(kwargs["args"][-1]).write_bytes(b"executable")
                Path(kwargs["output_path"]).write_text("", encoding="utf-8")
                return {"result": 0, "exit_code": 0}
            Path(kwargs["output_path"]).write_text("7\n", encoding="utf-8")
            Path(kwargs["error_path"]).write_text("", encoding="utf-8")
            return {"result": 0, "exit_code": 0, "real_time": 14}

        judger.run.side_effect = invoke
        with tempfile.TemporaryDirectory() as directory:
            source_path = os.path.join(directory, "answer.c")
            Path(source_path).write_text("int main(void){return 0;}", encoding="utf-8")
            with mock.patch.dict(sys.modules, {"_judger": judger, "config": config}), \
                    mock.patch("os.chown"), mock.patch("os.chmod"):
                result = run_c_source(source_path, directory, "7\n")
            self.assertEqual(result, {"status": "ok", "stdout": "7\n", "stderr": "",
                                      "exitCode": 0, "timeMs": 14})
            self.assertEqual(Path(directory, "stdin.txt").read_text(), "7\n")
            compile_call, run_call = [item.kwargs for item in judger.run.call_args_list]
            self.assertEqual(compile_call["exe_path"], "/usr/bin/gcc")
            self.assertIn("-std=c17", compile_call["args"])
            self.assertEqual(compile_call["uid"], 901)
            self.assertEqual(run_call["uid"], 902)
            self.assertEqual(run_call["seccomp_rule_name"], "c_cpp")
            self.assertEqual(run_call["input_path"], os.path.join(directory, "stdin.txt"))
            self.assertEqual(run_call["max_cpu_time"], 2000)
            self.assertEqual(run_call["max_real_time"], 5000)
            self.assertEqual(run_call["max_output_size"], 64 * 1024)
            self.assertEqual(run_call["max_process_number"], 1)

    def test_compile_error_returns_bounded_own_diagnostics_without_execution(self):
        judger, config = fake_modules()
        with tempfile.TemporaryDirectory() as directory:
            source_path = os.path.join(directory, "answer.c")
            Path(source_path).write_text("int main( {", encoding="utf-8")

            def invoke(**kwargs):
                Path(kwargs["output_path"]).write_text(source_path + ":1:11: error: expected ')'")
                return {"result": 4, "signal": 0, "exit_code": 1}

            judger.run.side_effect = invoke
            with mock.patch.dict(sys.modules, {"_judger": judger, "config": config}), \
                    mock.patch("os.chown"), mock.patch("os.chmod"):
                result = run_c_source(source_path, directory, "")
            self.assertEqual(result["status"], "compile_error")
            self.assertIn("answer.c:1:11", result["stderr"])
            self.assertNotIn(directory, result["stderr"])
            self.assertEqual(judger.run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
