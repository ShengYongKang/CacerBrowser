"""ShadowFox identity model.

An identity is a persistent, geo-coherent browser persona: one fpgen
fingerprint (drawn from the real-device distribution) plus the launcher
facts derived from it, stored as a single JSON file under profiles/.

Determinism: the fingerprint is drawn once at creation and persisted; every
launch reuses the exact same dict (verified in Phase 0a: cross-process hash
stable). No per-launch randomness leaks into the presented identity.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fsutil import write_text_atomic
from .validate import validate_identity

SCHEMA_VERSION = 1

VALID_OS = ("windows", "macos", "linux")

# Stable defaults used when the operator explicitly chooses a country. The
# fingerprint pool contains fewer samples for some countries, so relying only
# on random geo samples makes creation flaky. These values keep locale,
# language and timezone coherent while the rest of the fingerprint remains a
# real generated device profile.
COUNTRY_DEFAULTS = {
    "US": ("en-US", "America/New_York", ["en-US", "en"]),
    "CA": ("en-CA", "America/Toronto", ["en-CA", "en", "fr-CA"]),
    "GB": ("en-GB", "Europe/London", ["en-GB", "en"]),
    "FR": ("fr-FR", "Europe/Paris", ["fr-FR", "fr", "en-US"]),
    "DE": ("de-DE", "Europe/Berlin", ["de-DE", "de", "en-US"]),
    "ES": ("es-ES", "Europe/Madrid", ["es-ES", "es", "en-US"]),
    "IT": ("it-IT", "Europe/Rome", ["it-IT", "it", "en-US"]),
    "NL": ("nl-NL", "Europe/Amsterdam", ["nl-NL", "nl", "en-US"]),
    "SE": ("sv-SE", "Europe/Stockholm", ["sv-SE", "sv", "en-US"]),
    "CH": ("de-CH", "Europe/Zurich", ["de-CH", "de", "fr-CH", "en-US"]),
    "AU": ("en-AU", "Australia/Sydney", ["en-AU", "en"]),
    "JP": ("ja-JP", "Asia/Tokyo", ["ja-JP", "ja", "en-US"]),
    "KR": ("ko-KR", "Asia/Seoul", ["ko-KR", "ko", "en-US"]),
    "SG": ("en-SG", "Asia/Singapore", ["en-SG", "en", "zh-CN"]),
    "IN": ("en-IN", "Asia/Kolkata", ["en-IN", "en", "hi"]),
    "BR": ("pt-BR", "America/Sao_Paulo", ["pt-BR", "pt", "en-US"]),
    "CN": ("zh-CN", "Asia/Shanghai", ["zh-CN", "zh", "en-US"]),
    "TW": ("zh-TW", "Asia/Taipei", ["zh-TW", "zh", "en-US"]),
    "HK": ("zh-HK", "Asia/Hong_Kong", ["zh-HK", "zh-Hant", "en-US"]),
}


@dataclass
class Geo:
    country: str          # ISO 3166-1 alpha-2, e.g. "FR"
    region: Optional[str]  # e.g. "Île-de-France"
    locale: str            # e.g. "fr-FR" (primary Intl locale)
    timezone: str          # e.g. "Europe/Paris"
    languages: List[str] = field(default_factory=list)  # e.g. ["fr", "fr-FR", "en-US"]


@dataclass
class Launcher:
    maxTouchPoints: int
    hardwareConcurrency: int
    pinned_cores: bool = False
    # Browser-UI language (menus, dialogs) -- decoupled from the identity's
    # web-facing locale on purpose: the operator reads the UI in their own
    # language while the identity still presents its geo-coherent locale to
    # pages. None = follow the identity locale (maximum mimicry).
    ui_locale: Optional[str] = "zh-CN"
    # Camoufox's engine cfg disables Firefox's memory cache (disk-only), which
    # makes every revisit and back/forward re-read from disk and re-fetch over
    # the proxy. Re-enable it by default; operators can turn it off per
    # identity if they want the engine's stock behaviour.
    memory_cache: bool = True


@dataclass
class Identity:
    id: str
    name: str
    created_at: str
    engine_os: str                     # "windows" | "macos" | "linux"
    geo: Geo
    fingerprint: Dict[str, Any]        # full fpgen fingerprint dict (source of truth)
    launcher: Launcher
    network_mode: str = "direct"        # "direct" | "proxy"
    proxy_server: Optional[str] = None  # e.g. "socks5://127.0.0.1:28080" (proxy mode)
    # Clash-style subscription routing: a validated subscription file (stored
    # under <data_root>/subscriptions/) plus the node the operator picked.
    # When both are set, the launcher starts a private mihomo core for this
    # identity and routes the browser through it.
    proxy_source: Optional[str] = None
    proxy_node: Optional[str] = None
    note: str = ""                      # user remark shown in the GUI
    sort_order: int = 0                 # GUI drag-and-drop position
    # Extension-center slugs this environment does NOT load. Unknown slugs are
    # ignored, so a removed extension never blocks a launch; the list is a
    # launch-time switch and never affects the stored fingerprint.
    disabled_extensions: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------ io

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "note": self.note,
            "sort_order": self.sort_order,
            "disabled_extensions": self.disabled_extensions,
            "engine": {"os": self.engine_os},
            "geo": {
                "country": self.geo.country,
                "region": self.geo.region,
                "locale": self.geo.locale,
                "timezone": self.geo.timezone,
                "languages": self.geo.languages,
            },
            "fingerprint": self.fingerprint,
            "launcher": {
                "maxTouchPoints": self.launcher.maxTouchPoints,
                "hardwareConcurrency": self.launcher.hardwareConcurrency,
                "pinned_cores": self.launcher.pinned_cores,
                "ui_locale": self.launcher.ui_locale,
                "memory_cache": self.launcher.memory_cache,
            },
            "network": {
                "mode": self.network_mode,
                "proxy_server": self.proxy_server,
                "proxy_source": self.proxy_source,
                "proxy_node": self.proxy_node,
            },
        }

    def save(self, profiles_dir: Path) -> Path:
        d = Path(profiles_dir) / self.id
        d.mkdir(parents=True, exist_ok=True)
        path = d / "identity.json"
        write_text_atomic(
            path, json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        )
        return path

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Identity":
        geo = data["geo"]
        launcher = data["launcher"]
        network = data.get("network") or {}
        # Legacy files could carry the removed "tor" mode (an old default that
        # never had a running arti behind it). Treat it as direct so launch can
        # never silently fall through without a proxy.
        mode = network.get("mode") or "direct"
        if mode not in ("direct", "proxy"):
            mode = "direct"
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
            engine_os=data["engine"]["os"],
            geo=Geo(
                country=geo["country"],
                region=geo.get("region"),
                locale=geo["locale"],
                timezone=geo["timezone"],
                languages=list(geo.get("languages", [])),
            ),
            fingerprint=data["fingerprint"],
            launcher=Launcher(
                maxTouchPoints=int(launcher["maxTouchPoints"]),
                hardwareConcurrency=int(launcher["hardwareConcurrency"]),
                pinned_cores=bool(launcher.get("pinned_cores", False)),
                ui_locale=launcher.get("ui_locale", "zh-CN"),
                memory_cache=bool(launcher.get("memory_cache", True)),
            ),
            network_mode=mode,
            proxy_server=network.get("proxy_server"),
            proxy_source=network.get("proxy_source"),
            proxy_node=network.get("proxy_node"),
            note=data.get("note", ""),
            sort_order=int(data.get("sort_order", 0)),
            disabled_extensions=[
                str(slug) for slug in (data.get("disabled_extensions") or [])
            ],
        )

    @classmethod
    def load(cls, identity_file: Path) -> "Identity":
        return cls.from_dict(
            json.loads(Path(identity_file).read_text(encoding="utf-8"))
        )

    def violations(self) -> List[str]:
        """All coherence violations of this identity (empty = coherent)."""
        return validate_identity(self)

    def warnings(self) -> List[str]:
        """Soft problems camoufox repairs at launch (clamps); not blocking."""
        from .validate import warn_identity

        return warn_identity(self)

    def update_meta(
        self,
        *,
        name: Optional[str] = None,
        note: Optional[str] = None,
        network_mode: Optional[str] = None,
        proxy_server: Optional[str] = None,
        proxy_source: Optional[str] = None,
        proxy_node: Optional[str] = None,
        clear_proxy: bool = False,
        ui_locale: Optional[str] = None,
        memory_cache: Optional[bool] = None,
        disabled_extensions: Optional[List[str]] = None,
        profiles_dir: Path = Path("profiles"),
    ) -> "Identity":
        """Edit user-facing metadata only. The fingerprint is immutable by
        design: a live identity whose device changes breaks site continuity
        (canvas/audio/UA all shift under the same cookies). Name, note,
        network routing and the operator's UI language are safe to edit."""
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("name cannot be empty")
            self.name = name
        if note is not None:
            self.note = note
        if ui_locale is not None:
            # "" -> follow the identity locale (maximum mimicry)
            self.launcher.ui_locale = ui_locale or None
        if memory_cache is not None:
            self.launcher.memory_cache = bool(memory_cache)
        if disabled_extensions is not None:
            # Extension switches are a launch-time choice; they are safe to edit
            # while the browser runs (they land on the next start).
            self.disabled_extensions = list(dict.fromkeys(
                str(slug).strip() for slug in disabled_extensions if str(slug).strip()
            ))
        if network_mode is not None:
            if network_mode not in ("proxy", "direct"):
                raise ValueError(f"unsupported network mode {network_mode!r}")
            self.network_mode = network_mode
        if clear_proxy:
            self.proxy_server = None
            self.proxy_source = None
            self.proxy_node = None
        elif proxy_server is not None:
            value = proxy_server.strip()
            # Same convenience as create: "127.0.0.1:8080" means HTTP.
            if value and "://" not in value:
                value = f"http://{value}"
            self.proxy_server = value or None
        # None = leave untouched; "" = clear (the GUI always sends both).
        if proxy_source is not None:
            self.proxy_source = proxy_source.strip() or None
        if proxy_node is not None:
            self.proxy_node = proxy_node.strip() or None
        if self.network_mode == "proxy" and not self.proxy_server and not (
            self.proxy_source and self.proxy_node
        ):
            raise ValueError(
                "proxy mode requires proxy_server or proxy_source + proxy_node"
            )
        self.save(profiles_dir)
        return self


# --------------------------------------------------------------- extraction


def _extract_geo(fp: Dict[str, Any]) -> Geo:
    """Pull the identity's own geo facts out of an fpgen fingerprint.

    fpgen draws come from real devices, so location/locale/timezone/languages
    are already mutually coherent -- we persist them as first-class fields
    instead of re-deriving (and possibly contradicting) them later.
    """
    location = fp.get("location") or {}
    intl = fp.get("intl") or {}
    nav = fp.get("navigator") or {}
    country = (location.get("country") or "").upper()
    if not country:
        raise ValueError("fingerprint carries no location.country; cannot build geo")
    locale = intl.get("locale") or nav.get("language") or "en-US"
    timezone = intl.get("timeZone") or "UTC"
    languages = list(nav.get("languages") or [locale])
    return Geo(
        country=country,
        region=location.get("region"),
        locale=locale,
        timezone=timezone,
        languages=languages,
    )


def _host_snapped_cores() -> int:
    import os

    from camoufox.fingerprints import PLAUSIBLE_CORE_COUNTS

    try:
        n = len(os.sched_getaffinity(0))
    except AttributeError:
        n = os.cpu_count() or 8
    allowed = [c for c in PLAUSIBLE_CORE_COUNTS if c <= n]
    return allowed[-1] if allowed else PLAUSIBLE_CORE_COUNTS[0]


def _os_of_fingerprint(fp: Dict[str, Any]) -> str:
    """The OS a fingerprint claims, in camoufox terms."""
    ua = (fp.get("navigator") or {}).get("userAgent") or ""
    platform = ((fp.get("navigator") or {}).get("platform") or "").lower()
    if "macintosh" in ua.lower() or "mac" in platform:
        return "macos"
    if "windows" in ua.lower() or "win" in platform:
        return "windows"
    if "linux" in ua.lower() or "linux" in platform:
        return "linux"
    raise ValueError(f"cannot determine OS from UA {ua!r}")


# ---------------------------------------------------------------- creation


def next_sort_order(profiles_dir: Path) -> int:
    """One past the highest stored sort_order (0 when none exist)."""
    highest = -1
    root = Path(profiles_dir)
    if root.is_dir():
        for child in root.iterdir():
            f = child / "identity.json"
            if not f.is_file():
                continue
            try:
                highest = max(
                    highest,
                    int(json.loads(f.read_text(encoding="utf-8")).get("sort_order", 0)),
                )
            except (OSError, ValueError, TypeError):
                continue
    return highest + 1


def create_identity(
    name: str,
    *,
    os: Optional[str] = None,
    country: Optional[str] = None,
    profiles_dir: Path = Path("profiles"),
    max_draws: int = 40,
    network_mode: str = "direct",
    proxy_server: Optional[str] = None,
    proxy_source: Optional[str] = None,
    proxy_node: Optional[str] = None,
    note: str = "",
    ui_locale: str = "zh-CN",
    memory_cache: bool = True,
    sort_order: Optional[int] = None,
    persist: bool = True,
) -> Identity:
    """Draw a new identity.

    Draws from fpgen until the result passes validation and (optionally)
    matches the requested country; then persists it. Refusing to save an
    incoherent identity is the whole point: the validator is the gate.
    """
    from camoufox.fingerprints import generate_fingerprint

    if os is not None and os not in VALID_OS:
        raise ValueError(f"unsupported os {os!r}, one of {VALID_OS}")
    if network_mode not in ("proxy", "direct"):
        raise ValueError(f"unsupported network mode {network_mode!r}")
    proxy_server = (proxy_server or "").strip() or None
    proxy_source = (proxy_source or "").strip() or None
    proxy_node = (proxy_node or "").strip() or None
    if proxy_server and "://" not in proxy_server:
        # HTTP is the least surprising default for a plain host:port input.
        proxy_server = f"http://{proxy_server}"
    if network_mode == "proxy" and not (
        proxy_server or (proxy_source and proxy_node)
    ):
        raise ValueError(
            "proxy mode requires proxy_server or proxy_source + proxy_node"
        )
    want_country = country.upper() if country else None
    # Country-filtered draws reject most of the pool, so widen the budget:
    # 40 fast draws is not enough at ~5-10% hit rate (flaky CI / flaky users).
    draws_budget = max_draws * (3 if want_country else 1)
    order = next_sort_order(profiles_dir) if sort_order is None else int(sort_order)

    last_violations: List[str] = []
    for attempt in range(draws_budget):
        fp = generate_fingerprint(os=os)
        fp_dict = fp if isinstance(fp, dict) else fp.__dict__
        drawn_os = _os_of_fingerprint(fp_dict)
        if want_country:
            defaults = COUNTRY_DEFAULTS.get(want_country)
            if defaults:
                locale, timezone, languages = defaults
                # Keep the generated hardware/OS fingerprint, but make the
                # explicitly selected geo deterministic and internally
                # coherent. This avoids flaky country creation from sparse or
                # mismatched samples in the upstream pool.
                fp_dict.setdefault("location", {})["country"] = want_country
                fp_dict["location"]["region"] = None
                fp_dict.setdefault("intl", {})["locale"] = locale
                fp_dict["intl"]["timeZone"] = timezone
                nav = fp_dict.setdefault("navigator", {})
                nav["language"] = locale
                nav["languages"] = list(languages)
            else:
                geo = _extract_geo(fp_dict)
                if geo.country != want_country:
                    continue

        geo = _extract_geo(fp_dict)
        identity = Identity(
            id=uuid.uuid4().hex[:12],
            name=name,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            engine_os=drawn_os,
            geo=geo,
            fingerprint=fp_dict,
            launcher=Launcher(
                maxTouchPoints=int((fp_dict.get("navigator") or {}).get("maxTouchPoints") or 0),
                hardwareConcurrency=_host_snapped_cores(),
                # Browser chrome is Chinese by default (readable menus);
                # the web-facing locale still follows the country. "" =
                # follow the identity locale for maximum consistency.
                ui_locale=ui_locale or None,
                memory_cache=memory_cache,
            ),
            network_mode=network_mode,
            proxy_server=proxy_server if network_mode == "proxy" else None,
            proxy_source=proxy_source if network_mode == "proxy" else None,
            proxy_node=proxy_node if network_mode == "proxy" else None,
            note=note,
            sort_order=order,
        )
        violations = identity.violations()
        if not violations:
            if persist:
                identity.save(profiles_dir)
            return identity
        last_violations = violations

    raise ValueError(
        f"could not draw a coherent identity in {draws_budget} attempts; "
        f"last violations: {last_violations[:5]}"
    )
