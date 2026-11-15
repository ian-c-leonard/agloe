"""Agloe: a standard format for trips, a compiler that checks them, and an optimizer.

``read`` or ``load`` a FILE, then ``check`` it. ``agloe.report`` puts the Report into words.
"""

from agloe.answers import Answer, Report
from agloe.compiler import check
from agloe.file import File, FileError, load, read

__all__ = ["Answer", "File", "FileError", "Report", "check", "load", "read"]
