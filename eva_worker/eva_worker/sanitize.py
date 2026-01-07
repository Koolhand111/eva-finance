import re

# Matches URLs like http://..., https://...
URL_RE = re.compile(r"https?://\S+")

# Matches Reddit-style usernames like u/username
USER_RE = re.compile(r"\bu/([A-Za-z0-9_-]+)\b")


def sanitize_text(
    text: str,
    *,
    sanitize_urls: bool = True,
    sanitize_usernames: bool = True
) -> str:
    """
    Create a display-safe version of raw evidence text.

    IMPORTANT:
    - This does NOT replace the canonical record.
    - Raw text should still be stored in the evidence bundle.
    - This function is ONLY for excerpts shown in Markdown.

    Goals:
    - Remove accidental PII exposure (usernames, links)
    - Preserve meaning and tone
    - Keep output calm and readable
    """

    t = (text or "").strip()

    if sanitize_urls:
        t = URL_RE.sub("[link removed]", t)

    if sanitize_usernames:
        t = USER_RE.sub("u/[user]", t)

    # Collapse excessive newlines
    t = re.sub(r"\n{3,}", "\n\n", t)

    return t.strip()
