"""Importers turn one tool's export into conversations for the store.

To add a new importer, create a module here with a `read_export(path) -> ParsedExport`
function, then add a command for it in contextos/cli.py.
"""

from contextos.importers.base import ImportFailed, ImportResult, ParsedExport, save_all

__all__ = ["ImportFailed", "ImportResult", "ParsedExport", "save_all"]
