import importlib.util
import subprocess
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


def _load_mcp_service_module():
    path = Path("scripts/mcp_service.py")
    spec = importlib.util.spec_from_file_location("mcp_service_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MCPServiceManagerTests(unittest.TestCase):
    def test_start_launches_process_in_new_session_and_writes_pid(self):
        module = _load_mcp_service_module()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pid_file = root / "mcp.pid"
            log_file = root / "mcp.log"
            proc = Mock(pid=12345)

            args = Namespace(
                name="CLS",
                script="mcp_servers/cls_server.py",
                pid_file=str(pid_file),
                log_file=str(log_file),
                host="127.0.0.1",
                port=8003,
                python=".venv/bin/python",
                cwd=".",
                timeout=0.1,
            )

            with patch.object(module.subprocess, "Popen", return_value=proc) as popen, \
                patch.object(module, "_wait_for_ready", return_value=True), \
                patch.object(module, "_pid_running", return_value=False):
                status = module.start(args)

            self.assertEqual(status, 0)
            self.assertEqual(pid_file.read_text(encoding="utf-8"), "12345\n")
            _, kwargs = popen.call_args
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
            self.assertTrue(kwargs["close_fds"])
            self.assertTrue(kwargs["start_new_session"])

    def test_start_removes_stale_pid_before_launching(self):
        module = _load_mcp_service_module()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pid_file = root / "mcp.pid"
            log_file = root / "mcp.log"
            pid_file.write_text("98765\n", encoding="utf-8")
            proc = Mock(pid=12345)

            args = Namespace(
                name="Monitor",
                script="mcp_servers/monitor_server.py",
                pid_file=str(pid_file),
                log_file=str(log_file),
                host="127.0.0.1",
                port=8004,
                python=".venv/bin/python",
                cwd=".",
                timeout=0.1,
            )

            with patch.object(module.subprocess, "Popen", return_value=proc), \
                patch.object(module, "_wait_for_ready", return_value=True), \
                patch.object(module, "_pid_running", return_value=False):
                status = module.start(args)

            self.assertEqual(status, 0)
            self.assertEqual(pid_file.read_text(encoding="utf-8"), "12345\n")

    def test_status_uses_pid_and_tcp_readiness(self):
        module = _load_mcp_service_module()
        with TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "mcp.pid"
            pid_file.write_text("12345\n", encoding="utf-8")
            args = Namespace(
                name="CLS",
                pid_file=str(pid_file),
                host="127.0.0.1",
                port=8003,
            )

            output = StringIO()
            with patch.object(module, "_pid_running", return_value=True), \
                patch.object(module, "_tcp_open", return_value=True), \
                redirect_stdout(output):
                status = module.status(args)

            self.assertEqual(status, 0)
            self.assertIn("状态: 运行中", output.getvalue())
            self.assertIn("端口: ✅ 正常", output.getvalue())


if __name__ == "__main__":
    unittest.main()
