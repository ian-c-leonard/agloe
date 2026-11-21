"""The view: a page for a person, served on their own machine by ``agloe view FILE``.

The page shows the COMPILER's answer and report on one FILE, with a calendar of the TRIP, and
follows the FILE as it changes. Nothing in the page judges a TRIP: what it shows comes from the
FILE and from the COMPILER's report on it.

``agloe`` does not import this package by itself. It needs sockets and processes, and the home
page loads ``agloe`` where there are none.
"""

from agloe.view.serve import View

__all__ = ["View"]
