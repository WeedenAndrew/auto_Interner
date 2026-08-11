"""Environment-backed configuration for Auto Interner."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_SOURCE_MODES = frozenset({"git", "http"})
_DEFAULT_GIT_REPOSITORY_TEMPLATE = "https://github.com/SimplifyJobs/Summer{year}-Internships.git"


class SettingsError(ValueError):
    """Raised when configuration is missing, ambiguous, or unsafe."""


def _optional_text(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name, "").strip()
    return value or None


def _optional_path(environment: Mapping[str, str], name: str) -> Path | None:
    value = _optional_text(environment, name)
    return None if value is None else Path(value).expanduser()


def _parse_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = environment.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer; received {raw_value!r}") from exc
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}; received {value}")
    return value


def _parse_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw_value = environment.get(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be numeric; received {raw_value!r}") from exc
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}; received {value}")
    return value


def _parse_bool(environment: Mapping[str, str], name: str, default: bool) -> bool:
    raw_value = environment.get(name, str(default)).strip().lower()
    if raw_value in _TRUE_VALUES:
        return True
    if raw_value in _FALSE_VALUES:
        return False
    accepted = ", ".join(sorted(_TRUE_VALUES | _FALSE_VALUES))
    raise SettingsError(f"{name} must be one of: {accepted}; received {raw_value!r}")


def _validate_http_url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SettingsError(f"{name} must be a complete HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SettingsError(f"{name} must not contain embedded credentials")


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by all Auto Interner modules."""

    recruiting_year: int
    listings_source_mode: str
    listings_url: str | None
    listings_url_template: str | None
    listings_git_repository: str | None
    listings_git_repository_template: str | None
    listings_git_ref: str
    listings_git_path: str
    poll_interval_hours: float
    window_size: int
    static_fetch_timeout_seconds: float
    git_fetch_timeout_seconds: float
    browser_fetch_timeout_seconds: float
    max_fetch_attempts: int
    anthropic_model: str
    anthropic_api_key: str | None = field(repr=False)
    browser_enabled: bool = False
    chromium_binary: Path | None = None
    chromedriver_path: Path | None = None
    browser_no_sandbox: bool = False
    shadow_mode: bool = True
    data_dir: Path = Path("/app/data")
    state_dir: Path = Path("/app/state")
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        today: date | None = None,
    ) -> Settings:
        """Build settings without creating directories or contacting services."""
        values = os.environ if environment is None else environment
        current_date = date.today() if today is None else today

        raw_year = values.get("RECRUITING_YEAR", "").strip()
        if raw_year:
            recruiting_year = _parse_int(
                values,
                "RECRUITING_YEAR",
                current_date.year,
                minimum=2000,
                maximum=2100,
            )
        else:
            recruiting_year = current_date.year
            LOGGER.info(
                "Recruiting year omitted; using the current calendar year",
                extra={"event": "default_recruiting_year", "recruiting_year": recruiting_year},
            )

        listings_source_mode = values.get("LISTINGS_SOURCE_MODE", "git").strip().casefold()
        if listings_source_mode not in _SOURCE_MODES:
            raise SettingsError(
                "LISTINGS_SOURCE_MODE must be one of: "
                f"{', '.join(sorted(_SOURCE_MODES))}; received {listings_source_mode!r}"
            )

        listings_url = _optional_text(values, "LISTINGS_URL")
        listings_url_template = _optional_text(values, "LISTINGS_URL_TEMPLATE")
        if listings_source_mode == "http":
            if (listings_url is None) == (listings_url_template is None):
                raise SettingsError(
                    "HTTP source mode requires exactly one of LISTINGS_URL or LISTINGS_URL_TEMPLATE"
                )
            if listings_url is not None:
                _validate_http_url(listings_url, "LISTINGS_URL")
            if listings_url_template is not None:
                if listings_url_template.count("{year}") != 1:
                    raise SettingsError("LISTINGS_URL_TEMPLATE must contain {year} exactly once")
                _validate_http_url(
                    listings_url_template.format(year=recruiting_year),
                    "LISTINGS_URL_TEMPLATE",
                )

        listings_git_repository = _optional_text(values, "LISTINGS_GIT_REPOSITORY")
        listings_git_repository_template = _optional_text(
            values, "LISTINGS_GIT_REPOSITORY_TEMPLATE"
        )
        if listings_source_mode == "git":
            if listings_git_repository is not None and listings_git_repository_template is not None:
                raise SettingsError(
                    "Configure at most one of LISTINGS_GIT_REPOSITORY or "
                    "LISTINGS_GIT_REPOSITORY_TEMPLATE"
                )
            if listings_git_repository is None and listings_git_repository_template is None:
                listings_git_repository_template = _DEFAULT_GIT_REPOSITORY_TEMPLATE
            if listings_git_repository is not None:
                _validate_http_url(listings_git_repository, "LISTINGS_GIT_REPOSITORY")
            if listings_git_repository_template is not None:
                if listings_git_repository_template.count("{year}") != 1:
                    raise SettingsError(
                        "LISTINGS_GIT_REPOSITORY_TEMPLATE must contain {year} exactly once"
                    )
                _validate_http_url(
                    listings_git_repository_template.format(year=recruiting_year),
                    "LISTINGS_GIT_REPOSITORY_TEMPLATE",
                )

        log_level = values.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _LOG_LEVELS:
            raise SettingsError(
                f"LOG_LEVEL must be one of {', '.join(sorted(_LOG_LEVELS))}; received {log_level!r}"
            )

        anthropic_model = _optional_text(values, "ANTHROPIC_MODEL")
        if anthropic_model is None:
            raise SettingsError("ANTHROPIC_MODEL must contain an Anthropic model ID")

        return cls(
            recruiting_year=recruiting_year,
            listings_source_mode=listings_source_mode,
            listings_url=listings_url,
            listings_url_template=listings_url_template,
            listings_git_repository=listings_git_repository,
            listings_git_repository_template=listings_git_repository_template,
            listings_git_ref=values.get("LISTINGS_GIT_REF", "refs/heads/dev").strip(),
            listings_git_path=values.get(
                "LISTINGS_GIT_PATH", ".github/scripts/listings.json"
            ).strip(),
            poll_interval_hours=_parse_float(
                values,
                "POLL_INTERVAL_HOURS",
                2.0,
                minimum=0.25,
                maximum=168.0,
            ),
            window_size=_parse_int(values, "WINDOW_SIZE", 100, minimum=1, maximum=1_000),
            static_fetch_timeout_seconds=_parse_float(
                values,
                "STATIC_FETCH_TIMEOUT_SECONDS",
                15.0,
                minimum=1.0,
                maximum=120.0,
            ),
            git_fetch_timeout_seconds=_parse_float(
                values,
                "GIT_FETCH_TIMEOUT_SECONDS",
                60.0,
                minimum=5.0,
                maximum=600.0,
            ),
            browser_fetch_timeout_seconds=_parse_float(
                values,
                "BROWSER_FETCH_TIMEOUT_SECONDS",
                35.0,
                minimum=1.0,
                maximum=300.0,
            ),
            max_fetch_attempts=_parse_int(
                values,
                "MAX_FETCH_ATTEMPTS",
                3,
                minimum=1,
                maximum=10,
            ),
            anthropic_model=anthropic_model,
            anthropic_api_key=_optional_text(values, "ANTHROPIC_API_KEY"),
            browser_enabled=_parse_bool(values, "BROWSER_ENABLED", False),
            chromium_binary=_optional_path(values, "CHROMIUM_BINARY"),
            chromedriver_path=_optional_path(values, "CHROMEDRIVER_PATH"),
            browser_no_sandbox=_parse_bool(values, "BROWSER_NO_SANDBOX", False),
            shadow_mode=_parse_bool(values, "SHADOW_MODE", True),
            data_dir=Path(values.get("DATA_DIR", "/app/data")).expanduser(),
            state_dir=Path(values.get("STATE_DIR", "/app/state")).expanduser(),
            log_level=log_level,
        )

    @property
    def source_url(self) -> str:
        """Return the final snapshot URL for this recruiting cycle."""
        if self.listings_source_mode != "http":
            raise SettingsError("The active listing source is not HTTP")
        if self.listings_url is not None:
            return self.listings_url
        if self.listings_url_template is None:  # pragma: no cover - constructor invariant
            raise SettingsError("No listing source is configured")
        return self.listings_url_template.format(year=self.recruiting_year)

    @property
    def source_repository_url(self) -> str:
        """Return the final Git repository URL for this recruiting cycle."""
        if self.listings_source_mode != "git":
            raise SettingsError("The active listing source is not Git")
        if self.listings_git_repository is not None:
            return self.listings_git_repository
        if self.listings_git_repository_template is None:  # pragma: no cover - invariant
            raise SettingsError("No Git listing source is configured")
        return self.listings_git_repository_template.format(year=self.recruiting_year)

    @property
    def source_cache_dir(self) -> Path:
        """Return the private bare-repository cache for this recruiting cycle."""
        return self.state_dir / "source-cache" / f"summer-{self.recruiting_year}.git"

    @property
    def cycle_data_dir(self) -> Path:
        """Return the configured recruiting-cycle data directory."""
        return self.data_dir / str(self.recruiting_year)

    @property
    def base_resume_path(self) -> Path:
        """Return the immutable base resume expected for this cycle."""
        return self.cycle_data_dir / "baseplate" / "base_resume.docx"

    def ensure_runtime_layout(self) -> None:
        """Create runtime folders only when a run explicitly needs them."""
        (self.cycle_data_dir / "baseplate").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "tmp").mkdir(parents=True, exist_ok=True)

    def validate_runtime_requirements(
        self,
        *,
        require_model_key: bool = False,
        require_base_resume: bool = True,
    ) -> None:
        """Validate prerequisites immediately before pipeline work begins."""
        if require_model_key and self.anthropic_api_key is None:
            raise SettingsError(
                "ANTHROPIC_API_KEY is required for a live model call; "
                "set the variable or use an offline fake"
            )
        if require_base_resume and not self.base_resume_path.is_file():
            raise SettingsError(f"Base resume not found at {self.base_resume_path}")
        if self.browser_enabled:
            if self.chromium_binary is None or not self.chromium_binary.is_file():
                raise SettingsError("BROWSER_ENABLED requires a valid CHROMIUM_BINARY file")
            if self.chromedriver_path is None or not self.chromedriver_path.is_file():
                raise SettingsError("BROWSER_ENABLED requires a valid CHROMEDRIVER_PATH file")

    def safe_summary(self) -> dict[str, object]:
        """Return diagnostics that intentionally exclude secret values."""
        summary: dict[str, object] = {
            "recruiting_year": self.recruiting_year,
            "listings_source_mode": self.listings_source_mode,
            "shadow_mode": self.shadow_mode,
            "data_dir": str(self.data_dir),
            "state_dir": str(self.state_dir),
            "base_resume_path": str(self.base_resume_path),
            "anthropic_model": self.anthropic_model,
            "anthropic_api_key_configured": self.anthropic_api_key is not None,
            "browser_enabled": self.browser_enabled,
            "chromium_binary": (
                None if self.chromium_binary is None else str(self.chromium_binary)
            ),
            "chromedriver_path": (
                None if self.chromedriver_path is None else str(self.chromedriver_path)
            ),
            "browser_no_sandbox": self.browser_no_sandbox,
        }
        if self.listings_source_mode == "git":
            summary.update(
                {
                    "source_repository_url": self.source_repository_url,
                    "source_ref": self.listings_git_ref,
                    "source_path": self.listings_git_path,
                    "source_cache_dir": str(self.source_cache_dir),
                }
            )
        else:
            summary["source_url"] = self.source_url
        return summary
