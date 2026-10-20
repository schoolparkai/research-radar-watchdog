from __future__ import annotations

import json

from watchdog.check_site import (
    CheckOutcome,
    SiteStatus,
    check_url_with_page,
    classify_snapshot,
    format_log,
)
from watchdog.config import NORMAL_MARKERS, WAKE_BUTTON_TEXT, Settings


NORMAL_TEXT = "\n".join(NORMAL_MARKERS)


class FakeBody:
    def __init__(self, page: "FakePage") -> None:
        self.page = page

    def inner_text(self, timeout: int) -> str:
        del timeout
        return self.page.states[self.page.state_index]


class FakeWakeButton:
    def __init__(self, page: "FakePage") -> None:
        self.page = page

    def count(self) -> int:
        return int(WAKE_BUTTON_TEXT in self.page.states[self.page.state_index])

    def is_visible(self) -> bool:
        return self.count() == 1

    def click(self, timeout: int) -> None:
        del timeout
        self.page.click_count += 1
        if self.page.wake_result is not None:
            self.page.states = [self.page.wake_result]
            self.page.state_index = 0


class FakeFrame:
    def __init__(self, page: "FakePage") -> None:
        self.page = page

    def locator(self, selector: str) -> FakeBody:
        assert selector == "body"
        return FakeBody(self.page)

    def get_by_role(self, role: str, *, name: str, exact: bool) -> FakeWakeButton:
        self.page.requested_roles.append((role, name, exact))
        return FakeWakeButton(self.page)


class FakePage:
    def __init__(
        self,
        states: list[str],
        *,
        navigation_failures: int = 0,
        wake_result: str | None = None,
    ) -> None:
        self.states = states
        self.state_index = 0
        self.navigation_failures = navigation_failures
        self.wake_result = wake_result
        self.goto_calls = 0
        self.click_count = 0
        self.requested_roles: list[tuple[str, str, bool]] = []
        self.frames = [FakeFrame(self)]
        self.url = "https://korean.streamlit.app/"

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        assert url == "https://korean.streamlit.app/"
        assert wait_until == "domcontentloaded"
        assert timeout > 0
        self.goto_calls += 1
        if self.goto_calls <= self.navigation_failures:
            raise RuntimeError("simulated connection failure with SECRET=do-not-log")

    def wait_for_timeout(self, milliseconds: int) -> None:
        assert milliseconds > 0
        if self.state_index + 1 < len(self.states):
            self.state_index += 1


def quick_settings(**overrides: int) -> Settings:
    values = {
        "navigation_timeout_ms": 1_000,
        "settle_timeout_seconds": 3,
        "wake_timeout_seconds": 3,
        "poll_interval_seconds": 1,
        "max_attempts": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_normal_landing_page_is_detected() -> None:
    assert classify_snapshot(NORMAL_TEXT, wake_button_visible=False) is SiteStatus.NORMAL


def test_mock_sleep_button_is_the_only_clicked_control() -> None:
    page = FakePage(
        [f"The app is asleep\n{WAKE_BUTTON_TEXT}"], wake_result=NORMAL_TEXT
    )

    result = check_url_with_page(page, quick_settings(), allow_wake=True)

    assert result.status is SiteStatus.NORMAL
    assert result.sleep_detected is True
    assert result.wake_attempted is True
    assert page.click_count == 1
    assert set(page.requested_roles) == {("button", WAKE_BUTTON_TEXT, True)}


def test_long_loading_eventually_resolves_without_clicking() -> None:
    page = FakePage(["Loading", "Please wait", "Waking up", NORMAL_TEXT])

    result = check_url_with_page(page, quick_settings(), allow_wake=True)

    assert result.status is SiteStatus.NORMAL
    assert page.click_count == 0


def test_loading_timeout_is_distinct_from_unknown() -> None:
    page = FakePage(["Loading"])

    result = check_url_with_page(page, quick_settings(max_attempts=1), allow_wake=True)

    assert result.status is SiteStatus.LOADING


def test_app_error_is_detected() -> None:
    assert (
        classify_snapshot("This app has encountered an error", False)
        is SiteStatus.APP_ERROR
    )


def test_connection_failure_uses_only_limited_retries() -> None:
    page = FakePage([""], navigation_failures=10)

    result = check_url_with_page(page, quick_settings(max_attempts=2), allow_wake=True)

    assert result.status is SiteStatus.UNKNOWN
    assert page.goto_calls == 2


def test_transient_connection_failure_can_recover() -> None:
    page = FakePage([NORMAL_TEXT], navigation_failures=1)

    result = check_url_with_page(page, quick_settings(max_attempts=2), allow_wake=True)

    assert result.status is SiteStatus.NORMAL
    assert page.goto_calls == 2


def test_unexpected_redirect_is_not_inspected_or_clicked() -> None:
    page = FakePage([f"sleeping\n{WAKE_BUTTON_TEXT}"], wake_result=NORMAL_TEXT)
    page.url = "https://example.invalid/redirected"

    result = check_url_with_page(page, quick_settings(), allow_wake=True)

    assert result.status is SiteStatus.UNKNOWN
    assert page.click_count == 0


def test_read_only_sleep_check_does_not_click() -> None:
    page = FakePage([f"sleeping\n{WAKE_BUTTON_TEXT}"], wake_result=NORMAL_TEXT)

    result = check_url_with_page(page, quick_settings(), allow_wake=False)

    assert result.status is SiteStatus.SLEEPING
    assert result.sleep_detected is True
    assert result.wake_attempted is False
    assert page.click_count == 0


def test_search_and_analysis_controls_are_never_requested_or_clicked() -> None:
    page = FakePage(
        [
            NORMAL_TEXT
            + "\n고시조 검색 시스템\n검색 실행\nRAG 분석\n파일 업로드\n결과 저장"
        ]
    )

    result = check_url_with_page(page, quick_settings(), allow_wake=True)

    assert result.status is SiteStatus.NORMAL
    assert page.click_count == 0
    assert all(name == WAKE_BUTTON_TEXT for _, name, _ in page.requested_roles)


def test_log_contains_only_approved_fields_and_no_secret_material() -> None:
    outcome = CheckOutcome(
        status=SiteStatus.UNKNOWN,
        sleep_detected=False,
        wake_attempted=False,
        elapsed_seconds=1.25,
        attempts=2,
    )

    raw_log = format_log(outcome)
    record = json.loads(raw_log)

    assert set(record) == {
        "checked_at",
        "result",
        "sleep_detected",
        "wake_attempted",
        "elapsed_seconds",
    }
    assert "SECRET" not in raw_log
    assert "https://" not in raw_log
