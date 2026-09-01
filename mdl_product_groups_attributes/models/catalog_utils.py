import re


TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")
DIRECTION_MARKER_RE = re.compile(r"(?<![A-Za-z])([LRD])(?![A-Za-z])", re.IGNORECASE)
HEBREW_RE = re.compile(r"[\u0590-\u05ff]")
DEFAULT_VARIANT_DISPLAY_FORMAT = "[מק״ט] [שם הפריט]"
VARIANT_DISPLAY_FORMAT_PARAM = (
    "mdl_product_groups_attributes.variant_display_format"
)
BASE_NAME_TOKENS = {
    "שם קבוצת פריטים",
    "קבוצת פריטים",
    "דגם",
    "שם דגם",
}


def clean_text(value):
    """Return a predictable single-line value without changing punctuation."""
    if value in (None, False):
        return ""
    return " ".join(str(value).split())


def normalize_token(value):
    return clean_text(value).casefold()


def ltr_isolate(value):
    """Keep identifiers readable when embedded inside right-to-left text."""
    value = clean_text(value)
    return f"\u2066{value}\u2069" if value else ""


def split_direction_marker(value):
    """Return Hebrew opening text and a deferred L/R/D display marker.

    MasterProducts stores opening values in forms such as ``L שמאל`` and
    ``הזזה ימין R``. In mixed RTL/LTR interfaces the browser moves that marker
    unpredictably. Keeping the Hebrew wording in place and appending the
    marker after the complete generated name produces one stable reading order.
    """
    value = clean_text(value)
    markers = DIRECTION_MARKER_RE.findall(value)
    if not HEBREW_RE.search(value) or len(markers) != 1:
        return value, ""
    text = clean_text(DIRECTION_MARKER_RE.sub(" ", value))
    return text, markers[0].upper()


def extract_tokens(format_value):
    return [clean_text(token) for token in TOKEN_RE.findall(format_value or "")]


def render_format(format_value, replacements):
    """Render [tokens] and return (text, unresolved_tokens)."""
    normalized = {
        normalize_token(key): clean_text(value)
        for key, value in replacements.items()
    }
    unresolved = []

    def replace(match):
        token = clean_text(match.group(1))
        key = normalize_token(token)
        if key not in normalized:
            unresolved.append(token)
            return match.group(0)
        return normalized[key]

    rendered = TOKEN_RE.sub(replace, format_value or "")
    return clean_text(rendered), unresolved


def split_legacy_name_format(format_value, attribute_names):
    """Convert the old token format to native attribute-line presentation rules.

    Unknown bracketed text is intentionally kept as literal text. This preserves
    names such as ``[+ידית]`` from MasterProducts without pretending that they
    are attributes.
    """
    format_value = str(format_value or "")
    attributes_by_key = {
        normalize_token(name): clean_text(name) for name in attribute_names
    }
    base_keys = {normalize_token(name) for name in BASE_NAME_TOKENS}
    recognized = []
    for match in TOKEN_RE.finditer(format_value):
        key = normalize_token(match.group(1))
        if key in base_keys or key in attributes_by_key:
            recognized.append((match, key))

    base_end = max(
        (match.end() for match, key in recognized if key in base_keys),
        default=0,
    )
    attribute_matches = [
        (match, key)
        for match, key in recognized
        if key in attributes_by_key
    ]
    rules = {
        normalize_token(name): {
            "name_mode": "hidden",
            "prefix": "",
            "suffix": "",
            "sequence": None,
        }
        for name in attribute_names
    }
    previous_match = None
    previous_key = None
    for index, (match, key) in enumerate(attribute_matches):
        if previous_match is None:
            rules[key]["prefix"] = format_value[base_end:match.start()]
        else:
            rules[previous_key]["suffix"] = format_value[
                previous_match.end():match.start()
            ]
        rules[key]["name_mode"] = "value"
        rules[key]["sequence"] = (index + 1) * 10
        previous_match = match
        previous_key = key

    final_suffix = (
        format_value[previous_match.end():]
        if previous_match is not None
        else format_value[base_end:]
    )
    return rules, final_suffix
