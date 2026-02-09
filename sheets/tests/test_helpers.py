# Copyright (c) 2025, Gavin D'souza and Contributors
# See license.txt

"""Test helpers, fixtures, and mock builders for Sheets integration tests.

This module provides:
- Mock Google Sheets API responses (realistic gspread objects)
- Factory functions for SpreadSheet-related documents
- Data Import result validation helpers
- CSV construction utilities
"""

from csv import reader as csv_reader
from csv import writer as csv_writer
from io import StringIO
from unittest.mock import MagicMock, PropertyMock, patch

import frappe

from sheets.constants import INSERT, UPDATE


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def make_csv(*rows):
    """Create a CSV string from rows (each row is a list of values)."""
    buf = StringIO()
    csv_writer(buf).writerows(rows)
    return buf.getvalue()


def parse_csv(csv_string):
    """Parse a CSV string into a list of lists."""
    return list(csv_reader(StringIO(csv_string)))


# ---------------------------------------------------------------------------
# Google Sheets API mocks
# ---------------------------------------------------------------------------


SAMPLE_TODO_DATA = [
    ["Description", "Status"],
    ["Buy groceries", "Open"],
    ["Walk the dog", "Open"],
    ["Fix the leaky faucet", "Open"],
]

SAMPLE_TODO_DATA_WITH_ID = [
    ["ID", "Description", "Status"],
    ["TODO-001", "Buy groceries", "Open"],
    ["TODO-002", "Walk the dog", "Open"],
    ["TODO-003", "Fix the leaky faucet", "Open"],
]

SAMPLE_TODO_UPDATES = [
    ["ID", "Description", "Status"],
    ["TODO-001", "Buy groceries", "Closed"],
    ["TODO-002", "Walk the dog (updated)", "Open"],
    ["TODO-003", "Fix the leaky faucet", "Open"],
]


def make_mock_worksheet(data=None, worksheet_id=0):
    """Create a mock gspread Worksheet object with realistic responses.

    Args:
        data: List of lists representing spreadsheet data (header + rows).
              Defaults to SAMPLE_TODO_DATA.
        worksheet_id: The worksheet gid. Defaults to 0.
    """
    if data is None:
        data = SAMPLE_TODO_DATA

    mock_ws = MagicMock()
    mock_ws.id = worksheet_id
    mock_ws.title = f"Sheet{worksheet_id + 1}"
    mock_ws.get_all_values.return_value = data
    mock_ws.row_values.return_value = data[0] if data else []
    return mock_ws


def make_mock_spreadsheet(worksheets=None, title="Test Spreadsheet"):
    """Create a mock gspread Spreadsheet object.

    Args:
        worksheets: List of mock worksheet objects. If None, creates one
                    default worksheet with SAMPLE_TODO_DATA.
        title: The spreadsheet title.
    """
    if worksheets is None:
        worksheets = [make_mock_worksheet()]

    mock_ss = MagicMock()
    mock_ss.title = title
    mock_ss.worksheets.return_value = worksheets

    ws_by_id = {ws.id: ws for ws in worksheets}
    mock_ss.get_worksheet_by_id.side_effect = lambda wid: ws_by_id.get(wid)
    return mock_ss


def make_mock_gspread_client(spreadsheet=None):
    """Create a mock gspread Client that returns the given spreadsheet.

    Args:
        spreadsheet: A mock spreadsheet object. If None, creates a default one.
    """
    if spreadsheet is None:
        spreadsheet = make_mock_spreadsheet()

    mock_client = MagicMock()
    mock_client.open_by_url.return_value = spreadsheet
    mock_client.http_client.auth.service_account_email = "test@test-project.iam.gserviceaccount.com"
    return mock_client


# ---------------------------------------------------------------------------
# Document factory helpers
# ---------------------------------------------------------------------------


def ensure_allow_import(doctype="ToDo"):
    """Enable allow_import on a DocType if not already set (needed for Frappe v16+).

    Returns the original value so the caller can restore it in tearDown.
    """
    original = frappe.db.get_value("DocType", doctype, "allow_import")
    if not original:
        frappe.db.set_value("DocType", doctype, "allow_import", 1)
        frappe.clear_cache(doctype=doctype)
    return original


def restore_allow_import(doctype="ToDo", original_value=None):
    """Restore allow_import to its original value."""
    if not original_value:
        frappe.db.set_value("DocType", doctype, "allow_import", 0)
        frappe.clear_cache(doctype=doctype)


def make_worksheet_mapping(
    mapped_doctype="ToDo",
    worksheet_id=0,
    import_type="Insert",
    counter=1,
    mute_emails=1,
    submit_after_import=0,
    skip_failures=0,
    parent_name="test-spreadsheet",
    parent_sheet_name="Test Sheet",
    mock_parent=None,
):
    """Create a DocTypeWorksheetMapping instance with all required attributes.

    Returns (mapping, mock_parent) tuple.
    """
    from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
        DocTypeWorksheetMapping,
    )

    mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
    mapping.mapped_doctype = mapped_doctype
    mapping.worksheet_id = worksheet_id
    mapping.import_type = import_type
    mapping.counter = counter
    mapping.mute_emails = mute_emails
    mapping.submit_after_import = submit_after_import
    mapping.skip_failures = skip_failures
    mapping.last_import = None
    mapping.last_update_import = None
    mapping.reset_worksheet_on_import = False
    mapping.name = f"test-mapping-{frappe.generate_hash(length=6)}"
    mapping.flags = frappe._dict()
    mapping.docstatus = 0
    mapping.doctype = "DocType Worksheet Mapping"

    # Child table fields
    mapping.parenttype = "SpreadSheet"
    mapping.parent = parent_name
    mapping.parentfield = "worksheet_ids"
    mapping.idx = 1

    if mock_parent is None:
        mock_parent = MagicMock()
    mock_parent.sheet_name = parent_sheet_name
    mock_parent.name = parent_name

    return mapping, mock_parent


# ---------------------------------------------------------------------------
# Data Import validation helpers
# ---------------------------------------------------------------------------


def get_import_status(data_import_name):
    """Get the status of a Data Import document."""
    return frappe.db.get_value("Data Import", data_import_name, "status")


def get_import_file_content(data_import_name):
    """Read the CSV content of a Data Import's attached file."""
    import_file_url = frappe.db.get_value("Data Import", data_import_name, "import_file")
    if not import_file_url:
        return None
    file_doc = frappe.get_doc("File", {"file_url": import_file_url})
    return file_doc.get_content()


def get_imported_rows(data_import_name):
    """Parse the Data Import's CSV file and return rows as list of lists."""
    content = get_import_file_content(data_import_name)
    if content is None:
        return []
    return parse_csv(content)


def count_data_rows(data_import_name):
    """Count data rows (excluding header) in a Data Import's CSV file."""
    rows = get_imported_rows(data_import_name)
    return max(0, len(rows) - 1)


def cleanup_data_import(data_import_name):
    """Delete a Data Import and its attached file."""
    if data_import_name and frappe.db.exists("Data Import", data_import_name):
        frappe.delete_doc("Data Import", data_import_name, force=True)


def cleanup_todos(descriptions):
    """Delete ToDo documents matching the given descriptions."""
    for desc in descriptions:
        for name in frappe.get_all("ToDo", filters={"description": desc}, pluck="name"):
            frappe.delete_doc("ToDo", name, force=True)


# ---------------------------------------------------------------------------
# Context managers for parent_doc patching
# ---------------------------------------------------------------------------


def patch_parent_doc(mock_parent):
    """Return a context manager that patches parent_doc on DocTypeWorksheetMapping.

    Usage:
        mapping, mock_parent = make_worksheet_mapping()
        with patch_parent_doc(mock_parent):
            mapping.do_something()
    """
    from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
        DocTypeWorksheetMapping,
    )

    return patch.object(
        DocTypeWorksheetMapping,
        "parent_doc",
        new_callable=PropertyMock,
        return_value=mock_parent,
    )
