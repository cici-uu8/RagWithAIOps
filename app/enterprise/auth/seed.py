"""Deterministic local seed users for E1 development."""

from app.enterprise.auth.models import SeedUser

SEED_USERS_BY_USERNAME: dict[str, SeedUser] = {
    "admin": SeedUser(
        user_id="user_admin",
        username="admin",
        password="Admin123!",
        department_id="system",
        department_name="System",
        roles=["admin"],
    ),
    "demo_user_dept1": SeedUser(
        user_id="user_demo_dept1",
        username="demo_user_dept1",
        password="Demo123!",
        department_id="dept_1",
        department_name="Department 1",
        roles=["user"],
    ),
}
