"""Whole-identity consistency validation.

Camoufox's coherence.py already repairs machine-internal contradictions
(OS×GPU×cores×screen) at launch time. This module guards the IDENTITY FILE
itself -- catching corruption, bad manual edits, and cross-layer mistakes
that camoufox either repairs silently or does not look at (the geo layer:
locale region vs country vs timezone vs language).

validate_identity(identity) returns a list of human-readable violations.
An empty list means the identity is coherent and may be launched.
"""

from __future__ import annotations

from typing import List

# Compact country -> valid IANA timezone prefixes, covering the countries the
# fpgen corpus actually draws from. A country missing here falls back to
# continent-level plausibility. Keep prefixes short and prefer whole zones
# where the country spans one or two.
COUNTRY_TIMEZONES = {
    "US": ("America/", "US/"),
    "CA": ("America/",),
    "BR": ("America/Sao_Paulo", "America/Recife", "America/Fortaleza", "America/Bahia", "America/Belem"),
    "MX": ("America/Mexico_City", "America/Monterrey", "America/Tijuana"),
    "AR": ("America/Argentina/", "America/Buenos_Aires"),
    "CL": ("America/Santiago",),
    "GB": ("Europe/London",),
    "IE": ("Europe/Dublin",),
    "FR": ("Europe/Paris",),
    "DE": ("Europe/Berlin", "Europe/Busingen"),
    "AT": ("Europe/Vienna",),
    "CH": ("Europe/Zurich", "Europe/Geneva"),
    "NL": ("Europe/Amsterdam",),
    "BE": ("Europe/Brussels",),
    "SE": ("Europe/Stockholm",),
    "NO": ("Europe/Oslo",),
    "DK": ("Europe/Copenhagen",),
    "FI": ("Europe/Helsinki",),
    "PL": ("Europe/Warsaw",),
    "CZ": ("Europe/Prague",),
    "PT": ("Europe/Lisbon", "Atlantic/Azores"),
    "ES": ("Europe/Madrid", "Atlantic/Canary"),
    "IT": ("Europe/Rome",),
    "GR": ("Europe/Athens",),
    "RU": ("Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Novosibirsk", "Asia/Krasnoyarsk"),
    "UA": ("Europe/Kyiv", "Europe/Kiev", "Europe/Uzhgorod"),
    "TR": ("Europe/Istanbul",),
    "IL": ("Asia/Jerusalem",),
    "AE": ("Asia/Dubai",),
    "SA": ("Asia/Riyadh",),
    "IN": ("Asia/Kolkata", "Asia/Calcutta"),
    "PK": ("Asia/Karachi",),
    "BD": ("Asia/Dhaka",),
    "TH": ("Asia/Bangkok",),
    "VN": ("Asia/Ho_Chi_Minh", "Asia/Saigon"),
    "SG": ("Asia/Singapore",),
    "MY": ("Asia/Kuala_Lumpur",),
    "ID": ("Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"),
    "PH": ("Asia/Manila",),
    "CN": ("Asia/Shanghai", "Asia/Urumqi"),
    "TW": ("Asia/Taipei",),
    "HK": ("Asia/Hong_Kong",),
    "JP": ("Asia/Tokyo",),
    "KR": ("Asia/Seoul",),
    "AU": ("Australia/",),
    "NZ": ("Pacific/Auckland",),
    "ZA": ("Africa/Johannesburg",),
    "EG": ("Africa/Cairo",),
    "NG": ("Africa/Lagos",),
}

# GPU strings no OS can produce (mirrors camoufox.coherence.gpu_fits_os so the
# guard fires BEFORE launch, on the identity file, not just inside camoufox).
_NOT_A_MAC_GPU = ("ANGLE", "llvmpipe")


def _ua_says(ua: str) -> str:
    low = ua.lower()
    if "macintosh" in low or "mac os x" in low:
        return "macos"
    if "windows" in low:
        return "windows"
    if "linux" in low or "x11" in low:
        return "linux"
    return "unknown"


def validate_identity(identity) -> List[str]:
    v: List[str] = []
    fp = identity.fingerprint
    nav = fp.get("navigator") or {}
    ua = nav.get("userAgent") or ""
    platform = nav.get("platform") or ""
    oscpu = nav.get("oscpu") or ""
    screen = fp.get("screen") or {}
    window = fp.get("window") or {}
    gpu = fp.get("gpu") or {}
    geo = identity.geo

    # --- OS layer ---
    ua_os = _ua_says(ua)
    if ua_os == "unknown":
        v.append(f"UA names no OS: {ua!r}")
    elif ua_os != identity.engine_os:
        v.append(f"engine os {identity.engine_os!r} but UA claims {ua_os!r}")
    plat_expect = {"macos": "MacIntel", "windows": "Win32", "linux": "Linux x86_64"}
    if platform and identity.engine_os in plat_expect and platform != plat_expect[identity.engine_os]:
        v.append(f"navigator.platform {platform!r} wrong for {identity.engine_os}")
    if identity.engine_os == "macos" and "Windows" in oscpu:
        v.append(f"oscpu {oscpu!r} contradicts macos identity")
    if "x86_64" in ua and ("armv" in platform.lower() or "armv" in oscpu.lower()):
        v.append("UA claims x86_64 while platform/oscpu claim ARM")

    # --- GPU layer ---
    renderer = gpu.get("renderer") or ""
    if renderer:
        if identity.engine_os == "macos" and any(b in renderer for b in _NOT_A_MAC_GPU):
            v.append(f"macOS identity with GPU {renderer!r} no Mac reports")
        elif identity.engine_os == "windows" and not renderer.startswith("ANGLE"):
            v.append(f"Windows identity with GPU {renderer!r}; Firefox on Windows renders via ANGLE")
        elif identity.engine_os == "linux" and ("ANGLE" in renderer or "Apple M" in renderer):
            v.append(f"Linux identity with GPU {renderer!r} no Linux reports")

    # --- touch layer ---
    if identity.engine_os == "macos" and identity.launcher.maxTouchPoints != 0:
        v.append(f"macOS identity with maxTouchPoints {identity.launcher.maxTouchPoints}; no Mac has a touchscreen")
    if identity.launcher.maxTouchPoints < 0 or identity.launcher.maxTouchPoints > 10:
        v.append(f"maxTouchPoints {identity.launcher.maxTouchPoints} outside 0..10")

    # --- screen layer ---
    w, h = screen.get("width"), screen.get("height")
    if not w or not h:
        v.append("fingerprint has no screen dimensions")
    else:
        if h > w:
            v.append(f"portrait screen {w}x{h}; desktop panels are landscape")
        if w < 1024:
            v.append(f"screen {w}x{h} smaller than any current desktop panel")
    depth = screen.get("colorDepth")
    if depth is not None and depth not in (24, 30):
        v.append(f"screen.colorDepth {depth}; Firefox reports 24 or 30")
    # avail/window out-of-bounds pairs appear in real-device data (DPI
    # scaling artifacts) and camoufox clamps them at launch -> warnings,
    # see warn_identity().
    # --- geo layer (the part camoufox does NOT check) ---
    locale = geo.locale or ""
    region = locale.rsplit("-", 1)[-1] if "-" in locale else ""
    if region and region != geo.country:
        v.append(f"locale {locale!r} region does not match country {geo.country!r}")
    tz_prefixes = COUNTRY_TIMEZONES.get(geo.country)
    if tz_prefixes:
        if not any(geo.timezone.startswith(p) for p in tz_prefixes):
            v.append(f"timezone {geo.timezone!r} is not a {geo.country} zone")
    else:
        if not geo.timezone.count("/"):
            v.append(f"timezone {geo.timezone!r} is not an IANA zone")
    langs = geo.languages or []
    if langs and locale:
        if not langs[0].lower().startswith(locale.split("-")[0].lower()):
            v.append(f"primary language {langs[0]!r} contradicts locale {locale!r}")
    if not geo.timezone:
        v.append("identity has no timezone")

    return v


def warn_identity(identity) -> List[str]:
    """Soft coherence problems: real-device data artifacts that camoufox
    repairs at launch time (clamp_window_dimensions, _repair_avail_bounds).
    They do NOT block launching, but the GUI surfaces them for transparency.
    """
    w: List[str] = []
    screen = identity.fingerprint.get("screen") or {}
    window = identity.fingerprint.get("window") or {}
    sw, sh = screen.get("width"), screen.get("height")
    aw, ah = screen.get("availWidth"), screen.get("availHeight")
    ow, oh = window.get("outerWidth"), window.get("outerHeight")
    if aw and sw and aw > sw:
        w.append(f"screen.availWidth {aw} exceeds screen.width {sw} (clamped at launch)")
    if ah and sh and ah > sh:
        w.append(f"screen.availHeight {ah} exceeds screen.height {sh} (clamped at launch)")
    if ow and sw and ow > sw:
        w.append(f"window.outerWidth {ow} exceeds screen.width {sw} (clamped at launch)")
    if oh and sh and oh > sh:
        w.append(f"window.outerHeight {oh} exceeds screen.height {sh} (clamped at launch)")
    return w
