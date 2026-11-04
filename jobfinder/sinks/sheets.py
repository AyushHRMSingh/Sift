"""Google Sheets sink (framework only, not implemented yet).

Plan:
  - Auth: a Google service account; put its JSON key at data/google_service_account.json and share the
    target sheet with the service account's email. Sheet id comes from env SHEETS_ID.
  - Library: `gspread` (pip install gspread) -> gc = gspread.service_account(filename=...);
    ws = gc.open_by_key(SHEETS_ID).sheet1
  - push_saved: ws.append_row([saved_at, title, company, city, match, link, status]).
  - push_status: find the row by link (ws.find) and update the status cell.
Enable with SINKS=sheets once implemented.
"""
from . import Sink, register


@register
class GoogleSheetsSink(Sink):
    name = "sheets"

    def __init__(self):
        raise NotImplementedError("Google Sheets sink is a placeholder; see jobfinder/sinks/sheets.py")

    def push_saved(self, job: dict) -> None:  # pragma: no cover
        raise NotImplementedError
