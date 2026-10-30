"""The single source of truth for filenames: ``<stem>_<province>_<city>_<YYMMDD><ext>``.

Everything here is pure (no filesystem, no metadata) so the mobile app can port it
against the same golden cases in ``tests/fixtures/naming_cases.json``.
"""

from __future__ import annotations

import re

PROVINCE_SHORT = {
    "内蒙古自治区": "内蒙古",
    "广西壮族自治区": "广西",
    "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "香港特别行政区": "香港",
    "澳门特别行政区": "澳门",
}

LEVEL_SUFFIX_RE = re.compile(r"(自治州|自治县|自治旗|特别行政区|自治区|地区|省|市|盟|县|林区)$")

_ETHNIC_STEMS = sorted(
    {
        "土家",
        "蒙古",
        "朝鲜",
        "维吾尔",
        "哈萨克",
        "柯尔克孜",
        "塔吉克",
        "乌孜别克",
        "俄罗斯",
        "鄂温克",
        "鄂伦春",
        "达斡尔",
        "锡伯",
        "满",
        "回",
        "藏",
        "彝",
        "苗",
        "侗",
        "布依",
        "傣",
        "白",
        "哈尼",
        "壮",
        "羌",
        "傈僳",
        "拉祜",
        "佤",
        "纳西",
        "景颇",
        "黎",
        "瑶",
        "畲",
        "东乡",
        "仫佬",
        "布朗",
        "撒拉",
        "毛南",
        "仡佬",
        "阿昌",
        "普米",
        "德昂",
        "保安",
        "裕固",
        "塔塔尔",
        "独龙",
        "赫哲",
        "门巴",
        "珞巴",
        "基诺",
    },
    key=len,
    reverse=True,
)

_BARE_ETHNIC = sorted({"蒙古", "柯尔克孜", "维吾尔", "哈萨克", "达斡尔"}, key=len, reverse=True)

#: ``name_province_city_YYMMDD``; province/city must contain a non-digit character.
_EXISTING_RE = re.compile(r"^(?P<base>.+)_(?P<prov>[^_\d]+)_(?P<city>[^_\d]+)_(?P<date>\d{6})$")

_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_DATE_RE = re.compile(r"(\d{4})[-:](\d{2})[-:](\d{2})")


def clean_province(name: str) -> str:
    short = PROVINCE_SHORT.get(name)
    if short:
        return short
    return LEVEL_SUFFIX_RE.sub("", name)


def clean_city(name: str) -> str:
    was_prefecture = name.endswith("自治州")
    name = LEVEL_SUFFIX_RE.sub("", name)
    changed = True
    while changed:
        changed = False
        for stem in _ETHNIC_STEMS:
            token = stem + "族"
            if name.endswith(token) and len(name) > len(token):
                name = name[: -len(token)]
                changed = True
                break
    if was_prefecture:
        for stem in _BARE_ETHNIC:
            if name.endswith(stem) and len(name) > len(stem):
                name = name[: -len(stem)]
                break
    return name


def _valid_month_day(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def format_date(raw: str | None) -> str | None:
    """Normalise EXIF/ffprobe dates (or an existing ``YYMMDD``) to ``YYMMDD``."""
    if not raw:
        return None
    raw = str(raw).strip()

    if re.fullmatch(r"\d{6}", raw):
        if _valid_month_day(int(raw[2:4]), int(raw[4:6])):
            return raw
        return None

    match = _DATE_RE.search(raw)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not _valid_month_day(month, day):
        return None
    return f"{year % 100:02d}{month:02d}{day:02d}"


_CONFLICT_SUFFIX_RE = re.compile(r"_\d+$")


def parse_existing(stem: str) -> tuple[str, str | None]:
    """Split an already-suffixed stem into ``(base_stem, old_suffix)``.

    ``IMG_1234_江苏_南京_240815`` -> ``("IMG_1234", "江苏_南京_240815")``;
    ``DSC_0047_140620_140620`` -> unchanged (numeric segments are not place names).
    """
    # 冲突后缀（_2、_3 …）不是名字的一部分，先剥掉再判断，否则二次扫描会把它带进 stem
    probe = _CONFLICT_SUFFIX_RE.sub("", stem)
    match = _EXISTING_RE.match(probe) or _EXISTING_RE.match(stem)
    if not match:
        return stem, None
    suffix = f"{match.group('prov')}_{match.group('city')}_{match.group('date')}"
    return match.group("base"), suffix


def build_name(
    stem: str, province: str, city: str, date: str, ext: str, max_bytes: int = 200
) -> str:
    """Build the target filename, replacing (never stacking) an existing suffix.

    超长时只截 *stem*：省市与日期是归档依据，绝不能被截掉。
    """
    if not province or not city:
        raise ValueError("province and city must be non-empty")
    if not date:
        raise ValueError("date must be non-empty")
    base, _old = parse_existing(stem)
    base = sanitize(base)
    tail = f"_{province}_{city}_{date}{ext}"
    # 预留 3 字节给冲突后缀 _2.._99，避免 dedupe 把名字顶过上限
    budget = max_bytes - len(tail.encode("utf-8")) - 3
    if budget <= 0:
        raise ValueError(f"suffix alone exceeds {max_bytes} bytes: {tail}")
    trimmed: list[str] = []
    used = 0
    for ch in base:
        size = len(ch.encode("utf-8"))
        if used + size > budget:
            break
        trimmed.append(ch)
        used += size
    return "".join(trimmed) + tail


def sanitize(name: str, max_bytes: int = 200) -> str:
    """Make *name* safe on Windows/macOS/Linux and keep it under *max_bytes*."""
    cleaned = _ILLEGAL_RE.sub("-", name).strip().rstrip(". ")

    if len(cleaned.encode("utf-8")) <= max_bytes:
        return cleaned

    dot = cleaned.rfind(".")
    stem, ext = (cleaned[:dot], cleaned[dot:]) if dot > 0 else (cleaned, "")
    budget = max_bytes - len(ext.encode("utf-8"))
    trimmed: list[str] = []
    used = 0
    for ch in stem:
        size = len(ch.encode("utf-8"))
        if used + size > budget:
            break
        trimmed.append(ch)
        used += size
    return "".join(trimmed) + ext
