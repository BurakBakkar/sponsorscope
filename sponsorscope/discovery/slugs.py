from __future__ import annotations

from sponsorscope.matching.names import SHORT_NAME_MAX

MIN_UNVERIFIED_SLUG = 8  # without a company name to check, only long full-name slugs are distinctive


def candidates(norm: str, *, verifiable: bool) -> list[str]:
    """Slugs to probe for a normalised sponsor name (tokens are already [a-z0-9])."""
    tokens = norm.split()
    joined = "".join(tokens)
    if len(joined) <= SHORT_NAME_MAX:
        return []
    out = [joined, "-".join(tokens)]
    if verifiable:
        if len(tokens) > 1 and len(tokens[0]) > SHORT_NAME_MAX:
            out.append(tokens[0])
    elif len(joined) < MIN_UNVERIFIED_SLUG:
        return []
    return list(dict.fromkeys(out))
