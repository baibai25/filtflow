"""update_checker モジュールのテスト。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from Filtflow.update_checker import (
    RELEASES_URL,
    UpdateChecker,
    _build_release_url,
    _fetch_latest_release,
    _parse_version,
)


class TestParseVersion:
    def test_valid_tag_with_prefix(self) -> None:
        v = _parse_version("v0.1.0")
        assert v is not None
        assert str(v) == "0.1.0"

    def test_valid_tag_without_prefix(self) -> None:
        v = _parse_version("1.2.3")
        assert v is not None
        assert str(v) == "1.2.3"

    def test_invalid_tag(self) -> None:
        assert _parse_version("not-a-version") is None

    def test_empty_string(self) -> None:
        assert _parse_version("") is None

    def test_comparison(self) -> None:
        v1 = _parse_version("v0.1.0")
        v2 = _parse_version("v0.2.0")
        assert v1 is not None
        assert v2 is not None
        assert v2 > v1


class TestBuildReleaseUrl:
    def test_valid_tag(self) -> None:
        assert _build_release_url("v0.2.0") == f"{RELEASES_URL}/tag/v0.2.0"

    def test_tag_with_underscore_and_hyphen(self) -> None:
        assert _build_release_url("v1.0.0-rc_1") == f"{RELEASES_URL}/tag/v1.0.0-rc_1"

    def test_empty_tag_falls_back(self) -> None:
        assert _build_release_url("") == RELEASES_URL

    def test_tag_with_slash_falls_back(self) -> None:
        assert _build_release_url("v0.2.0/../evil") == RELEASES_URL

    def test_tag_with_scheme_falls_back(self) -> None:
        assert _build_release_url("javascript:alert(1)") == RELEASES_URL

    def test_tag_with_query_falls_back(self) -> None:
        assert _build_release_url("v0.2.0?x=1") == RELEASES_URL


class TestFetchLatestRelease:
    def test_success(self) -> None:
        fake_response = json.dumps(
            {"tag_name": "v0.2.0", "html_url": "https://example.com/release"}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("Filtflow.update_checker.urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_latest_release()

        assert result is not None
        assert result["tag_name"] == "v0.2.0"
        assert result["html_url"] == "https://example.com/release"

    def test_network_error_returns_none(self) -> None:
        with patch(
            "Filtflow.update_checker.urllib.request.urlopen",
            side_effect=OSError("Network error"),
        ):
            assert _fetch_latest_release() is None

    def test_timeout_returns_none(self) -> None:
        with patch(
            "Filtflow.update_checker.urllib.request.urlopen",
            side_effect=TimeoutError,
        ):
            assert _fetch_latest_release() is None


class TestUpdateChecker:
    def _make_fake_release(self, tag: str, url: str) -> dict[str, str]:
        return {"tag_name": tag, "html_url": url}

    def test_update_available_emits_signal(self) -> None:
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        fake = self._make_fake_release("v0.2.0", "https://example.com/v0.2.0")
        with patch("Filtflow.update_checker._fetch_latest_release", return_value=fake):
            checker._run("0.1.0")

        callback.assert_called_once_with("0.2.0", f"{RELEASES_URL}/tag/v0.2.0")

    def test_release_url_ignores_html_url(self) -> None:
        """html_url は使わず tag_name から URL を構築する (Issue #19)。"""
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        fake = self._make_fake_release("v0.2.0", "file:///C:/Windows/evil.exe")
        with patch("Filtflow.update_checker._fetch_latest_release", return_value=fake):
            checker._run("0.1.0")

        callback.assert_called_once_with("0.2.0", f"{RELEASES_URL}/tag/v0.2.0")

    def test_no_update_when_current_is_latest(self) -> None:
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        fake = self._make_fake_release("v0.1.0", "https://example.com/v0.1.0")
        with patch("Filtflow.update_checker._fetch_latest_release", return_value=fake):
            checker._run("0.1.0")

        callback.assert_not_called()

    def test_no_update_when_current_is_newer(self) -> None:
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        fake = self._make_fake_release("v0.1.0", "https://example.com/v0.1.0")
        with patch("Filtflow.update_checker._fetch_latest_release", return_value=fake):
            checker._run("0.2.0")

        callback.assert_not_called()

    def test_network_failure_no_signal(self) -> None:
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        with patch("Filtflow.update_checker._fetch_latest_release", return_value=None):
            checker._run("0.1.0")

        callback.assert_not_called()

    def test_invalid_current_version_no_signal(self) -> None:
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        fake = self._make_fake_release("v0.2.0", "https://example.com/v0.2.0")
        with patch("Filtflow.update_checker._fetch_latest_release", return_value=fake):
            checker._run("invalid")

        callback.assert_not_called()

    def test_invalid_remote_tag_no_signal(self) -> None:
        checker = UpdateChecker()
        callback = MagicMock()
        checker.update_available.connect(callback)

        fake = self._make_fake_release("not-a-version", "https://example.com")
        with patch("Filtflow.update_checker._fetch_latest_release", return_value=fake):
            checker._run("0.1.0")

        callback.assert_not_called()
