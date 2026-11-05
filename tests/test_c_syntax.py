"""Isolated tests for the classroom C syntax endpoint."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock


SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

from c_syntax import parse_diagnostics, run_c_syntax  # noqa: E402
from exception import JudgeClientError  # noqa: E402


class CSyntaxTests(unittest.TestCase):
    def test_gcc_json_is_bounded_and_maps_editor_positions(self):
        source_path = "/judger/run/private/answer.c"
        output = json.dumps([{"kind": "error", "message": source_path + ": expected ';'",
                              "locations": [{"caret": {"line": 4, "column": 9}}]}] * 12)
        diagnostics = parse_diagnostics(output, source_path)
        self.assertEqual(len(diagnostics), 8)
        self.assertEqual(diagnostics[0], {"line": 4, "column": 9, "severity": "error",
                                          "message": "answer.c: expected ';'"})

    def test_compiler_invocation_is_parse_only_and_resource_limited(self):
        fake_judger = ModuleType("_judger")
        fake_judger.RESULT_SUCCESS = 0
        fake_judger.RESULT_RUNTIME_ERROR = 4
        fake_judger.run = mock.Mock()
        fake_config = ModuleType("config")
        fake_config.COMPILER_LOG_PATH = "/log/compile.log"
        fake_config.COMPILER_USER_UID = 901
        fake_config.COMPILER_GROUP_GID = 901
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "answer.c")
            Path(source).write_text("int main(void) { return 0; }", encoding="utf-8")

            def run_judger(**kwargs):
                Path(kwargs["output_path"]).write_text("[]", encoding="utf-8")
                return {"result": fake_judger.RESULT_SUCCESS, "signal": 0}

            fake_judger.run.side_effect = run_judger
            with mock.patch.dict(sys.modules, {"_judger": fake_judger, "config": fake_config}):
                result = run_c_syntax(source, directory)
            self.assertEqual(result, {"ok": True, "diagnostics": []})
            args = fake_judger.run.call_args.kwargs
            self.assertEqual(args["exe_path"], "/usr/bin/gcc")
            self.assertIn("-fsyntax-only", args["args"])
            self.assertIn("-std=c17", args["args"])
            self.assertNotIn("-o", args["args"])
            self.assertEqual(args["max_cpu_time"], 5000)
            self.assertEqual(args["max_real_time"], 10000)
            self.assertEqual(args["max_memory"], 256 * 1024 * 1024)
            self.assertEqual(args["uid"], 901)
            self.assertEqual(args["gid"], 901)

    def test_syntax_error_is_not_infrastructure_error(self):
        fake_judger = ModuleType("_judger")
        fake_judger.RESULT_SUCCESS = 0
        fake_judger.RESULT_RUNTIME_ERROR = 4
        fake_judger.run = mock.Mock()
        fake_config = ModuleType("config")
        fake_config.COMPILER_LOG_PATH = "/log/compile.log"
        fake_config.COMPILER_USER_UID = 901
        fake_config.COMPILER_GROUP_GID = 901
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "answer.c")
            Path(source).write_text("int main( {", encoding="utf-8")

            def run_judger(**kwargs):
                Path(kwargs["output_path"]).write_text(json.dumps([
                    {"kind": "error", "message": "expected identifier", "locations": [
                        {"caret": {"line": 1, "column": 11}}]}
                ]), encoding="utf-8")
                return {"result": fake_judger.RESULT_RUNTIME_ERROR, "signal": 0}

            fake_judger.run.side_effect = run_judger
            with mock.patch.dict(sys.modules, {"_judger": fake_judger, "config": fake_config}):
                result = run_c_syntax(source, directory)
            self.assertFalse(result["ok"])
            self.assertEqual(result["diagnostics"][0]["line"], 1)

    def test_warning_does_not_fail_syntax_check(self):
        fake_judger = ModuleType("_judger")
        fake_judger.RESULT_SUCCESS = 0
        fake_judger.RESULT_RUNTIME_ERROR = 4
        fake_config = ModuleType("config")
        fake_config.COMPILER_LOG_PATH = "/log/compile.log"
        fake_config.COMPILER_USER_UID = 901
        fake_config.COMPILER_GROUP_GID = 901
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "answer.c")
            Path(source).write_text("int main(void) { int unused; return 0; }", encoding="utf-8")

            def run_judger(**kwargs):
                Path(kwargs["output_path"]).write_text(json.dumps([
                    {"kind": "warning", "message": "unused variable", "locations": [
                        {"caret": {"line": 1, "column": 22}}]}
                ]), encoding="utf-8")
                return {"result": fake_judger.RESULT_SUCCESS, "signal": 0}

            fake_judger.run = mock.Mock(side_effect=run_judger)
            with mock.patch.dict(sys.modules, {"_judger": fake_judger, "config": fake_config}):
                result = run_c_syntax(source, directory)
            self.assertTrue(result["ok"])
            self.assertEqual(result["diagnostics"][0]["severity"], "warning")

    def test_syntax_only_mode_requires_token_and_rejects_grading(self):
        fake_config = ModuleType("config")
        for key, value in {
            "JUDGER_WORKSPACE_BASE": "/judger/run", "SPJ_SRC_DIR": "/judger/spj",
            "SPJ_EXE_DIR": "/judger/spj", "COMPILER_USER_UID": 901,
            "SPJ_USER_UID": 903, "RUN_USER_UID": 902, "RUN_GROUP_GID": 902,
            "TEST_CASE_DIR": "/test_case"}.items():
            setattr(fake_config, key, value)
        fake_compiler = ModuleType("compiler")
        fake_compiler.Compiler = object
        fake_client = ModuleType("judge_client")
        fake_client.JudgeClient = object
        fake_utils = ModuleType("utils")
        fake_utils.token = "private-token-digest"
        fake_utils.logger = mock.Mock()
        fake_utils.server_info = lambda: {}
        fake_utils.ProblemIOMode = type("ProblemIOMode", (), {"standard": "Standard IO"})
        spec = importlib.util.spec_from_file_location("fcu_judge_server_test", SERVER_DIR / "server.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"FCU_SYNTAX_ONLY": "1"}), \
                mock.patch.dict(sys.modules, {"config": fake_config, "compiler": fake_compiler,
                                              "judge_client": fake_client, "utils": fake_utils}):
            spec.loader.exec_module(module)
        client = module.app.test_client()
        denied = client.post("/check_c_syntax", json={"src": "int x;"},
                             headers={"X-Judge-Server-Token": "wrong"}).get_json()
        self.assertEqual(denied["err"], "TokenVerificationFailed")
        with mock.patch.object(module.JudgeServer, "check_c_syntax",
                               return_value={"ok": True, "diagnostics": []}) as check:
            allowed = client.post("/check_c_syntax", json={"src": "int x;"},
                                  headers={"X-Judge-Server-Token": "private-token-digest"}).get_json()
        self.assertEqual(allowed, {"err": None, "data": {"ok": True, "diagnostics": []}})
        check.assert_called_once_with(src="int x;")
        self.assertEqual(client.post("/judge", json={}).get_json()["err"], "InvalidRequest")
        with mock.patch.object(module.JudgeServer, "run_c", return_value={
                "status": "ok", "stdout": "7\n", "stderr": "", "exitCode": 0, "timeMs": 12}) as run:
            allowed_run = client.post("/run_c", json={"src": "int main(void){return 0;}", "input": "7\n"},
                                      headers={"X-Judge-Server-Token": "private-token-digest"}).get_json()
        self.assertEqual(allowed_run["err"], None)
        run.assert_called_once_with(src="int main(void){return 0;}", input="7\n")
        with self.assertRaises(JudgeClientError):
            module.JudgeServer.run_c("int main(void){return 0;}", "x" * 32_001)
        with self.assertRaises(JudgeClientError):
            module.JudgeServer.check_c_syntax("x" * 16_001)


if __name__ == "__main__":
    unittest.main()
