"""The name to show for each record of a FILE, in a report and on a page.

A report in words names PERSONs, PLACEs, OPTIONs and the rest by their names. A page shows
the lines of a report beside its drawings. So both use one rule for which name to show, and
a name that a page shows like another one comes with its id in the report too.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

_WITH_AN_ID = re.compile(r" \([a-z0-9]+(-[a-z0-9]+)*\)$")  # how a name ends when its id is shown
# The words that a report uses in place of a name: "nobody takes part", "people need a
# right", "there is none", "none refuses the bags", "another WAY". A page has one more, for
# a step with nobody in it.
_NO_NAMES = frozenset(
    {
        "nobody",
        "everybody",
        "somebody",
        "anybody",
        "whoever",
        "people",
        "none",
        "there is none",
        "another way",
        "nobody of the trip",
    }
)
# What a page shows nothing for: the characters that Unicode calls default ignorable. A soft
# hyphen, a space of no width, a mark of direction, a character that joins two others, and one
# that only says how the sign before it is drawn.
_UNSEEN = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e"
    "\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8"
    "\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)


class Named(Protocol):
    """A record of a FILE that has an id and a name."""

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


def seen_as(name: str) -> str:
    """A name as a page shows it, so that two names that a page shows alike are the same.

    It is without the characters that a page shows nothing for, with each accent joined to
    its letter, and with each run of spaces as one space. A format character is left out too:
    a page shows nothing for most of them. A character that is another one set in another way
    counts as that one, as Unicode has it: two letters drawn as one sign, a wide letter, a
    space or a hyphen that does not break.

    This stops there. A letter of another alphabet that is drawn like one of this alphabet is
    another letter, and a dash is no hyphen.
    """
    plain = unicodedata.normalize("NFKC", name).replace("\u2010", "-")
    seen = "".join(each for each in _UNSEEN.sub("", plain) if unicodedata.category(each) != "Cf")
    return " ".join(seen.split())


def to_show(records: Sequence[Named], joins: str | None = None) -> dict[str, str]:
    """The name to show for each record, so that no two records show the same.

    A record whose name another record has shows its id too. Two names count as the same
    where a page shows them alike, as ``seen_as`` tells it: they differ only in how an accent
    is set, in their spaces, or in characters that a page shows nothing for. If two would
    still show the same, every record shows its id: no two ids are the same. Each name is
    printed in the spelling of the FILE.

    A name is shown in quotes where it could be taken for something else: one with a comma,
    a colon, a semicolon or a quote mark, one that ends like a name with its id, one that
    holds the word ``joins``, which joins the list the names are for, and one that is a
    word the report uses in place of a name. A PERSON can be called nobody, and "visit,
    nobody" would read as a visit with nobody in it. A name holds a word where a page shows
    it so. The quotes go on before the id.
    """
    shared = Counter(seen_as(record.name) for record in records)
    shown = {
        record.id: _quoted(record.name, joins)
        if shared[seen_as(record.name)] == 1
        else f"{_quoted(record.name, joins)} ({record.id})"
        for record in records
    }
    if len({seen_as(name) for name in shown.values()}) < len(shown):
        return {record.id: f"{_quoted(record.name, joins)} ({record.id})" for record in records}
    return shown


def _quoted(name: str, joins: str | None) -> str:
    """A name, in quotes where it could be taken for something else."""
    looks = seen_as(name)  # a word of the name is a word that a page shows
    marks = any(mark in name for mark in ",:;")  # what a report puts between its own parts
    splits = marks or (joins is not None and joins in looks.casefold().split())
    stands_in = looks.casefold() in _NO_NAMES
    if splits or stands_in or '"' in name or _WITH_AN_ID.search(looks):
        return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return name
