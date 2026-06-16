import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
from app.enterprise.auth.service import auth_service


def build_auth_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    return app


class EnterpriseAuthTests(unittest.TestCase):
    def setUp(self):
        auth_service.clear_blacklist()
        self.client = TestClient(build_auth_app())

    def _login(self, username: str = "admin", password: str = "Admin123!") -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["access_token"]

    def test_protected_api_requires_authentication(self):
        response = self.client.get("/api/auth/protected")

        self.assertEqual(response.status_code, 401)

    def test_login_success_returns_access_token_and_user_profile(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "Admin123!"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["code"], 200)
        self.assertEqual(payload["message"], "success")
        self.assertEqual(payload["data"]["token_type"], "bearer")
        self.assertTrue(payload["data"]["access_token"])
        self.assertEqual(payload["data"]["user"]["user_id"], "user_admin")
        self.assertEqual(payload["data"]["user"]["department_id"], "system")
        self.assertEqual(payload["data"]["user"]["roles"], ["admin"])

    def test_login_wrong_password_returns_401(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401)

    def test_protected_request_gets_user_department_roles_and_trace_id(self):
        token = self._login()

        response = self.client.get(
            "/api/auth/protected",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": "trace-e1-test",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["user_id"], "user_admin")
        self.assertEqual(data["department_id"], "system")
        self.assertEqual(data["roles"], ["admin"])
        self.assertEqual(data["trace_id"], "trace-e1-test")

    def test_me_returns_current_user_profile_and_trace_id(self):
        token = self._login("demo_user_dept1", "Demo123!")

        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["user"]["user_id"], "user_demo_dept1")
        self.assertEqual(data["user"]["department_id"], "dept_1")
        self.assertEqual(data["user"]["roles"], ["user"])
        self.assertTrue(data["trace_id"])

    def test_logout_blacklists_token(self):
        token = self._login()

        logout_response = self.client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(logout_response.status_code, 200, logout_response.text)

        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        user = auth_service.authenticate("admin", "Admin123!")
        token = auth_service.create_access_token(user, expires_delta_seconds=-1)

        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
