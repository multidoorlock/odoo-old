import re


TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")


def clean_text(value):
    """Return a predictable single-line value without changing punctuation."""
    if value in (None, False):
        return ""
    return " ".join(str(value).split())


def normalize_token(value):
    return clean_text(value).casefold()


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
        if key not in normalized or not normalized[key]:
            unresolved.append(token)
            return match.group(0)
        return normalized[key]

    rendered = TOKEN_RE.sub(replace, format_value or "")
    return clean_text(rendered), unresolved

