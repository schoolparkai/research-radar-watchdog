"""Fixed, low-impact settings for the Research Radar watchdog."""

from __future__ import annotations

from dataclasses import dataclass
import os


TARGET_URL = "https://korean.streamlit.app/"
WAKE_BUTTON_TEXT = "Yes, get this app back up!"

# All three markers were confirmed on the public landing page on 2026-10-20.
NORMAL_MARKERS = (
    "Research Radar",
    "문장 분석 검색 시스템",
    "개인 연구 자료 검색을 위한 사이트입니다.",
)

LOADING_MARKERS = (
    "Loading",
    "Please wait",
    "This app is waking up",
    "Waking up",
    "This app is in the oven",
    "Connecting",
)

APP_ERROR_MARKERS = (
    "Oh no",
    "This app has encountered an error",
    "Error running app",
    "Error running your app",
    "Application error",
    "Something went wrong",
    "ModuleNotFoundError",
    "ImportError",
    "Traceback (most recent call last)",
    "gone over its resource limits",
)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read a non-sensitive integer setting and keep it within safe limits."""

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    """Runtime bounds. The target URL is deliberately not configurable."""

    target_url: str = TARGET_URL
    navigation_timeout_ms: int = 45_000
    settle_timeout_seconds: int = 90
    wake_timeout_seconds: int = 240
    poll_interval_seconds: int = 5
    max_attempts: int = 2

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            navigation_timeout_ms=_bounded_int(
                "WATCHDOG_NAVIGATION_TIMEOUT_MS", 45_000, 5_000, 120_000
            ),
            settle_timeout_seconds=_bounded_int(
                "WATCHDOG_SETTLE_TIMEOUT_SECONDS", 90, 10, 300
            ),
            wake_timeout_seconds=_bounded_int(
                "WATCHDOG_WAKE_TIMEOUT_SECONDS", 240, 30, 480
            ),
            poll_interval_seconds=_bounded_int(
                "WATCHDOG_POLL_INTERVAL_SECONDS", 5, 1, 30
            ),
            max_attempts=_bounded_int("WATCHDOG_MAX_ATTEMPTS", 2, 1, 3),
        )
