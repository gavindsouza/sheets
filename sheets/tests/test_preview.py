# Copyright (c) 2025, Gavin D'souza and Contributors
# See license.txt

"""TDD tests for Feature #7: Data Preview Before Import.

Tests written FIRST (red), then implementation to make them pass (green).
"""

from unittest.mock import MagicMock, PropertyMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from sheets.tests.test_helpers import (
    make_mock_gspread_client,
    make_mock_spreadsheet,
    make_mock_worksheet,
    make_worksheet_mapping,
    patch_parent_doc,
)


class TestPreviewData(FrappeTestCase):
    """Tests for the worksheet data preview feature."""

    def test_preview_returns_header_and_sample_rows(self):
        """Preview returns header row + up to 10 data rows."""
        data = [
            ["Name", "Email", "Status"],
        ] + [[f"User {i}", f"user{i}@example.com", "Open"] for i in range(20)]

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.preview_data()

        self.assertIn("header", result)
        self.assertIn("rows", result)
        self.assertEqual(result["header"], ["Name", "Email", "Status"])
        self.assertEqual(len(result["rows"]), 10)  # max 10 rows
        self.assertEqual(result["rows"][0], ["User 0", "user0@example.com", "Open"])
        self.assertEqual(result["total_rows"], 20)

    def test_preview_returns_all_rows_when_fewer_than_10(self):
        """Preview returns all data rows when there are fewer than 10."""
        data = [
            ["Name", "Status"],
            ["Alice", "Open"],
            ["Bob", "Closed"],
        ]

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.preview_data()

        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["total_rows"], 2)

    def test_preview_returns_empty_for_empty_worksheet(self):
        """Preview of empty worksheet returns empty rows."""
        mock_ws = make_mock_worksheet(data=[])
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.preview_data()

        self.assertEqual(result["header"], [])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total_rows"], 0)

    def test_preview_returns_only_header_when_no_data_rows(self):
        """Preview with header-only worksheet returns empty rows."""
        data = [["Name", "Email"]]

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.preview_data()

        self.assertEqual(result["header"], ["Name", "Email"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total_rows"], 0)

    def test_preview_includes_mapped_doctype_fields(self):
        """Preview includes target DocType field info for mapping display."""
        data = [
            ["Description", "Status", "Unknown Column"],
            ["Task 1", "Open", "xyz"],
        ]

        mock_ws = make_mock_worksheet(data=data)
        mock_ss = make_mock_spreadsheet(worksheets=[mock_ws])
        mock_client = make_mock_gspread_client(spreadsheet=mock_ss)

        mapping, mock_parent = make_worksheet_mapping(mapped_doctype="ToDo")
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            result = mapping.preview_data()

        self.assertIn("field_mapping", result)
        # "Description" should map to a field in ToDo
        self.assertIsInstance(result["field_mapping"], dict)
        # Known columns should be marked as mapped
        self.assertIn("Description", result["field_mapping"])

    def test_preview_handles_special_characters(self):
        """Preview correctly handles special characters in values."""
        data = [
            ["Name", "Notes"],
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
            result = mapping.preview_data()

        self.assertEqual(result["rows"][0], ["Alice, Bob", 'She said "hello"'])
        self.assertEqual(result["rows"][1], ["Charlie\nNewline", "normal"])
