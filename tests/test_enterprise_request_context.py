import asyncio
import unittest

from app.enterprise.context import (
    RequestContext,
    clear_current_request_context,
    get_current_request_context,
    reset_current_request_context,
    set_current_request_context,
)


class EnterpriseRequestContextTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        clear_current_request_context()

    async def test_request_context_is_isolated_per_async_task(self):
        async def run_with_context(trace_id: str) -> str:
            token = set_current_request_context(
                RequestContext(
                    request_id=f"request-{trace_id}",
                    trace_id=trace_id,
                    user_id=f"user-{trace_id}",
                    username=f"name-{trace_id}",
                    department_id="dept",
                    department_name="Department",
                    roles=["user"],
                )
            )
            try:
                await asyncio.sleep(0)
                return get_current_request_context().trace_id
            finally:
                reset_current_request_context(token)

        trace_a, trace_b = await asyncio.gather(
            run_with_context("trace-a"),
            run_with_context("trace-b"),
        )

        self.assertEqual(trace_a, "trace-a")
        self.assertEqual(trace_b, "trace-b")
        self.assertIsNone(get_current_request_context())

    async def test_clear_current_request_context_removes_context(self):
        set_current_request_context(
            RequestContext(
                request_id="request-1",
                trace_id="trace-1",
                user_id="user-1",
                username="name-1",
                department_id="dept-1",
                department_name="Department 1",
                roles=["admin"],
            )
        )

        self.assertEqual(get_current_request_context().trace_id, "trace-1")

        clear_current_request_context()

        self.assertIsNone(get_current_request_context())


if __name__ == "__main__":
    unittest.main()
