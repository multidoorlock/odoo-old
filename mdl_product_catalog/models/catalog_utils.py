import re


TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")
DEFAULT_VARIANT_DISPLAY_FORMAT = "מק״ט [מק״ט] — [שם הפריט]"
VARIANT_DISPLAY_FORMAT_PARAM = "mdl_product_catalog.variant_display_format"


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
