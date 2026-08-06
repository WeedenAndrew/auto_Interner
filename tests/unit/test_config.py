"""Phase 0 configuration behavior."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest

from auto_interner.config import Settings, SettingsError

pytestmark = pytest.mark.unit


def _base_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "RECRUITING_YEAR": "2027",
        "LISTINGS_SOURCE_MODE": "http",
        "LISTINGS_URL": "https://example.com/listings.json",
        "DATA_DIR": str(tmp_path / "data"),
        "STATE_DIR": str(tmp_path / "state"),
        "SHADOW_MODE": "true",
        "ANTHROPIC_MODEL": "account-model-id",
    }


def test_f_cfg_001_explicit_recruiting_year_is_used(tmp_path: Path) -> None:
    """F-CFG-001: an explicit valid recruiting year is retained."""
    settings = Settings.from_env(_base_environment(tmp_path))

    assert settings.recruiting_year == 2027


def test_f_cfg_002_omitted_year_uses_current_year_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F-CFG-002: omission selects and reports the current calendar year."""
    environment = _base_environment(tmp_path)
    del environment["RECRUITING_YEAR"]

    with caplog.at_level(logging.INFO, logger="auto_interner.config"):
        settings = Settings.from_env(environment, today=date(2031, 6, 4))

    assert settings.recruiting_year == 2031
    assert "current calendar year" in caplog.text


def test_f_cfg_003_explicit_url_is_not_rewritten(tmp_path: Path) -> None:
    """F-CFG-003: a complete source URL is used verbatim."""
    settings = Settings.from_env(_base_environment(tmp_path))

    assert settings.source_url == "https://example.com/listings.json"


def test_f_cfg_004_template_substitutes_year_exactly_once(tmp_path: Path) -> None:
    """F-CFG-004: the configured cycle replaces the one year placeholder."""
    environment = _base_environment(tmp_path)
    del environment["LISTINGS_URL"]
    environment["LISTINGS_URL_TEMPLATE"] = "https://example.com/internships/{year}/listings.json"

    settings = Settings.from_env(environment)

    assert settings.source_url == "https://example.com/internships/2027/listings.json"


def test_f_cfg_005_missing_source_fails_before_work(tmp_path: Path) -> None:
    """F-CFG-005: startup rejects an absent listing source."""
    environment = _base_environment(tmp_path)
    del environment["LISTINGS_URL"]

    with pytest.raises(SettingsError, match="HTTP source mode requires exactly one"):
        Settings.from_env(environment)


def test_f_cfg_006_template_without_year_fails(tmp_path: Path) -> None:
    """F-CFG-006: a non-parameterized template fails before network access."""
    environment = _base_environment(tmp_path)
    del environment["LISTINGS_URL"]
    environment["LISTINGS_URL_TEMPLATE"] = "https://example.com/listings.json"

    with pytest.raises(SettingsError, match=r"contain \{year\} exactly once"):
        Settings.from_env(environment)


@pytest.mark.parametrize(
    ("name", "value"),
    [("WINDOW_SIZE", "0"), ("MAX_FETCH_CONCURRENCY", "-1")],
)
def test_f_cfg_007_nonpositive_limits_are_rejected(tmp_path: Path, name: str, value: str) -> None:
    """F-CFG-007: bounded work settings cannot be zero or negative."""
    environment = _base_environment(tmp_path)
    environment[name] = value

    with pytest.raises(SettingsError, match=name):
        Settings.from_env(environment)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("YES", True), ("1", True), ("false", False), ("off", False)],
)
def test_f_cfg_008_shadow_mode_parses_common_spellings(
    tmp_path: Path, value: str, expected: bool
) -> None:
    """F-CFG-008: common boolean spellings parse consistently."""
    environment = _base_environment(tmp_path)
    environment["SHADOW_MODE"] = value

    assert Settings.from_env(environment).shadow_mode is expected


def test_f_cfg_009_live_model_requires_key(tmp_path: Path) -> None:
    """F-CFG-009: a live model path fails before listing processing."""
    settings = Settings.from_env(_base_environment(tmp_path))

    with pytest.raises(SettingsError, match="ANTHROPIC_API_KEY"):
        settings.validate_runtime_requirements(require_model_key=True, require_base_resume=False)


def test_f_cfg_010_missing_resume_reports_expected_path(tmp_path: Path) -> None:
    """F-CFG-010: a missing base resume has an actionable local error."""
    settings = Settings.from_env(_base_environment(tmp_path))

    with pytest.raises(SettingsError, match="base_resume.docx"):
        settings.validate_runtime_requirements(require_base_resume=True)


def test_f_cfg_011_runtime_directories_are_created_lazily(tmp_path: Path) -> None:
    """F-CFG-011: parsing has no writes; an explicit call creates the layout."""
    settings = Settings.from_env(_base_environment(tmp_path))

    assert not settings.data_dir.exists()
    assert not settings.state_dir.exists()

    settings.ensure_runtime_layout()

    assert (settings.cycle_data_dir / "baseplate").is_dir()
    assert (settings.state_dir / "tmp").is_dir()


def test_f_cfg_012_cycle_paths_use_configured_year(tmp_path: Path) -> None:
    """F-CFG-012: runtime paths follow the recruiting cycle, not wall time."""
    settings = Settings.from_env(_base_environment(tmp_path), today=date(2026, 8, 5))

    assert settings.cycle_data_dir == tmp_path / "data" / "2027"
    assert settings.base_resume_path == (
        tmp_path / "data" / "2027" / "baseplate" / "base_resume.docx"
    )


def test_source_settings_are_mutually_exclusive(tmp_path: Path) -> None:
    """Ambiguous source precedence is rejected instead of guessed."""
    environment = _base_environment(tmp_path)
    environment["LISTINGS_URL_TEMPLATE"] = "https://example.com/{year}/listings.json"

    with pytest.raises(SettingsError, match="exactly one"):
        Settings.from_env(environment)


def test_git_source_is_default_and_uses_recruiting_year(tmp_path: Path) -> None:
    """The default source is a year-variable Simplify repository."""
    environment = _base_environment(tmp_path)
    del environment["LISTINGS_SOURCE_MODE"]
    del environment["LISTINGS_URL"]

    settings = Settings.from_env(environment)

    assert settings.listings_source_mode == "git"
    assert settings.source_repository_url == (
        "https://github.com/SimplifyJobs/Summer2027-Internships.git"
    )
    assert settings.listings_git_ref == "refs/heads/dev"
    assert settings.listings_git_path == ".github/scripts/listings.json"


def test_git_repository_override_and_template_are_mutually_exclusive(tmp_path: Path) -> None:
    environment = _base_environment(tmp_path)
    environment["LISTINGS_SOURCE_MODE"] = "git"
    environment["LISTINGS_GIT_REPOSITORY"] = (
        "https://github.com/SimplifyJobs/Summer2027-Internships.git"
    )
    environment["LISTINGS_GIT_REPOSITORY_TEMPLATE"] = (
        "https://github.com/SimplifyJobs/Summer{year}-Internships.git"
    )

    with pytest.raises(SettingsError, match="at most one"):
        Settings.from_env(environment)


def test_unknown_listing_source_mode_is_rejected(tmp_path: Path) -> None:
    environment = _base_environment(tmp_path)
    environment["LISTINGS_SOURCE_MODE"] = "archive"

    with pytest.raises(SettingsError, match="LISTINGS_SOURCE_MODE"):
        Settings.from_env(environment)


def test_source_url_rejects_embedded_credentials(tmp_path: Path) -> None:
    """Secrets cannot be smuggled into a logged source URL."""
    environment = _base_environment(tmp_path)
    environment["LISTINGS_URL"] = "https://user:password@example.com/listings.json"

    with pytest.raises(SettingsError, match="embedded credentials"):
        Settings.from_env(environment)


def test_anthropic_model_is_swappable_without_code_changes(tmp_path: Path) -> None:
    """Any nonempty configured model identifier is retained exactly."""
    environment = _base_environment(tmp_path)
    environment["ANTHROPIC_MODEL"] = "account-model-id"

    settings = Settings.from_env(environment)

    assert settings.anthropic_model == "account-model-id"


def test_blank_anthropic_model_is_rejected(tmp_path: Path) -> None:
    """A live adapter must never receive an empty model identifier."""
    environment = _base_environment(tmp_path)
    environment["ANTHROPIC_MODEL"] = "  "

    with pytest.raises(SettingsError, match="ANTHROPIC_MODEL"):
        Settings.from_env(environment)


def test_browser_fallback_is_disabled_by_default(tmp_path: Path) -> None:
    settings = Settings.from_env(_base_environment(tmp_path))

    assert settings.browser_enabled is False
    assert settings.chromium_binary is None
    assert settings.chromedriver_path is None
    assert settings.browser_no_sandbox is False


def test_enabled_browser_requires_existing_binary_and_driver(tmp_path: Path) -> None:
    environment = _base_environment(tmp_path)
    environment["BROWSER_ENABLED"] = "true"
    settings = Settings.from_env(environment)

    with pytest.raises(SettingsError, match="CHROMIUM_BINARY"):
        settings.validate_runtime_requirements(require_base_resume=False)

    binary = tmp_path / "chromium"
    driver = tmp_path / "chromedriver"
    binary.touch()
    driver.touch()
    environment["CHROMIUM_BINARY"] = str(binary)
    environment["CHROMEDRIVER_PATH"] = str(driver)
    environment["BROWSER_NO_SANDBOX"] = "true"
    settings = Settings.from_env(environment)

    settings.validate_runtime_requirements(require_base_resume=False)
    assert settings.browser_enabled is True
    assert settings.browser_no_sandbox is True
    assert settings.chromium_binary == binary
    assert settings.chromedriver_path == driver


def test_enabled_browser_rejects_missing_driver_after_binary_passes(tmp_path: Path) -> None:
    binary = tmp_path / "chromium"
    binary.touch()
    environment = _base_environment(tmp_path)
    environment.update(
        {
            "BROWSER_ENABLED": "true",
            "CHROMIUM_BINARY": str(binary),
            "CHROMEDRIVER_PATH": str(tmp_path / "missing-driver"),
        }
    )

    with pytest.raises(SettingsError, match="CHROMEDRIVER_PATH"):
        Settings.from_env(environment).validate_runtime_requirements(require_base_resume=False)
