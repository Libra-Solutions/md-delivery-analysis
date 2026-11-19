import httpx
import pytest

from delivery_analysis.connectors.bitbucket.client import BitbucketClient, RateLimitedError


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 1))
        self.now += seconds


def _client(responses, clock, patience):
    queue = list(responses)

    def handler(request):
        status, headers = queue.pop(0)
        return httpx.Response(status, headers=headers, json={"ok": status == 200})

    return BitbucketClient("made-up-token", transport=httpx.MockTransport(handler), sleep=clock.sleep,
                           jitter=lambda: 0.0, patience=patience, clock=clock)


def test_patient_client_waits_out_rate_limits_and_carries_on():
    clock = Clock()
    seen = []
    client = _client([(429, {"Retry-After": "40"}), (429, {}), (429, {}), (200, {})], clock, patience=3600)
    client.on_wait = seen.append
    assert client.get("/x") == {"ok": True}
    assert clock.slept == [40.0, 30.0, 60.0]  # Retry-After when sent, else a growing pause
    assert seen == [40.0, 30.0, 60.0] and client.waited == 130.0


def test_patience_outlasts_the_normal_retry_count():
    clock = Clock()
    client = _client([(429, {"Retry-After": "1"})] * 12 + [(200, {})], clock, patience=3600)
    assert client.get("/x") == {"ok": True}
    assert len(clock.slept) == 12


def test_waits_stop_when_patience_runs_out():
    clock = Clock()
    client = _client([(429, {"Retry-After": "600"})] * 10, clock, patience=1000)
    with pytest.raises(RateLimitedError):
        client.get("/x")
    assert sum(clock.slept) <= 1000 + 60 * 5  # never far past the deadline


def test_long_pause_is_capped_at_five_minutes():
    clock = Clock()
    client = _client([(429, {})] * 6 + [(200, {})], clock, patience=36000)
    client.get("/x")
    assert max(clock.slept) == 300.0


def test_impatient_client_still_gives_up():
    clock = Clock()
    client = _client([(429, {})] * 10, clock, patience=0)
    with pytest.raises(RateLimitedError):
        client.get("/x")
    assert len(clock.slept) == 4  # the normal max_retries


def test_patient_client_spreads_calls_near_the_limit():
    clock = Clock()
    client = _client([(200, {"X-RateLimit-NearLimit": "true"})], clock, patience=3600)
    client.get("/x")
    assert clock.slept == [10.0]
