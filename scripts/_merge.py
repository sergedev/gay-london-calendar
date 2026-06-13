"""Shared merge helper to keep refresh / enrich scripts idempotent.

Authoritative fields (those reflecting the source of truth: title, time, price,
sold-out, attendees, etc.) are always overwritten from the freshly-scraped
record. Anything else on the existing on-disk record is preserved — that
includes any human edits like category overrides, custom labels, area tags,
notes, or fields we add to the schema in the future.

Rule of thumb when adding a new field:
  - Source-controlled (scraper knows the truth) → add to AUTHORITATIVE_FIELDS
  - User-controlled (manual edits should survive a re-scrape) → leave it out
"""

AUTHORITATIVE_FIELDS = frozenset({
    'source', 'id',
    'title', 'start', 'end', 'location', 'locationNote',
    'price', 'soldOut',
    'attendees', 'attendeeLimit',
    'url', 'image', 'links',
    'status', 'recurrence',
    'description',
})


def merge_preserving_custom(new, existing):
    """Return a record that uses `new` for authoritative fields and falls back
    to `existing` for anything else. New record wins for ties on non-auth
    fields *only when existing doesn't have them*.
    """
    if not existing:
        return dict(new)
    result = dict(existing)
    for k in AUTHORITATIVE_FIELDS:
        if k in new:
            result[k] = new[k]
    for k, v in new.items():
        if k not in AUTHORITATIVE_FIELDS and k not in result:
            result[k] = v
    return result
