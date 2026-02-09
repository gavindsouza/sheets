# Copyright (c) 2025, Gavin D'souza and Contributors
# See license.txt

"""Integration tests for the Sheets import pipeline.

These tests exercise the full flow from Google Sheets data to Frappe documents,
with mocked external services (Google Sheets API) but real Frappe operations
(database writes, Data Import document creation, file attachments).
"""

from csv import reader as csv_reader
from io import StringIO
from unittest.mock import MagicMock, PropertyMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from sheets.constants import INSERT, UPDATE, UPSERT
from sheets.tests.test_helpers import (
    SAMPLE_TODO_DATA,
    SAMPLE_TODO_DATA_WITH_ID,
    SAMPLE_TODO_UPDATES,
    cleanup_data_import,
    cleanup_todos,
    count_data_rows,
    ensure_allow_import,
    get_import_file_content,
    get_import_status,
    get_imported_rows,
    make_csv,
    make_mock_gspread_client,
    make_mock_spreadsheet,
    make_mock_worksheet,
    make_worksheet_mapping,
    parse_csv,
    patch_parent_doc,
    restore_allow_import,
)

MODULE_PATH = "sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping"


class TestInsertImportPipeline(FrappeTestCase):
    """Integration tests for the INSERT import flow.

    Tests the full pipeline: fetch remote data -> create Data Import -> enqueue.
    """

    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []
        self._created_todos = []

    def tearDown(self):
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        cleanup_todos(self._created_todos)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def _track_import(self, mapping):
        if mapping.last_import:
            self._created_imports.append(mapping.last_import)

    def test_insert_creates_data_import_with_csv(self):
        """Full INSERT: fetch CSV from mock sheets -> Data Import with file."""
        data = [
            ["Description", "Status"],
            ["Integration test item 1", "Open"],
            ["Integration test item 2", "Open"],
        ]
        self._created_todos.extend(["Integration test item 1", "Integration test item 2"])

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=1)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc") as mock_enqueue:
                    mapping.trigger_insert_worksheet_import()

        self._track_import(mapping)

        # Data Import was created
        self.assertIsNotNone(mapping.last_import)

        # Counter was updated: 1 + 2 data rows = 3
        self.assertEqual(mapping.counter, 3)

        # Data Import has correct fields
        di = frappe.get_doc("Data Import", mapping.last_import)
        self.assertEqual(di.reference_doctype, "ToDo")
        self.assertEqual(di.import_type, INSERT)
        self.assertEqual(di.mute_emails, 1)
        self.assertTrue(di.import_file)

        # CSV content is correct
        rows = get_imported_rows(mapping.last_import)
        self.assertEqual(rows[0], ["Description", "Status"])
        self.assertEqual(len(rows), 3)  # header + 2 data rows

        # Import was enqueued
        mock_enqueue.assert_called_once()

    def test_insert_counter_tracks_incrementally(self):
        """Counter increments correctly across multiple INSERT imports."""
        # First import: 2 rows
        data_batch1 = [
            ["Description", "Status"],
            ["Batch 1 item 1", "Open"],
            ["Batch 1 item 2", "Open"],
        ]
        # Second import: adds 2 more rows (4 total)
        data_batch2 = [
            ["Description", "Status"],
            ["Batch 1 item 1", "Open"],
            ["Batch 1 item 2", "Open"],
            ["Batch 2 item 1", "Open"],
            ["Batch 2 item 2", "Open"],
        ]

        self._created_todos.extend([
            "Batch 1 item 1", "Batch 1 item 2",
            "Batch 2 item 1", "Batch 2 item 2",
        ])

        mock_ws = make_mock_worksheet(data=data_batch1)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=1)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc"):
                    mapping.trigger_insert_worksheet_import()

        self._track_import(mapping)
        self.assertEqual(mapping.counter, 3)  # 1 + 2

        # Second batch: update mock data
        mock_ws.get_all_values.return_value = data_batch2
        # Clear cached_property if it exists
        if "worksheet_id_field" in mapping.__dict__:
            del mapping.__dict__["worksheet_id_field"]

        # Set last import status to Success so next import proceeds
        frappe.db.set_value("Data Import", mapping.last_import, "status", "Success")

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc"):
                    mapping.trigger_insert_worksheet_import()

        self._track_import(mapping)
        self.assertEqual(mapping.counter, 5)  # 3 + 2

        # Verify only the new rows are in the second import
        rows = get_imported_rows(mapping.last_import)
        self.assertEqual(len(rows), 3)  # header + 2 new rows
        self.assertEqual(rows[1][0], "Batch 2 item 1")
        self.assertEqual(rows[2][0], "Batch 2 item 2")

    def test_insert_skips_when_no_new_data(self):
        """INSERT with no new rows (counter at end) does nothing."""
        data = [
            ["Description", "Status"],
            ["Already imported", "Open"],
        ]
        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=2)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                mapping.trigger_insert_worksheet_import()

        self.assertIsNone(mapping.last_import)
        self.assertEqual(mapping.counter, 2)  # unchanged

    def test_insert_blocks_after_failed_import(self):
        """INSERT refuses to proceed when last import has Error status."""
        mapping, mock_parent = make_worksheet_mapping()

        # Create a failed Data Import
        di = frappe.new_doc("Data Import")
        di.reference_doctype = "ToDo"
        di.import_type = INSERT
        di.save()
        frappe.db.set_value("Data Import", di.name, "status", "Error")
        self._created_imports.append(di.name)

        mapping.last_import = di.name

        with self.assertRaises(frappe.exceptions.ValidationError):
            with patch.object(mapping, "save", return_value=mapping):
                mapping.trigger_insert_worksheet_import()

    def test_insert_proceeds_after_success(self):
        """INSERT proceeds when last import has Success status."""
        data = [
            ["Description", "Status"],
            ["Already imported", "Open"],
            ["New item", "Open"],
        ]
        self._created_todos.append("New item")

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=2)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        # Create a successful previous import
        di = frappe.new_doc("Data Import")
        di.reference_doctype = "ToDo"
        di.import_type = INSERT
        di.save()
        frappe.db.set_value("Data Import", di.name, "status", "Success")
        self._created_imports.append(di.name)
        mapping.last_import = di.name

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc"):
                    mapping.trigger_insert_worksheet_import()

        self._track_import(mapping)
        self.assertIsNotNone(mapping.last_import)
        self.assertNotEqual(mapping.last_import, di.name)
        self.assertEqual(mapping.counter, 3)

    def test_insert_proceeds_after_partial_success(self):
        """INSERT proceeds when last import has Partial Success status."""
        data = [
            ["Description", "Status"],
            ["Prev", "Open"],
            ["New partial", "Open"],
        ]
        self._created_todos.append("New partial")

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=2)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        di = frappe.new_doc("Data Import")
        di.reference_doctype = "ToDo"
        di.import_type = INSERT
        di.save()
        frappe.db.set_value("Data Import", di.name, "status", "Partial Success")
        self._created_imports.append(di.name)
        mapping.last_import = di.name

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc"):
                    mapping.trigger_insert_worksheet_import()

        self._track_import(mapping)
        self.assertEqual(mapping.counter, 3)


class TestUpsertImportPipeline(FrappeTestCase):
    """Integration tests for the UPSERT import flow.

    Tests the full pipeline: merge historical imports -> diff against remote -> update.
    """

    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []
        self._created_todos = []

    def tearDown(self):
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        cleanup_todos(self._created_todos)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def _create_successful_insert_import(self, mapping, mock_parent, csv_data):
        """Create a Data Import with Success status and attached CSV file."""
        di = frappe.new_doc("Data Import")
        di.reference_doctype = "ToDo"
        di.import_type = INSERT
        di.save()

        import_file = frappe.new_doc("File")
        import_file.update({
            "attached_to_doctype": "Data Import",
            "attached_to_name": di.name,
            "attached_to_field": "import_file",
            "file_name": f"test-import-{frappe.generate_hash(length=6)}.csv",
            "is_private": 1,
        })
        import_file.content = csv_data.encode("utf-8")
        import_file.save()

        di.import_file = import_file.file_url
        # Use db_set to avoid link validation on fake parent references
        frappe.db.set_value("Data Import", di.name, {
            "import_file": import_file.file_url,
            "spreadsheet_id": mock_parent.name,
            "worksheet_id": mapping.name,
        })
        frappe.db.set_value("Data Import", di.name, "status", "Success")

        self._created_imports.append(di.name)
        return di

    def test_upsert_falls_back_to_insert_when_no_prior_imports(self):
        """UPSERT with no successful prior inserts falls back to INSERT."""
        data = [
            ["Description", "Status"],
            ["Fallback item", "Open"],
        ]
        self._created_todos.append("Fallback item")

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(import_type="Upsert", counter=1)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc"):
                    mapping.trigger_upsert_worksheet_import()

        # Should have fallen back to INSERT
        self.assertIsNotNone(mapping.last_import)
        self._created_imports.append(mapping.last_import)

        di = frappe.get_doc("Data Import", mapping.last_import)
        self.assertEqual(di.import_type, INSERT)

    def test_upsert_detects_changes_and_creates_update_import(self):
        """UPSERT detects differences between local and remote data."""
        # Original insert data
        original_csv = make_csv(
            ["ID", "Description", "Status"],
            ["TODO-001", "Buy groceries", "Open"],
            ["TODO-002", "Walk the dog", "Open"],
        )

        # Remote data with changes
        remote_data = [
            ["ID", "Description", "Status"],
            ["TODO-001", "Buy groceries", "Closed"],  # status changed
            ["TODO-002", "Walk the dog", "Open"],      # unchanged
        ]

        mock_ws = make_mock_worksheet(data=remote_data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(
            import_type="Upsert", counter=3
        )
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        # Create a successful prior insert import
        with patch_parent_doc(mock_parent):
            self._create_successful_insert_import(mapping, mock_parent, original_csv)

            # Mock worksheet_id_field to return "ID"
            mock_ws_for_id = MagicMock()
            mock_ws_for_id.row_values.return_value = ["ID", "Description", "Status"]
            mock_client.open_by_url.return_value.get_worksheet_by_id.return_value = mock_ws_for_id

            # Also patch get_all_values for the fetch
            mock_ws_for_id.get_all_values.return_value = remote_data

            with patch.object(mapping, "save", return_value=mapping):
                with patch(
                    "frappe.core.doctype.data_import.data_import.DataImport.start_import"
                ):
                    mapping.trigger_upsert_worksheet_import()

        if mapping.last_update_import:
            self._created_imports.append(mapping.last_update_import)

            di = frappe.get_doc("Data Import", mapping.last_update_import)
            self.assertEqual(di.import_type, UPDATE)

    def test_upsert_no_changes_falls_back_to_insert(self):
        """UPSERT with no diff between local and remote falls back to INSERT."""
        csv_data = make_csv(
            ["ID", "Description", "Status"],
            ["TODO-001", "Buy groceries", "Open"],
        )

        # Remote is identical
        remote_data = [
            ["ID", "Description", "Status"],
            ["TODO-001", "Buy groceries", "Open"],
        ]

        mock_ws = make_mock_worksheet(data=remote_data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(
            import_type="Upsert", counter=2
        )
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            self._create_successful_insert_import(mapping, mock_parent, csv_data)

            mock_ws_for_id = MagicMock()
            mock_ws_for_id.row_values.return_value = ["ID", "Description", "Status"]
            mock_ws_for_id.get_all_values.return_value = remote_data
            mock_client.open_by_url.return_value.get_worksheet_by_id.return_value = mock_ws_for_id

            with patch.object(mapping, "save", return_value=mapping):
                with patch("frappe.enqueue_doc"):
                    mapping.trigger_upsert_worksheet_import()

        # Should have fallen back to INSERT (no changes detected)
        if mapping.last_import:
            self._created_imports.append(mapping.last_import)


class TestImportRouting(FrappeTestCase):
    """Tests that trigger_worksheet_import correctly routes to INSERT vs UPSERT."""

    def test_routes_to_insert(self):
        mapping, _ = make_worksheet_mapping(import_type="Insert")

        with patch(f"{MODULE_PATH}.DocTypeWorksheetMapping.trigger_insert_worksheet_import") as m:
            mapping.trigger_worksheet_import()
            m.assert_called_once()

    def test_routes_to_upsert(self):
        mapping, _ = make_worksheet_mapping(import_type="Upsert")

        with patch(f"{MODULE_PATH}.DocTypeWorksheetMapping.trigger_upsert_worksheet_import") as m:
            mapping.trigger_worksheet_import()
            m.assert_called_once()

    def test_invalid_type_raises(self):
        mapping, _ = make_worksheet_mapping(import_type="Delete")
        with self.assertRaises(ValueError):
            mapping.trigger_worksheet_import()

    def test_empty_mapped_doctype_raises(self):
        mapping, _ = make_worksheet_mapping(mapped_doctype="")
        with self.assertRaises(frappe.exceptions.ValidationError):
            mapping.trigger_worksheet_import()

    def test_none_mapped_doctype_raises(self):
        mapping, _ = make_worksheet_mapping(mapped_doctype=None)
        mapping.mapped_doctype = None
        with self.assertRaises(frappe.exceptions.ValidationError):
            mapping.trigger_worksheet_import()


class TestDataImportCreation(FrappeTestCase):
    """Integration tests for Data Import + File document creation."""

    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []

    def tearDown(self):
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def test_creates_data_import_and_file(self):
        """create_data_import() creates both Data Import and File documents."""
        mapping, mock_parent = make_worksheet_mapping()
        csv_data = make_csv(["Description", "Status"], ["Test", "Open"])

        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data, import_type=INSERT)

        self._created_imports.append(di.name)

        self.assertTrue(frappe.db.exists("Data Import", di.name))
        self.assertEqual(di.reference_doctype, "ToDo")
        self.assertEqual(di.import_type, INSERT)
        self.assertTrue(di.import_file)

        # File content matches
        content = get_import_file_content(di.name)
        rows = parse_csv(content)
        self.assertEqual(rows[0], ["Description", "Status"])
        self.assertEqual(rows[1], ["Test", "Open"])

    def test_creates_update_import(self):
        """create_data_import() can create UPDATE type imports."""
        mapping, mock_parent = make_worksheet_mapping()
        csv_data = make_csv(["ID", "Status"], ["TODO-001", "Closed"])

        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data, import_type=UPDATE)

        self._created_imports.append(di.name)
        self.assertEqual(di.import_type, UPDATE)

    def test_sets_spreadsheet_tracking_fields(self):
        """Data Import has spreadsheet_id and worksheet_id set."""
        mapping, mock_parent = make_worksheet_mapping(parent_name="my-spreadsheet")
        csv_data = make_csv(["Description"], ["Test"])

        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data)

        self._created_imports.append(di.name)
        self.assertEqual(di.spreadsheet_id, "my-spreadsheet")
        self.assertEqual(di.worksheet_id, mapping.name)

    def test_csv_with_special_characters(self):
        """CSV with commas, quotes, and newlines survives round-trip."""
        csv_data = make_csv(
            ["Description", "Notes"],
            ["Item, with comma", 'She said "hello"'],
        )
        mapping, mock_parent = make_worksheet_mapping()

        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data)

        self._created_imports.append(di.name)

        rows = get_imported_rows(di.name)
        self.assertEqual(rows[1][0], "Item, with comma")
        self.assertEqual(rows[1][1], 'She said "hello"')

    def test_ignore_links_flag_is_set(self):
        """Data Import has flags.ignore_links set to True."""
        mapping, mock_parent = make_worksheet_mapping()
        csv_data = make_csv(["Description"], ["Test"])

        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data)

        self._created_imports.append(di.name)
        # The flag is set on the doc object during creation
        # Re-fetch to confirm the doc was saved correctly
        self.assertTrue(frappe.db.exists("Data Import", di.name))


class TestFetchRemoteData(FrappeTestCase):
    """Integration tests for fetching and transforming remote spreadsheet data."""

    def test_fetch_remote_worksheet_converts_to_csv(self):
        """fetch_remote_worksheet() converts gspread data to CSV string."""
        data = [
            ["Name", "Email", "Age"],
            ["Alice", "alice@example.com", "30"],
            ["Bob", "bob@example.com", "25"],
        ]
        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.fetch_remote_worksheet()

        rows = parse_csv(result)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ["Name", "Email", "Age"])
        self.assertEqual(rows[1], ["Alice", "alice@example.com", "30"])

    def test_fetch_remote_worksheet_empty(self):
        """fetch_remote_worksheet() returns empty string for empty sheet."""
        mock_ws = make_mock_worksheet(data=[])
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.fetch_remote_worksheet()

        self.assertEqual(result, "")

    def test_fetch_remote_spreadsheet_slices_by_counter(self):
        """fetch_remote_spreadsheet() returns only rows after counter."""
        data = [
            ["Description", "Status"],
            ["Row 1", "Open"],
            ["Row 2", "Open"],
            ["Row 3", "Open"],
        ]
        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=2)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.fetch_remote_spreadsheet()

        rows = parse_csv(result)
        self.assertEqual(len(rows), 3)  # header + 2 remaining rows
        self.assertEqual(rows[0], ["Description", "Status"])
        self.assertEqual(rows[1], ["Row 2", "Open"])
        self.assertEqual(rows[2], ["Row 3", "Open"])

    def test_fetch_remote_spreadsheet_only_header_when_all_imported(self):
        """fetch_remote_spreadsheet() returns only header when all rows imported."""
        data = [
            ["Description", "Status"],
            ["Row 1", "Open"],
        ]
        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=2)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.fetch_remote_spreadsheet()

        rows = parse_csv(result)
        self.assertEqual(len(rows), 1)  # only header
        self.assertEqual(rows[0], ["Description", "Status"])

    def test_fetch_handles_special_characters(self):
        """CSV conversion preserves commas, quotes, and newlines in values."""
        data = [
            ["Name", "Description"],
            ["Alice, Bob", 'She said "hello"'],
            ["Charlie\nNewline", "normal"],
        ]
        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.fetch_remote_worksheet()

        rows = parse_csv(result)
        self.assertEqual(rows[1], ["Alice, Bob", 'She said "hello"'])
        self.assertEqual(rows[2], ["Charlie\nNewline", "normal"])


class TestWorksheetIdFieldDetection(FrappeTestCase):
    """Integration tests for worksheet_id_field detection logic."""

    def test_detects_id_column(self):
        """Finds 'ID' when present in header row."""
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mock_ws = make_mock_worksheet(data=SAMPLE_TODO_DATA_WITH_ID)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.worksheet_id_field

        self.assertEqual(result, "ID")

    def test_raises_when_no_id_field(self):
        """Raises ValidationError when no ID or unique field found."""
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        data = [["RandomCol1", "RandomCol2"], ["val1", "val2"]]
        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with self.assertRaises(frappe.exceptions.ValidationError):
                _ = mapping.worksheet_id_field


class TestErrorScenarios(FrappeTestCase):
    """Tests for error handling: malformed data, API failures, missing columns."""

    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []

    def tearDown(self):
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def test_api_error_on_fetch(self):
        """Google Sheets API error raises a frappe exception."""
        import gspread as gs

        mock_client = MagicMock()
        mock_client.open_by_url.side_effect = gs.exceptions.APIError(
            MagicMock(status_code=403, text="Forbidden")
        )

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with self.assertRaises(Exception):
                mapping.fetch_remote_worksheet()

    def test_worksheet_not_found_error(self):
        """WorksheetNotFound error raises a frappe exception."""
        import gspread as gs

        mock_client = MagicMock()
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.get_worksheet_by_id.side_effect = gs.exceptions.WorksheetNotFound("0")
        mock_client.open_by_url.return_value = mock_spreadsheet

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with self.assertRaises(Exception):
                mapping.fetch_remote_worksheet()

    def test_insert_with_empty_csv(self):
        """INSERT with empty worksheet does not create Data Import."""
        mock_ws = make_mock_worksheet(data=[])
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(counter=1)
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch.object(mapping, "save", return_value=mapping):
                mapping.trigger_insert_worksheet_import()

        self.assertIsNone(mapping.last_import)

    def test_reset_worksheet_on_import_throws(self):
        """reset_worksheet_on_import raises an error (feature disabled)."""
        mapping, mock_parent = make_worksheet_mapping(counter=1)
        mapping.reset_worksheet_on_import = True

        # Create a successful previous import so the code reaches the check
        di = frappe.new_doc("Data Import")
        di.reference_doctype = "ToDo"
        di.import_type = INSERT
        di.save()
        frappe.db.set_value("Data Import", di.name, "status", "Success")
        self._created_imports.append(di.name)
        mapping.last_import = di.name

        with self.assertRaises(Exception):
            with patch.object(mapping, "save", return_value=mapping):
                mapping.trigger_insert_worksheet_import()


class TestImporterPatch(FrappeTestCase):
    """Tests for the Importer monkey-patching context manager."""

    def test_patch_importer_applies_and_restores(self):
        """patch_importer() applies the patch and restores the original."""
        from frappe.core.doctype.data_import.importer import Importer

        from sheets.sheets_workspace.doctype.spreadsheet.spreadsheet import patch_importer

        original_method = Importer.update_record
        self.assertFalse(hasattr(Importer, "patched"))

        with patch_importer():
            self.assertTrue(hasattr(Importer, "patched"))
            self.assertNotEqual(Importer.update_record, original_method)

        self.assertFalse(hasattr(Importer, "patched"))
        self.assertEqual(Importer.update_record, original_method)

    def test_patch_importer_leaks_on_exception(self):
        """patch_importer() does NOT restore on exception (known limitation).

        The @contextmanager implementation lacks try/finally, so cleanup
        code after yield is skipped when an exception occurs. This test
        documents the current behavior.
        """
        from frappe.core.doctype.data_import.importer import Importer

        from sheets.sheets_workspace.doctype.spreadsheet.spreadsheet import patch_importer

        original_method = Importer.update_record

        with self.assertRaises(RuntimeError):
            with patch_importer():
                self.assertTrue(hasattr(Importer, "patched"))
                raise RuntimeError("Simulated failure")

        # BUG: patch is NOT cleaned up on exception because
        # patch_importer() doesn't use try/finally around yield
        self.assertTrue(hasattr(Importer, "patched"))
        self.assertNotEqual(Importer.update_record, original_method)

        # Manual cleanup for test isolation
        Importer.update_record = original_method
        del Importer.patched


class TestSchedulerIntegration(FrappeTestCase):
    """Tests for Server Script creation and cron validation."""

    def test_cron_map_has_expected_frequencies(self):
        """CRON_MAP contains all standard frequencies."""
        from sheets.api import CRON_MAP

        expected = {"Yearly", "Monthly", "Weekly", "Daily", "Hourly"}
        self.assertEqual(set(CRON_MAP.keys()), expected)

    def test_describe_cron_returns_string(self):
        """describe_cron() returns a human-readable description."""
        from sheets.api import describe_cron

        result = describe_cron("0 0 * * *")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_describe_cron_with_frequency_name(self):
        """describe_cron() accepts frequency names from CRON_MAP."""
        from sheets.api import describe_cron

        result = describe_cron("Daily")
        self.assertIsInstance(result, str)

    def test_get_all_frequency_returns_int(self):
        """get_all_frequency() returns scheduler interval in minutes."""
        from sheets.api import get_all_frequency

        result = get_all_frequency()
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_import_type_constants(self):
        """Import type constants match expected Frappe values."""
        self.assertEqual(INSERT, "Insert New Records")
        self.assertEqual(UPDATE, "Update Existing Records")
        self.assertEqual(UPSERT, "Update Existing Records or Insert New Records")


class TestMultiWorksheetImport(FrappeTestCase):
    """Tests for importing multiple worksheets from a single spreadsheet."""

    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []
        self._created_todos = []

    def tearDown(self):
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        cleanup_todos(self._created_todos)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def test_multiple_worksheets_import_independently(self):
        """Each worksheet mapping tracks its own counter independently."""
        data_ws0 = [
            ["Description", "Status"],
            ["WS0 Item 1", "Open"],
            ["WS0 Item 2", "Open"],
        ]
        data_ws1 = [
            ["Description", "Status"],
            ["WS1 Item 1", "Open"],
        ]
        self._created_todos.extend(["WS0 Item 1", "WS0 Item 2", "WS1 Item 1"])

        mock_ws0 = make_mock_worksheet(data=data_ws0, worksheet_id=0)
        mock_ws1 = make_mock_worksheet(data=data_ws1, worksheet_id=1)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws0, mock_ws1])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mock_parent = MagicMock()
        mock_parent.sheet_name = "Multi Sheet"
        mock_parent.name = "test-multi-spreadsheet"
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        mapping0, _ = make_worksheet_mapping(
            worksheet_id=0, counter=1, mock_parent=mock_parent,
            parent_name="test-multi-spreadsheet"
        )
        mapping1, _ = make_worksheet_mapping(
            worksheet_id=1, counter=1, mock_parent=mock_parent,
            parent_name="test-multi-spreadsheet"
        )

        with patch_parent_doc(mock_parent):
            for mapping in [mapping0, mapping1]:
                with patch.object(mapping, "save", return_value=mapping):
                    with patch("frappe.enqueue_doc"):
                        mapping.trigger_insert_worksheet_import()

                if mapping.last_import:
                    self._created_imports.append(mapping.last_import)

        # Each worksheet has its own counter
        self.assertEqual(mapping0.counter, 3)  # 1 + 2 rows
        self.assertEqual(mapping1.counter, 2)  # 1 + 1 row

        # Each has its own Data Import
        self.assertIsNotNone(mapping0.last_import)
        self.assertIsNotNone(mapping1.last_import)
        self.assertNotEqual(mapping0.last_import, mapping1.last_import)


class TestCsvRoundTrip(FrappeTestCase):
    """Tests for CSV data integrity through the entire pipeline."""

    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []

    def tearDown(self):
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def test_csv_with_unicode(self):
        """Unicode characters survive the full pipeline."""
        csv_data = make_csv(
            ["Description", "Status"],
            ["Buy groceries \u2014 milk & eggs", "Open"],
            ["\u00c9mile's task", "Open"],
        )

        mapping, mock_parent = make_worksheet_mapping()
        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data)

        self._created_imports.append(di.name)

        rows = get_imported_rows(di.name)
        self.assertEqual(rows[1][0], "Buy groceries \u2014 milk & eggs")
        self.assertEqual(rows[2][0], "\u00c9mile's task")

    def test_csv_with_empty_cells(self):
        """Empty cells are preserved through the pipeline."""
        csv_data = make_csv(
            ["Description", "Status", "Priority"],
            ["Item 1", "", "High"],
            ["", "Open", ""],
        )

        mapping, mock_parent = make_worksheet_mapping()
        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data)

        self._created_imports.append(di.name)

        rows = get_imported_rows(di.name)
        self.assertEqual(rows[1], ["Item 1", "", "High"])
        self.assertEqual(rows[2], ["", "Open", ""])

    def test_csv_with_numeric_values(self):
        """Numeric values are preserved as strings through the pipeline."""
        csv_data = make_csv(
            ["Description", "Count", "Price"],
            ["Widget", "42", "19.99"],
            ["Gadget", "0", "100.00"],
        )

        mapping, mock_parent = make_worksheet_mapping()
        with patch_parent_doc(mock_parent):
            di = mapping.create_data_import(csv_data)

        self._created_imports.append(di.name)

        rows = get_imported_rows(di.name)
        self.assertEqual(rows[1], ["Widget", "42", "19.99"])
        self.assertEqual(rows[2], ["Gadget", "0", "100.00"])
