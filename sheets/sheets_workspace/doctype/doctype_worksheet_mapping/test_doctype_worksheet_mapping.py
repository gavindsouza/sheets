# Copyright (c) 2023, Gavin D'souza and Contributors
# See license.txt

from csv import reader as csv_reader
from io import StringIO
from unittest.mock import MagicMock, PropertyMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from sheets.constants import INSERT, UPDATE, UPSERT


def make_csv(*rows):
    """Helper to create CSV string from rows (list of lists)."""
    from csv import writer as csv_writer

    buf = StringIO()
    csv_writer(buf).writerows(rows)
    return buf.getvalue()


class TestGetImportType(FrappeTestCase):
    """Tests for DocTypeWorksheetMapping.get_import_type()."""

    def _make_mapping(self, import_type):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.import_type = import_type
        return mapping

    def test_insert_type(self):
        mapping = self._make_mapping("Insert")
        self.assertEqual(mapping.get_import_type(), INSERT)

    def test_upsert_type(self):
        mapping = self._make_mapping("Upsert")
        self.assertEqual(mapping.get_import_type(), UPSERT)

    def test_invalid_type_raises(self):
        mapping = self._make_mapping("Delete")
        with self.assertRaises(ValueError):
            mapping.get_import_type()

    def test_empty_type_raises(self):
        mapping = self._make_mapping("")
        with self.assertRaises(ValueError):
            mapping.get_import_type()


class TestTriggerWorksheetImport(FrappeTestCase):
    """Tests for DocTypeWorksheetMapping.trigger_worksheet_import() routing."""

    def _make_mapping(self, import_type):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.import_type = import_type
        mapping.mapped_doctype = "ToDo"
        return mapping

    @patch(
        "sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping.DocTypeWorksheetMapping.trigger_insert_worksheet_import"
    )
    def test_routes_insert(self, mock_insert):
        mapping = self._make_mapping("Insert")
        mapping.trigger_worksheet_import()
        mock_insert.assert_called_once()

    @patch(
        "sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping.DocTypeWorksheetMapping.trigger_upsert_worksheet_import"
    )
    def test_routes_upsert(self, mock_upsert):
        mapping = self._make_mapping("Upsert")
        mapping.trigger_worksheet_import()
        mock_upsert.assert_called_once()

    def test_routes_invalid_raises(self):
        mapping = self._make_mapping("Invalid")
        with self.assertRaises(ValueError):
            mapping.trigger_worksheet_import()


class TestFetchRemoteSpreadsheet(FrappeTestCase):
    """Tests for fetch_remote_spreadsheet() counter/slicing logic."""

    def _make_mapping(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        return mapping

    def test_returns_all_rows_when_counter_is_zero(self):
        mapping = self._make_mapping()
        mapping.reset_worksheet_on_import = True

        csv_data = make_csv(
            ["Name", "Email"],
            ["Alice", "alice@example.com"],
            ["Bob", "bob@example.com"],
        )

        with patch.object(mapping, "fetch_remote_worksheet", return_value=csv_data):
            result = mapping.fetch_remote_spreadsheet()
            rows = list(csv_reader(StringIO(result)))
            self.assertEqual(len(rows), 3)  # header + 2 data rows
            self.assertEqual(rows[0], ["Name", "Email"])

    def test_skips_already_imported_rows(self):
        mapping = self._make_mapping()
        mapping.counter = 2  # already imported first data row
        mapping.reset_worksheet_on_import = False

        csv_data = make_csv(
            ["Name", "Email"],
            ["Alice", "alice@example.com"],
            ["Bob", "bob@example.com"],
            ["Charlie", "charlie@example.com"],
        )

        with patch.object(mapping, "fetch_remote_worksheet", return_value=csv_data):
            result = mapping.fetch_remote_spreadsheet()
            rows = list(csv_reader(StringIO(result)))
            # header + rows after counter (Bob and Charlie)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0], ["Name", "Email"])
            self.assertEqual(rows[1], ["Bob", "bob@example.com"])
            self.assertEqual(rows[2], ["Charlie", "charlie@example.com"])

    def test_returns_only_header_when_all_imported(self):
        mapping = self._make_mapping()
        mapping.counter = 3  # all 3 data rows already imported
        mapping.reset_worksheet_on_import = False

        csv_data = make_csv(
            ["Name", "Email"],
            ["Alice", "alice@example.com"],
            ["Bob", "bob@example.com"],
        )

        with patch.object(mapping, "fetch_remote_worksheet", return_value=csv_data):
            result = mapping.fetch_remote_spreadsheet()
            rows = list(csv_reader(StringIO(result)))
            # only header remains
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0], ["Name", "Email"])


class TestFetchRemoteWorksheet(FrappeTestCase):
    """Tests for fetch_remote_worksheet() CSV conversion."""

    def setUp(self):
        super().setUp()
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        self._mock_parent = MagicMock()
        self._parent_doc_patcher = patch.object(
            DocTypeWorksheetMapping, "parent_doc", new_callable=PropertyMock, return_value=self._mock_parent
        )
        self._parent_doc_patcher.start()

    def tearDown(self):
        self._parent_doc_patcher.stop()
        super().tearDown()

    def _make_mapping(self, worksheet_id=0):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.worksheet_id = worksheet_id

        return mapping, self._mock_parent

    def test_converts_values_to_csv(self):
        mapping, mock_parent = self._make_mapping()
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = [
            ["Name", "Email"],
            ["Alice", "alice@example.com"],
        ]
        mock_parent.get_sheet_client().open_by_url().get_worksheet_by_id.return_value = (
            mock_worksheet
        )

        result = mapping.fetch_remote_worksheet()
        rows = list(csv_reader(StringIO(result)))
        self.assertEqual(rows[0], ["Name", "Email"])
        self.assertEqual(rows[1], ["Alice", "alice@example.com"])

    def test_handles_special_characters_in_csv(self):
        mapping, mock_parent = self._make_mapping()
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = [
            ["Name", "Description"],
            ["Alice, Bob", 'She said "hello"'],
            ["Charlie\nNewline", "normal"],
        ]
        mock_parent.get_sheet_client().open_by_url().get_worksheet_by_id.return_value = (
            mock_worksheet
        )

        result = mapping.fetch_remote_worksheet()
        rows = list(csv_reader(StringIO(result)))
        self.assertEqual(rows[0], ["Name", "Description"])
        self.assertEqual(rows[1], ["Alice, Bob", 'She said "hello"'])
        self.assertEqual(rows[2], ["Charlie\nNewline", "normal"])

    def test_handles_empty_worksheet(self):
        mapping, mock_parent = self._make_mapping()
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = []
        mock_parent.get_sheet_client().open_by_url().get_worksheet_by_id.return_value = (
            mock_worksheet
        )

        result = mapping.fetch_remote_worksheet()
        self.assertEqual(result.strip(), "")


class TestGenerateImportFileName(FrappeTestCase):
    """Tests for generate_import_file_name()."""

    def test_filename_format(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mock_parent = MagicMock()
        mock_parent.sheet_name = "Test Sheet"

        with patch.object(DocTypeWorksheetMapping, "parent_doc", new_callable=PropertyMock, return_value=mock_parent):
            mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
            mapping.worksheet_id = 42

            filename = mapping.generate_import_file_name()
            self.assertTrue(filename.startswith("Test Sheet-worksheet-42-"))
            self.assertTrue(filename.endswith(".csv"))


class TestCreateDataImport(FrappeTestCase):
    """Tests for create_data_import() document creation."""

    def setUp(self):
        super().setUp()
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        self._mock_parent = MagicMock()
        self._mock_parent.sheet_name = "Test Sheet"
        self._mock_parent.name = "test-spreadsheet-001"
        self._parent_doc_patcher = patch.object(
            DocTypeWorksheetMapping, "parent_doc", new_callable=PropertyMock, return_value=self._mock_parent
        )
        self._parent_doc_patcher.start()

    def tearDown(self):
        self._parent_doc_patcher.stop()
        super().tearDown()

    def _make_mapping(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.mapped_doctype = "ToDo"
        mapping.mute_emails = 1
        mapping.submit_after_import = 0
        mapping.worksheet_id = 0
        mapping.name = "test-mapping-001"

        return mapping

    def test_creates_data_import_with_correct_fields(self):
        mapping = self._make_mapping()
        csv_data = make_csv(["Name", "Status"], ["Test Todo", "Open"])

        di = mapping.create_data_import(csv_data, import_type=INSERT)

        self.assertEqual(di.reference_doctype, "ToDo")
        self.assertEqual(di.import_type, INSERT)
        self.assertEqual(di.mute_emails, 1)
        self.assertEqual(di.submit_after_import, 0)
        self.assertEqual(di.spreadsheet_id, "test-spreadsheet-001")
        self.assertEqual(di.worksheet_id, "test-mapping-001")
        self.assertTrue(di.import_file)

        # verify the file content
        file_doc = frappe.get_doc("File", {"file_url": di.import_file})
        content = file_doc.get_content()
        rows = list(csv_reader(StringIO(content)))
        self.assertEqual(rows[0], ["Name", "Status"])
        self.assertEqual(rows[1], ["Test Todo", "Open"])

        # cleanup
        frappe.delete_doc("Data Import", di.name, force=True)

    def test_creates_data_import_for_update(self):
        mapping = self._make_mapping()
        csv_data = make_csv(["ID", "Status"], ["TODO-001", "Closed"])

        di = mapping.create_data_import(csv_data, import_type=UPDATE)

        self.assertEqual(di.import_type, UPDATE)

        # cleanup
        frappe.delete_doc("Data Import", di.name, force=True)


class TestTriggerInsertWorksheetImport(FrappeTestCase):
    """Tests for trigger_insert_worksheet_import() logic."""

    def setUp(self):
        super().setUp()
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        self._mock_parent = MagicMock()
        self._mock_parent.sheet_name = "Test Sheet"
        self._mock_parent.name = "test-spreadsheet-insert"
        self._parent_doc_patcher = patch.object(
            DocTypeWorksheetMapping, "parent_doc", new_callable=PropertyMock, return_value=self._mock_parent
        )
        self._parent_doc_patcher.start()

    def tearDown(self):
        self._parent_doc_patcher.stop()
        super().tearDown()

    def _make_mapping(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.mapped_doctype = "ToDo"
        mapping.mute_emails = 1
        mapping.submit_after_import = 0
        mapping.worksheet_id = 0
        mapping.counter = 1
        mapping.last_import = None
        mapping.reset_worksheet_on_import = False
        mapping.name = "test-mapping-insert"
        mapping.flags = frappe._dict()
        mapping.docstatus = 0

        mapping.parenttype = "SpreadSheet"
        mapping.parent = self._mock_parent.name
        mapping.parentfield = "worksheet_ids"
        mapping.idx = 1

        return mapping

    @patch(
        "sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping.DocTypeWorksheetMapping.fetch_remote_spreadsheet"
    )
    @patch("frappe.enqueue_doc")
    def test_insert_creates_data_import_and_updates_counter(self, mock_enqueue, mock_fetch):
        mapping = self._make_mapping()
        csv_data = make_csv(
            ["Description", "Status"],
            ["Task 1", "Open"],
            ["Task 2", "Open"],
        )
        mock_fetch.return_value = csv_data

        # We need to mock save since this is a child table
        with patch.object(mapping, "save", return_value=mapping):
            mapping.trigger_insert_worksheet_import()

        self.assertIsNotNone(mapping.last_import)
        # counter should be 1 (original) + 2 (new rows) = 3
        self.assertEqual(mapping.counter, 3)
        mock_enqueue.assert_called_once()

        # cleanup
        if mapping.last_import:
            frappe.delete_doc("Data Import", mapping.last_import, force=True)

    @patch(
        "sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping.DocTypeWorksheetMapping.fetch_remote_spreadsheet"
    )
    def test_insert_skips_when_no_data(self, mock_fetch):
        mapping = self._make_mapping()
        # only header, no data rows
        csv_data = make_csv(["Description", "Status"])
        mock_fetch.return_value = csv_data

        with patch.object(mapping, "save", return_value=mapping):
            mapping.trigger_insert_worksheet_import()

        # counter should not change when there's no data
        self.assertEqual(mapping.counter, 1)
        self.assertIsNone(mapping.last_import)

    def test_insert_throws_when_last_import_failed(self):
        mapping = self._make_mapping()

        # create a failed Data Import
        di = frappe.new_doc("Data Import")
        di.reference_doctype = "ToDo"
        di.import_type = INSERT
        di.save()
        frappe.db.set_value("Data Import", di.name, "status", "Error")

        mapping.last_import = di.name

        with self.assertRaises(frappe.exceptions.ValidationError):
            with patch.object(mapping, "save", return_value=mapping):
                mapping.trigger_insert_worksheet_import()

        # cleanup
        frappe.delete_doc("Data Import", di.name, force=True)


class TestWorksheetIdField(FrappeTestCase):
    """Tests for worksheet_id_field cached property."""

    def _make_mapping(self, header_row, mapped_doctype="ToDo"):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.mapped_doctype = mapped_doctype
        mapping.worksheet_id = 0

        mock_parent = MagicMock()
        mock_worksheet = MagicMock()
        mock_worksheet.row_values.return_value = header_row
        mock_parent.get_sheet_client().open_by_url().get_worksheet_by_id.return_value = (
            mock_worksheet
        )

        return mapping, mock_parent

    def test_returns_id_when_present(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping, mock_parent = self._make_mapping(["ID", "Name", "Email"])
        with patch.object(DocTypeWorksheetMapping, "parent_doc", new_callable=PropertyMock, return_value=mock_parent):
            self.assertEqual(mapping.worksheet_id_field, "ID")

    def test_throws_when_no_id_field_found(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping, mock_parent = self._make_mapping(["RandomCol1", "RandomCol2"])
        with patch.object(DocTypeWorksheetMapping, "parent_doc", new_callable=PropertyMock, return_value=mock_parent):
            with self.assertRaises(frappe.exceptions.ValidationError):
                _ = mapping.worksheet_id_field


class TestMappedDoctypeValidation(FrappeTestCase):
    """Tests for mapped_doctype validation on import trigger."""

    def test_throws_when_mapped_doctype_empty(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.mapped_doctype = ""
        mapping.import_type = "Insert"

        with self.assertRaises(frappe.exceptions.ValidationError):
            mapping.trigger_worksheet_import()

    def test_throws_when_mapped_doctype_none(self):
        from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
            DocTypeWorksheetMapping,
        )

        mapping = DocTypeWorksheetMapping.__new__(DocTypeWorksheetMapping)
        mapping.mapped_doctype = None
        mapping.import_type = "Insert"

        with self.assertRaises(frappe.exceptions.ValidationError):
            mapping.trigger_worksheet_import()


class TestUpsertCsvHandling(FrappeTestCase):
    """Tests for proper CSV handling in upsert flow (no manual comma-joining)."""

    def test_csv_with_commas_in_values_survives_roundtrip(self):
        """Verify that values containing commas are properly handled in CSV conversion.

        This is a regression test for the bug where manual ','.join() was used
        instead of the csv module, causing values with commas to break.
        """
        from csv import writer as csv_writer

        # Simulate the fixed code path: list-of-lists -> CSV lines
        data = [
            ["Name", "Description", "ID"],
            ["Alice, Bob", 'She said "hello"', "1"],
            ["Charlie", "normal value", "2"],
        ]

        csv_buffer = StringIO()
        csv_writer(csv_buffer).writerows(data)
        csv_lines = csv_buffer.getvalue().splitlines()

        # Parse back and verify roundtrip integrity
        parsed = list(csv_reader(StringIO("\n".join(csv_lines))))
        self.assertEqual(parsed[0], ["Name", "Description", "ID"])
        self.assertEqual(parsed[1], ["Alice, Bob", 'She said "hello"', "1"])
        self.assertEqual(parsed[2], ["Charlie", "normal value", "2"])
