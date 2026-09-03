"""Tests for rate limiting (atomicity, IP extraction, concurrency)."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

from django.test import TestCase, override_settings, Client, RequestFactory
from django.core.cache import cache
from ninja.errors import HttpError

from helpers.rate_limit import check_rate_limit, _get_ip


@override_settings(RATE_LIMIT_ENABLED=True)
class GetIpTests(TestCase):
    """Tests for _get_ip() IP extraction logic."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_no_xff_uses_remote_addr(self):
        """Without X-Forwarded-For, use REMOTE_ADDR."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(_get_ip(request), "10.0.0.1")

    def test_single_xff_hop(self):
        """Single X-Forwarded-For hop is returned directly."""
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="192.168.1.1")
        self.assertEqual(_get_ip(request), "192.168.1.1")

    def test_multiple_xff_hops_rightmost_wins(self):
        """Multiple X-Forwarded-For hops: rightmost (closest to Railway) is trusted."""
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR="5.5.5.5, 6.6.6.6, 7.7.7.7"
        )
        # With NUM_TRUSTED_PROXIES=1 (default), take the rightmost single hop
        self.assertEqual(_get_ip(request), "7.7.7.7")

    def test_multiple_xff_hops_with_num_proxies_2(self):
        """With NUM_TRUSTED_PROXIES=2, take the last 2 hops and return the first of those."""
        with override_settings(NUM_TRUSTED_PROXIES=2):
            request = self.factory.get(
                "/", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2, 3.3.3.3, 4.4.4.4"
            )
            # Last 2 hops are [3.3.3.3, 4.4.4.4]; return the first of those
            self.assertEqual(_get_ip(request), "3.3.3.3")

    def test_xff_with_whitespace(self):
        """X-Forwarded-For entries with whitespace are stripped."""
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR=" 1.1.1.1 , 2.2.2.2 , 3.3.3.3 "
        )
        self.assertEqual(_get_ip(request), "3.3.3.3")

    def test_empty_xff_falls_back_to_remote_addr(self):
        """Empty X-Forwarded-For falls back to REMOTE_ADDR."""
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR="", REMOTE_ADDR="10.0.0.99"
        )
        self.assertEqual(_get_ip(request), "10.0.0.99")


@override_settings(RATE_LIMIT_ENABLED=True)
class AtomicRateLimitTests(TestCase):
    """Tests for atomic (non-racy) rate limiting behavior."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_first_request_allowed(self):
        """First request in a window is always allowed."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        check_rate_limit(request, key="test", max_requests=5, period=60)
        # If no exception, test passes

    def test_max_requests_allowed(self):
        """Exactly max_requests requests are allowed."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        for i in range(5):
            check_rate_limit(request, key="test", max_requests=5, period=60)
        # All 5 allowed; if no exception, test passes

    def test_exceeding_limit_raises_429(self):
        """Request beyond max_requests raises HttpError 429."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        for _ in range(5):
            check_rate_limit(request, key="test", max_requests=5, period=60)
        with self.assertRaises(HttpError) as cm:
            check_rate_limit(request, key="test", max_requests=5, period=60)
        self.assertEqual(cm.exception.status_code, 429)

    def test_429_message_contains_period(self):
        """429 error message contains the period in seconds."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        for _ in range(3):
            check_rate_limit(request, key="test", max_requests=3, period=45)
        with self.assertRaises(HttpError) as cm:
            check_rate_limit(request, key="test", max_requests=3, period=45)
        self.assertIn("45 seconds", cm.exception.message)

    def test_independent_identifiers(self):
        """Different identifiers have independent rate limit buckets."""
        request1 = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        request2 = self.factory.get("/", REMOTE_ADDR="10.0.0.2")
        for _ in range(3):
            check_rate_limit(request1, key="test", max_requests=3, period=60)
        # request1 is now at limit, but request2 should still be allowed
        check_rate_limit(request2, key="test", max_requests=3, period=60)

    def test_different_keys_independent(self):
        """Different keys (endpoints) have independent buckets."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        for _ in range(2):
            check_rate_limit(request, key="login", max_requests=2, period=60)
        for _ in range(2):
            check_rate_limit(request, key="register", max_requests=2, period=60)
        # Both should be at limit, but each independently

    def test_custom_identifier_bypasses_ip(self):
        """Providing a custom identifier bypasses IP extraction."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        for _ in range(3):
            check_rate_limit(
                request, key="test", max_requests=3, period=60, identifier="user:123"
            )
        with self.assertRaises(HttpError):
            check_rate_limit(
                request, key="test", max_requests=3, period=60, identifier="user:123"
            )


@override_settings(RATE_LIMIT_ENABLED=True)
class ConcurrentRateLimitTests(TestCase):
    """Regression tests for atomicity under concurrent load (race condition fix).

    The old implementation used cache.get() → cache.set(), which is racy.
    New implementation uses cache.add() + cache.incr(), which is atomic.
    This test verifies exactly N requests succeed and the rest fail.
    """

    def setUp(self):
        cache.clear()

    def test_concurrent_requests_exact_boundary(self):
        """Under concurrent load, exactly max_requests succeed; N+1 is blocked."""
        factory = RequestFactory()
        cache_key = "rl:test:10.0.0.1"
        max_requests = 10
        num_threads = 25  # More threads than the limit to stress-test

        results = []
        lock = threading.Lock()

        def make_request():
            request = factory.get("/", REMOTE_ADDR="10.0.0.1")
            try:
                check_rate_limit(request, key="test", max_requests=max_requests, period=60)
                with lock:
                    results.append("allowed")
            except HttpError as e:
                if e.status_code == 429:
                    with lock:
                        results.append("blocked")
                else:
                    raise

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        allowed = results.count("allowed")
        blocked = results.count("blocked")

        # Exactly max_requests should succeed
        self.assertEqual(allowed, max_requests, f"Expected {max_requests} allowed, got {allowed}")
        self.assertEqual(blocked, num_threads - max_requests, f"Expected {num_threads - max_requests} blocked, got {blocked}")


@override_settings(RATE_LIMIT_ENABLED=True)
class GlobalRateLimitMiddlewareTests(TestCase):
    """Tests for GlobalRateLimitMiddleware (100 req/min per IP on /api/*)."""

    def setUp(self):
        self.client = Client()
        cache.clear()

    def test_100_api_requests_allowed(self):
        """100 requests/min per IP: exactly 100 requests to /api/hello are allowed."""
        for i in range(100):
            response = self.client.get(
                "/api/hello", REMOTE_ADDR="10.0.0.1"
            )
            if response.status_code == 429:
                self.fail(f"Request #{i+1} was rate-limited; expected first 100 to pass")
            # Allow 200/201 (success) and other non-429 responses
            self.assertNotEqual(response.status_code, 429)

    def test_101st_api_request_blocked(self):
        """101st request within the window is blocked."""
        for _ in range(100):
            self.client.get("/api/hello", REMOTE_ADDR="10.0.0.1")
        response = self.client.get("/api/hello", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(response.status_code, 429)

    def test_429_response_shape(self):
        """429 response has the correct shape: {"detail": "..."}."""
        for _ in range(100):
            self.client.get("/api/hello", REMOTE_ADDR="10.0.0.1")
        response = self.client.get("/api/hello", REMOTE_ADDR="10.0.0.1")
        body = json.loads(response.content)
        self.assertIn("detail", body)
        self.assertIn("Rate limit exceeded", body["detail"])

    def test_different_ips_independent_buckets(self):
        """Global limit is per-IP; different IPs have independent buckets."""
        for _ in range(100):
            self.client.get("/api/hello", REMOTE_ADDR="10.0.0.1")
        # 10.0.0.1 is now blocked
        response = self.client.get("/api/hello", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(response.status_code, 429)
        # But 10.0.0.2 should still be allowed
        response = self.client.get("/api/hello", REMOTE_ADDR="10.0.0.2")
        self.assertNotEqual(response.status_code, 429)

    def test_non_api_paths_unaffected(self):
        """Non-/api/* paths (e.g. /admin) bypass the global middleware."""
        # This test is illustrative; the test server doesn't have /admin,
        # but it demonstrates the middleware only checks /api/* paths.
        # We can't easily test /admin without it existing, but we can verify
        # that the middleware passes through non-/api/ requests.
        # For now, this is documentation.


@override_settings(RATE_LIMIT_ENABLED=False)
class RateLimitDisabledTests(TestCase):
    """Verify rate limiting can be disabled via RATE_LIMIT_ENABLED."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_disabled_allows_unlimited(self):
        """When RATE_LIMIT_ENABLED=False, limits are not enforced."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        for _ in range(100):
            check_rate_limit(request, key="test", max_requests=3, period=60)
        # No exception should be raised
