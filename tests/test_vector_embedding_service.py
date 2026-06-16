"""DashScope embeddings batch-level retry + per-embedder token cap tests.

Layer 1 — retry (added 2026-05-20 after P6 trigger eval first run hit
`openai.APITimeoutError` mid-corpus-indexing). Retry sits BETWEEN the OpenAI
SDK's internal retries and our RuntimeError wrap, so a transient batch
failure no longer fails the whole eval.

Layer 2 — token cap pre-truncation (added 2026-05-21, S2 of WeKnora port).
Pathological queries / chunking regressions / new content paths can produce
texts past DashScope text-embedding-v4's 8192-token window. Client-side
pre-truncation (chars_for_token_limit @ 8192 with 0.9 safety) keeps any single
batch from being rejected with `400 Range of input length should be ...`.
Server-side truncation is unavailable in OpenAI-compat mode, so this is
defensive only — chunker still owns the upstream budget.

Frozen retry behavior:
- Each batch makes up to 3 attempts (1 initial + 2 retries).
- Retry on transient: APITimeoutError, APIConnectionError, InternalServerError,
  RateLimitError.
- Fail-fast (no retry) on permanent: AuthenticationError, BadRequestError,
  PermissionDeniedError, NotFoundError, etc.
- Exponential backoff between attempts: 2s, 4s.
- Order of embeddings is preserved across batches even when an interior batch retries.
- embed_query gets the same retry coverage as embed_documents.

Frozen token-cap behavior:
- Cap = chars_for_token_limit(8192, detected_language(text)). Per-text, NOT
  per-batch — different batch members can have different budgets.
- Truncation is silent below the cap and emits a WARNING above it (with
  original / truncated lengths).
- Truncation runs BEFORE the OpenAI client call, so the API never sees the
  oversized payload regardless of retry attempts.
"""

import unittest
from unittest.mock import MagicMock, patch

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from app.services.token_estimator import (
    LANG_CHINESE,
    LANG_ENGLISH,
    chars_for_token_limit,
)
from app.services.vector_embedding_service import (
    EMBEDDER_MAX_TOKENS,
    DashScopeEmbeddings,
)


def _embedding_response(n_items: int, dim: int = 1024) -> MagicMock:
    response = MagicMock()
    response.data = [MagicMock(embedding=[float(i)] * dim) for i in range(n_items)]
    return response


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(request=MagicMock())


def _connection_error() -> APIConnectionError:
    return APIConnectionError(message="connection blip", request=MagicMock())


def _server_error() -> InternalServerError:
    response = MagicMock()
    response.status_code = 500
    response.headers = {}
    return InternalServerError(message="server hiccup", response=response, body=None)


def _rate_limit_error() -> RateLimitError:
    response = MagicMock()
    response.status_code = 429
    response.headers = {}
    return RateLimitError(message="too fast", response=response, body=None)


def _auth_error() -> AuthenticationError:
    response = MagicMock()
    response.status_code = 401
    response.headers = {}
    return AuthenticationError(message="bad key", response=response, body=None)


def _bad_request_error() -> BadRequestError:
    response = MagicMock()
    response.status_code = 400
    response.headers = {}
    return BadRequestError(message="bad input", response=response, body=None)


class EmbeddingsRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Build with a non-empty fake key to bypass the init-time guard, then replace
        # the OpenAI client with a MagicMock for full control over .embeddings.create.
        self.inst = DashScopeEmbeddings(
            api_key="sk-fake-test-key-1234567890", model="text-embedding-v4", dimensions=1024
        )
        self.mock_create = MagicMock()
        self.inst.client = MagicMock()
        self.inst.client.embeddings.create = self.mock_create

        sleep_patch = patch("app.services.vector_embedding_service.time.sleep")
        self.sleep_mock = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_happy_path_no_retry(self):
        self.mock_create.return_value = _embedding_response(3)
        result = self.inst.embed_documents(["a", "b", "c"])
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]), 1024)
        self.assertEqual(self.mock_create.call_count, 1)
        self.sleep_mock.assert_not_called()

    def test_empty_input_no_call(self):
        result = self.inst.embed_documents([])
        self.assertEqual(result, [])
        self.mock_create.assert_not_called()
        self.sleep_mock.assert_not_called()

    def test_transient_timeout_once_succeeds_on_retry(self):
        self.mock_create.side_effect = [_timeout_error(), _embedding_response(1)]
        result = self.inst.embed_documents(["a"])
        self.assertEqual(len(result), 1)
        self.assertEqual(self.mock_create.call_count, 2)
        self.assertEqual(self.sleep_mock.call_count, 1)

    def test_transient_timeout_twice_succeeds_on_third(self):
        self.mock_create.side_effect = [
            _timeout_error(),
            _timeout_error(),
            _embedding_response(1),
        ]
        result = self.inst.embed_documents(["a"])
        self.assertEqual(len(result), 1)
        self.assertEqual(self.mock_create.call_count, 3)
        self.assertEqual(self.sleep_mock.call_count, 2)

    def test_transient_timeout_exhausts_retries_raises(self):
        self.mock_create.side_effect = [
            _timeout_error(),
            _timeout_error(),
            _timeout_error(),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            self.inst.embed_documents(["a"])
        self.assertEqual(self.mock_create.call_count, 3)
        self.assertEqual(self.sleep_mock.call_count, 2)  # no sleep after final attempt
        self.assertIn("批量嵌入失败", str(ctx.exception))

    def test_authentication_error_fails_fast_no_retry(self):
        self.mock_create.side_effect = _auth_error()
        with self.assertRaises(RuntimeError):
            self.inst.embed_documents(["a"])
        self.assertEqual(self.mock_create.call_count, 1)
        self.sleep_mock.assert_not_called()

    def test_bad_request_fails_fast_no_retry(self):
        self.mock_create.side_effect = _bad_request_error()
        with self.assertRaises(RuntimeError):
            self.inst.embed_documents(["a"])
        self.assertEqual(self.mock_create.call_count, 1)
        self.sleep_mock.assert_not_called()

    def test_retry_on_connection_error(self):
        self.mock_create.side_effect = [_connection_error(), _embedding_response(1)]
        result = self.inst.embed_documents(["a"])
        self.assertEqual(len(result), 1)
        self.assertEqual(self.mock_create.call_count, 2)

    def test_retry_on_internal_server_error(self):
        self.mock_create.side_effect = [_server_error(), _embedding_response(1)]
        result = self.inst.embed_documents(["a"])
        self.assertEqual(len(result), 1)
        self.assertEqual(self.mock_create.call_count, 2)

    def test_retry_on_rate_limit_error(self):
        self.mock_create.side_effect = [_rate_limit_error(), _embedding_response(1)]
        result = self.inst.embed_documents(["a"])
        self.assertEqual(len(result), 1)
        self.assertEqual(self.mock_create.call_count, 2)

    def test_exponential_backoff_2s_then_4s(self):
        self.mock_create.side_effect = [
            _timeout_error(),
            _timeout_error(),
            _embedding_response(1),
        ]
        self.inst.embed_documents(["a"])
        sleeps = [call.args[0] for call in self.sleep_mock.call_args_list]
        self.assertEqual(sleeps, [2, 4])

    def test_only_failing_batch_retries_order_preserved(self):
        """25 docs split into 3 batches (10+10+5). Middle batch fails once
        then succeeds. Final embeddings must be in batch order [b1, b2, b3]
        with exactly one extra call attributable to the middle batch."""
        b1, b2, b3 = (
            _embedding_response(10),
            _embedding_response(10),
            _embedding_response(5),
        )
        self.mock_create.side_effect = [b1, _timeout_error(), b2, b3]
        result = self.inst.embed_documents(["doc"] * 25)
        self.assertEqual(len(result), 25)
        # 4 calls total (1 + 2 + 1); only the middle batch retried.
        self.assertEqual(self.mock_create.call_count, 4)
        # First 10 from b1, next 10 from b2 (post-retry), last 5 from b3.
        self.assertEqual(result[0], b1.data[0].embedding)
        self.assertEqual(result[10], b2.data[0].embedding)
        self.assertEqual(result[20], b3.data[0].embedding)

    def test_embed_query_also_retries(self):
        self.mock_create.side_effect = [_timeout_error(), _embedding_response(1)]
        result = self.inst.embed_query("question text")
        self.assertEqual(len(result), 1024)
        self.assertEqual(self.mock_create.call_count, 2)

    def test_embed_query_exhausts_retries_raises(self):
        self.mock_create.side_effect = [
            _timeout_error(),
            _timeout_error(),
            _timeout_error(),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            self.inst.embed_query("question text")
        self.assertEqual(self.mock_create.call_count, 3)
        self.assertIn("查询嵌入失败", str(ctx.exception))


class EmbeddingsTokenCapTests(unittest.TestCase):
    """Pre-truncation against the DashScope text-embedding-v4 8192-token window."""

    def setUp(self) -> None:
        self.inst = DashScopeEmbeddings(
            api_key="sk-fake-test-key-1234567890", model="text-embedding-v4", dimensions=1024
        )
        self.mock_create = MagicMock()
        self.inst.client = MagicMock()
        self.inst.client.embeddings.create = self.mock_create

        sleep_patch = patch("app.services.vector_embedding_service.time.sleep")
        self.sleep_mock = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_max_tokens_constant_is_8192(self):
        # Frozen: text-embedding-v4 documented input limit.
        self.assertEqual(EMBEDDER_MAX_TOKENS, 8192)

    def test_short_text_passed_through_unchanged(self):
        self.mock_create.return_value = _embedding_response(1)
        text = "short query"
        self.inst.embed_documents([text])
        sent = self.mock_create.call_args.kwargs["input"]
        self.assertEqual(sent, [text])

    def test_oversize_english_truncated_to_char_budget(self):
        self.mock_create.return_value = _embedding_response(1)
        # English budget at 8192 tokens: 8192 * 4.0 * 0.9 = 29491 chars.
        en_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_ENGLISH)
        oversize = "x" * (en_budget + 5000)
        self.inst.embed_documents([oversize])
        sent = self.mock_create.call_args.kwargs["input"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]), en_budget)
        # Truncation preserves the prefix.
        self.assertTrue(oversize.startswith(sent[0]))

    def test_oversize_chinese_uses_smaller_char_budget(self):
        # Chinese ratio is 1.7 vs english 4.0; same token budget → ~2.4× fewer chars.
        self.mock_create.return_value = _embedding_response(1)
        zh_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_CHINESE)
        oversize = "中" * (zh_budget + 1000)
        self.inst.embed_documents([oversize])
        sent = self.mock_create.call_args.kwargs["input"]
        self.assertEqual(len(sent[0]), zh_budget)
        # Sanity: zh budget should be much smaller than en budget at same token cap.
        en_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_ENGLISH)
        self.assertLess(zh_budget, en_budget)

    def test_per_text_budget_in_mixed_batch(self):
        """Each text gets its own language-detected budget, not a batch-wide one."""
        self.mock_create.return_value = _embedding_response(2)
        en_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_ENGLISH)
        zh_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_CHINESE)
        en_oversize = "x" * (en_budget + 1000)
        zh_oversize = "中" * (zh_budget + 1000)
        self.inst.embed_documents([en_oversize, zh_oversize])
        sent = self.mock_create.call_args.kwargs["input"]
        self.assertEqual(len(sent[0]), en_budget)
        self.assertEqual(len(sent[1]), zh_budget)

    def test_truncation_logs_warning(self):
        self.mock_create.return_value = _embedding_response(1)
        en_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_ENGLISH)
        oversize = "x" * (en_budget + 5000)
        with patch("app.services.vector_embedding_service.logger") as mock_logger:
            self.inst.embed_documents([oversize])
            warnings = [
                call for call in mock_logger.warning.call_args_list
                if "截断" in str(call) or "truncat" in str(call).lower()
            ]
            self.assertGreaterEqual(len(warnings), 1)

    def test_no_warning_when_under_budget(self):
        self.mock_create.return_value = _embedding_response(1)
        with patch("app.services.vector_embedding_service.logger") as mock_logger:
            self.inst.embed_documents(["a short doc"])
            for call in mock_logger.warning.call_args_list:
                msg = str(call).lower()
                self.assertNotIn("truncat", msg)
                self.assertNotIn("截断", str(call))

    def test_embed_query_also_truncates(self):
        self.mock_create.return_value = _embedding_response(1)
        en_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_ENGLISH)
        oversize = "x" * (en_budget + 1000)
        self.inst.embed_query(oversize)
        sent = self.mock_create.call_args.kwargs["input"]
        # embed_query sends a string, not a list.
        self.assertIsInstance(sent, str)
        self.assertEqual(len(sent), en_budget)

    def test_truncation_runs_before_retry(self):
        """API never sees the oversized payload, even when first attempt fails."""
        self.mock_create.side_effect = [_timeout_error(), _embedding_response(1)]
        en_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, LANG_ENGLISH)
        oversize = "x" * (en_budget + 5000)
        self.inst.embed_documents([oversize])
        # Both attempts (the failed first + the successful retry) used the same truncated input.
        for call in self.mock_create.call_args_list:
            sent = call.kwargs["input"]
            self.assertEqual(len(sent[0]), en_budget)


if __name__ == "__main__":
    unittest.main()
