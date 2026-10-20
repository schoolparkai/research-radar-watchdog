"""Check the public Research Radar landing page and wake it only when asleep."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
import time
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page, Playwright, sync_playwright

from .config import (
    APP_ERROR_MARKERS,
    LOADING_MARKERS,
    NORMAL_MARKERS,
    WAKE_BUTTON_TEXT,
    Settings,
)


class SiteStatus(str, Enum):
    """Externally reported site states."""

    NORMAL = "normal"
    SLEEPING = "sleeping"
    LOADING = "loading"
    APP_ERROR = "app_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CheckOutcome:
    status: SiteStatus
    sleep_detected: bool
    wake_attempted: bool
    elapsed_seconds: float
    attempts: int


@dataclass(frozen=True)
class PageCheck:
    status: SiteStatus
    sleep_detected: bool = False
    wake_attempted: bool = False
    attempts: int = 1


def classify_snapshot(visible_text: str, wake_button_visible: bool) -> SiteStatus:
    """Classify already-visible public page text without triggering app actions."""

    if wake_button_visible:
        return SiteStatus.SLEEPING
    if all(marker in visible_text for marker in NORMAL_MARKERS):
        return SiteStatus.NORMAL
    if any(marker in visible_text for marker in APP_ERROR_MARKERS):
        return SiteStatus.APP_ERROR
    if any(marker in visible_text for marker in LOADING_MARKERS):
        return SiteStatus.LOADING
    return SiteStatus.UNKNOWN


def _frames(page: Page) -> list[Any]:
    """Return only target/Streamlit frames, tolerating a partial load."""

    try:
        candidates = list(page.frames)
    except Exception:
        candidates = [page]
    allowed_hosts = {
        urlsplit(Settings().target_url).hostname,
        "share.streamlit.io",
    }
    allowed: list[Any] = []
    for frame in candidates:
        frame_url = getattr(frame, "url", None)
        if not isinstance(frame_url, str) or not frame_url:
            # Test doubles and a frame being replaced during startup have no URL.
            allowed.append(frame)
            continue
        parsed = urlsplit(frame_url)
        if parsed.scheme == "https" and parsed.hostname in allowed_hosts:
            allowed.append(frame)
    return allowed


def _is_allowed_page_url(url: str, target_url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in {
        urlsplit(target_url).hostname,
        "share.streamlit.io",
    }


def _collect_visible_text(page: Page) -> str:
    chunks: list[str] = []
    for frame in _frames(page):
        try:
            text = frame.locator("body").inner_text(timeout=2_500)
        except Exception:
            continue
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _find_wake_button(page: Page) -> Any | None:
    """Return only an unambiguous, visible Streamlit wake button."""

    for frame in _frames(page):
        try:
            candidate = frame.get_by_role(
                "button", name=WAKE_BUTTON_TEXT, exact=True
            )
            if candidate.count() == 1 and candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


def _observe(page: Page) -> tuple[SiteStatus, Any | None]:
    wake_button = _find_wake_button(page)
    visible_text = _collect_visible_text(page)
    for frame in _frames(page):
        try:
            exceptions = frame.locator('[data-testid="stException"]').all()
            if any(item.is_visible() for item in exceptions):
                return SiteStatus.APP_ERROR, None
        except Exception:
            continue
    return classify_snapshot(visible_text, wake_button is not None), wake_button


def _wait_for_resolution(
    page: Page, timeout_seconds: int, poll_interval_seconds: int
) -> tuple[SiteStatus, Any | None]:
    """Poll a bounded number of times while Streamlit initializes."""

    checks = max(1, math.ceil(timeout_seconds / poll_interval_seconds) + 1)
    last_status = SiteStatus.UNKNOWN
    saw_loading = False
    for index in range(checks):
        status, wake_button = _observe(page)
        last_status = status
        saw_loading = saw_loading or status is SiteStatus.LOADING
        if status in {
            SiteStatus.NORMAL,
            SiteStatus.SLEEPING,
            SiteStatus.APP_ERROR,
        }:
            return status, wake_button
        if index + 1 < checks:
            try:
                page.wait_for_timeout(poll_interval_seconds * 1_000)
            except Exception:
                return SiteStatus.UNKNOWN, None
    if last_status is SiteStatus.LOADING or saw_loading:
        return SiteStatus.LOADING, None
    return SiteStatus.UNKNOWN, None


def check_url_with_page(
    page: Page, settings: Settings, *, allow_wake: bool
) -> PageCheck:
    """Navigate and inspect a page with limited retries and narrowly scoped clicks."""

    for attempt in range(1, settings.max_attempts + 1):
        try:
            response = page.goto(
                settings.target_url,
                wait_until="domcontentloaded",
                timeout=settings.navigation_timeout_ms,
            )
        except Exception:
            if attempt < settings.max_attempts:
                continue
            return PageCheck(status=SiteStatus.UNKNOWN, attempts=attempt)

        current_url = getattr(page, "url", settings.target_url)
        if isinstance(current_url, str) and not _is_allowed_page_url(
            current_url, settings.target_url
        ):
            return PageCheck(status=SiteStatus.UNKNOWN, attempts=attempt)
        response_status = getattr(response, "status", 200)
        if response_status >= 500:
            return PageCheck(status=SiteStatus.APP_ERROR, attempts=attempt)
        if response_status >= 400:
            return PageCheck(status=SiteStatus.UNKNOWN, attempts=attempt)

        status, wake_button = _wait_for_resolution(
            page,
            settings.settle_timeout_seconds,
            settings.poll_interval_seconds,
        )

        if status is SiteStatus.SLEEPING:
            if not allow_wake or wake_button is None:
                return PageCheck(
                    status=SiteStatus.SLEEPING,
                    sleep_detected=True,
                    attempts=attempt,
                )
            try:
                # This is the program's only click. It never targets app widgets,
                # menus, search controls, upload controls, or analysis actions.
                wake_button.click(timeout=10_000)
            except Exception:
                return PageCheck(
                    status=SiteStatus.UNKNOWN,
                    sleep_detected=True,
                    wake_attempted=True,
                    attempts=attempt,
                )
            final_status, _ = _wait_for_resolution(
                page,
                settings.wake_timeout_seconds,
                settings.poll_interval_seconds,
            )
            return PageCheck(
                status=final_status,
                sleep_detected=True,
                wake_attempted=True,
                attempts=attempt,
            )

        if status is SiteStatus.UNKNOWN and attempt < settings.max_attempts:
            continue
        return PageCheck(status=status, attempts=attempt)

    return PageCheck(status=SiteStatus.UNKNOWN, attempts=settings.max_attempts)


def _run_browser(playwright: Playwright, settings: Settings, allow_wake: bool) -> PageCheck:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        accept_downloads=False,
        java_script_enabled=True,
        locale="ko-KR",
    )
    try:
        page = context.new_page()
        return check_url_with_page(page, settings, allow_wake=allow_wake)
    finally:
        context.close()
        browser.close()


def check_site(
    settings: Settings | None = None, *, allow_wake: bool = True
) -> CheckOutcome:
    """Run the independent browser check and return a secret-free outcome."""

    selected_settings = settings or Settings.from_environment()
    started = time.monotonic()
    try:
        with sync_playwright() as playwright:
            result = _run_browser(playwright, selected_settings, allow_wake)
    except Exception:
        result = PageCheck(status=SiteStatus.UNKNOWN, attempts=1)
    return CheckOutcome(
        status=result.status,
        sleep_detected=result.sleep_detected,
        wake_attempted=result.wake_attempted,
        elapsed_seconds=round(time.monotonic() - started, 2),
        attempts=result.attempts,
    )


def format_log(outcome: CheckOutcome) -> str:
    """Produce the complete log record; never include URLs, page text, or errors."""

    record = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": outcome.status.value,
        "sleep_detected": outcome.sleep_detected,
        "wake_attempted": outcome.wake_attempted,
        "elapsed_seconds": outcome.elapsed_seconds,
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def _exit_code(status: SiteStatus) -> int:
    if status is SiteStatus.NORMAL:
        return 0
    if status in {SiteStatus.SLEEPING, SiteStatus.LOADING}:
        return 2
    if status is SiteStatus.APP_ERROR:
        return 3
    return 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="detect sleeping state but do not click the wake button",
    )
    args = parser.parse_args(argv)
    outcome = check_site(allow_wake=not args.read_only)
    print(format_log(outcome), flush=True)
    return _exit_code(outcome.status)


if __name__ == "__main__":
    raise SystemExit(main())
