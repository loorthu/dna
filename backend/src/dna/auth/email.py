"""Email comparison helpers for authorization checks."""


def emails_match(a: str, b: str) -> bool:
    """Return True when two emails refer to the same mailbox (case-insensitive)."""
    return a.strip().lower() == b.strip().lower()


def display_name(email: str) -> str:
    """A human byline for a mailbox, for when nothing else knows the person's name.

    Draft notes store who wrote them as an address and nothing more, so both the notes email and
    the artist review page have to make a name out of one. Doing it in the same place is what
    keeps the same person from appearing as "Jane Smith" in the mail and "jane.smith" on the page
    it links to.
    """
    local = email.split("@")[0]
    return local.replace(".", " ").replace("_", " ").title()
