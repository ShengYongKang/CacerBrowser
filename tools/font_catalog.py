"""Build language packs and an auditable file/family index from the actual engine.

fontTools is a build dependency only. Country recommendations include UI language;
identity-declared families are resolved separately so OS fonts are not discarded.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

LABELS = {
    "base": "公共字体 / 符号 / Emoji", "latin": "拉丁文补充字体",
    "latin-code": "Iosevka 编程字体补充",
    "hans": "简体中文", "hant": "繁体中文", "ja": "日文", "ko": "韩文",
    "arabic": "阿拉伯文", "hebrew": "希伯来文", "indic": "印度文字",
    "thai": "泰文", "cyrillic": "西里尔文", "other": "其他文字与补充字体",
}
LOCALES = {
    "zh": ["hans"], "zh-CN": ["hans"], "zh-SG": ["hans"],
    "zh-TW": ["hant"], "zh-HK": ["hant"], "zh-MO": ["hant"], "zh-Hant": ["hant"],
    "ja": ["ja"], "ko": ["ko"], "ar": ["arabic"], "fa": ["arabic"],
    "ur": ["arabic"], "he": ["hebrew"], "hi": ["indic"], "bn": ["indic"],
    "ta": ["indic"], "te": ["indic"], "mr": ["indic"], "gu": ["indic"],
    "kn": ["indic"], "ml": ["indic"], "pa": ["indic"], "si": ["indic"],
    "ne": ["indic"], "th": ["thai"], "ru": ["cyrillic"], "uk": ["cyrillic"],
    "bg": ["cyrillic"], "sr": ["cyrillic"], "mk": ["cyrillic"],
}
LATIN_LANGUAGES = "en fr de es it nl sv pt da no nb nn fi is pl cs sk sl hr hu ro tr vi id ms fil tl sw af ca eu gl et lv lt sq az".split()
LOCALES.update({language: [] for language in LATIN_LANGUAGES})


def classify(filename: str, characters: set[int]) -> str:
    name = Path(filename).stem.lower()
    if "iosevka" in name:
        return "latin-code"
    # Named regional CJK faces take precedence over their overlapping cmaps.
    for group, words in (
        ("hant", ("hant", "jheng", "msjh", "mingliu", "biau", "lisong", "lihei", "heititc", "songtitc")),
        ("hans", ("hans", "msyh", "simsun", "simhei", "fangsong", "kaiti", "deng", "heitisc", "songtisc")),
        ("ko", ("korean", "malgun", "applegothic", "applemyungjo", "batang", "gulim", "dotum")),
        ("ja", ("japan", "hiragino", "yugoth", "yumin", "msgothic", "msmincho", "osaka")),
    ):
        if any(word in name for word in words):
            return group
    count = lambda start, end: sum(start <= point <= end for point in characters)
    if count(0xAC00, 0xD7AF) > 500:
        return "ko"
    if count(0x4E00, 0x9FFF) > 1000:
        if "tc" in name or "traditional" in name:
            return "hant"
        if "sc" in name or "simplified" in name:
            return "hans"
        if count(0x3040, 0x30FF) > 80:
            return "ja"
        return "hans"
    for group, start, end, threshold in (
        ("indic", 0x0900, 0x0DFF, 35), ("thai", 0x0E00, 0x0E7F, 30),
        ("arabic", 0x0600, 0x06FF, 40), ("hebrew", 0x0590, 0x05FF, 25),
    ):
        if count(start, end) > threshold and count(0x0020, 0x007E) < 80:
            return group
    if any(word in name for word in ("noto", "devanagari", "sangam", "arabic", "hebrew")):
        for group, start, end in (("indic", 0x0900, 0x0DFF), ("thai", 0x0E00, 0x0E7F),
                                  ("arabic", 0x0600, 0x06FF), ("hebrew", 0x0590, 0x05FF)):
            if count(start, end) > 25:
                return group
    if count(0x0400, 0x052F) > 40 and count(0x0020, 0x007E) < 80:
        return "cyrillic"
    if any(word in name for word in (
        "arial", "times", "courier", "segoe", "tahoma", "verdana", "calibri",
        "cambria", "consol", "liberation", "dejavu", "cantarell", "nimbus",
        "emoji", "symbol", "wingding", "webding", "noto sans.", "notosans[",
        "notoserif[", "sfns", "helvetica", "menlo", "pingfang",
    )):
        return "base"
    return "latin" if count(0x0020, 0x007E) > 80 else "other"


def inspect_font(path: Path) -> tuple[list[str], set[int]]:
    from fontTools.ttLib import TTCollection, TTFont
    if path.suffix.lower() in {".t1", ".pfb"}:
        from fontTools.t1Lib import T1Font
        font = T1Font(path)
        info = font["FontInfo"]
        values = [font["FontName"], info.get("FamilyName", ""), info.get("FullName", "")]
        return sorted({value.decode("latin-1") if isinstance(value, bytes) else value
                       for value in values if value}), set(range(32, 127))
    if path.suffix.lower() not in {".ttf", ".otf", ".ttc", ".otc"}:
        return [], set()
    collection = TTCollection(path, lazy=True) if path.suffix.lower() in {".ttc", ".otc"} else None
    fonts = collection.fonts if collection else [TTFont(path, lazy=True)]
    names, characters = set(), set()
    try:
        for font in fonts:
            for record in font["name"].names:
                if record.nameID in {1, 4, 6, 16}:
                    try:
                        names.add(record.toUnicode().strip())
                    except UnicodeError:
                        pass
            characters.update((font.getBestCmap() or {}).keys())
    finally:
        for font in fonts:
            font.close()
    return sorted(name for name in names if name), characters


def index_fonts(source: Path) -> dict:
    files, families = {}, defaultdict(set)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if path.suffix.lower() in {".json", ".conf"}:
            group, names = "base", []
        else:
            names, characters = inspect_font(path)
            group = classify(path.name, characters)
        files[relative] = {"group": group, "families": names, "size": path.stat().st_size}
        for family in names:
            families[family.lower()].add(group)
    if not files:
        raise ValueError("The font bundle is empty")
    return {
        "schema": 1, "locales": LOCALES, "labels": LABELS,
        "files": files, "families": {name: sorted(groups) for name, groups in sorted(families.items())},
    }
