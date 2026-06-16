import subprocess
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class EnterpriseDashboardE11Tests(unittest.TestCase):
    def test_vue_dashboard_static_files_are_mountable(self):
        app = FastAPI()
        app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
        client = TestClient(app)

        html = client.get("/static/enterprise-dashboard.html")
        script = client.get("/static/enterprise-dashboard.js")
        styles = client.get("/static/enterprise-dashboard.css")

        self.assertEqual(html.status_code, 200, html.text)
        self.assertEqual(script.status_code, 200, script.text)
        self.assertEqual(styles.status_code, 200, styles.text)
        self.assertIn('id="e11-app"', html.text)
        self.assertIn("Vue3", html.text)
        self.assertIn("/static/enterprise-dashboard.js", html.text)
        self.assertIn("/static/enterprise-dashboard.css", html.text)

    def test_dashboard_sse_helpers_handle_chat_and_aiops_events(self):
        result = subprocess.run(
            ["node", "--test", "tests/js/test_enterprise_dashboard_e11.mjs"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
