from __future__ import annotations

from miles.auth.throttle import LoginThrottle


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_throttle_blocks_origin_after_max_failures_only() -> None:
    clock = _Clock()
    throttle = LoginThrottle(max_per_origin=3, max_global=100, window_s=60, clock=clock)

    for _ in range(2):
        throttle.record_failure("10.0.0.1")
    assert not throttle.is_blocked("10.0.0.1")

    throttle.record_failure("10.0.0.1")
    assert throttle.is_blocked("10.0.0.1")
    assert not throttle.is_blocked("10.0.0.2")


def test_throttle_releases_origin_after_window() -> None:
    clock = _Clock()
    throttle = LoginThrottle(max_per_origin=1, max_global=100, window_s=60, clock=clock)
    throttle.record_failure("10.0.0.1")

    clock.now += 60
    assert not throttle.is_blocked("10.0.0.1")


def test_throttle_global_limit_blocks_every_origin() -> None:
    clock = _Clock()
    throttle = LoginThrottle(max_per_origin=100, max_global=3, window_s=60, clock=clock)

    for index in range(3):
        throttle.record_failure(f"10.0.0.{index}")

    assert throttle.is_blocked("192.168.1.1")
