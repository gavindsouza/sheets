# Copyright (c) 2025, Gavin D'souza and Contributors
# See license.txt

"""TDD tests for Feature #4: Error Handling, Retry Logic, and Failure Recovery.

Tests written FIRST (red), then implementation to make them pass (green).
"""

import time
from unittest.mock import MagicMock, PropertyMock, call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from sheets.constants import INSERT
from sheets.tests.test_helpers import (
    cleanup_data_import,
    ensure_allow_import,
    make_csv,
    make_mock_gspread_client,
    make_mock_spreadsheet,
    make_mock_worksheet,
    make_worksheet_mapping,
    patch_parent_doc,
    restore_allow_import,
)


class TestApiRetry(FrappeTestCase):
    """Tests for automatic retry on Google Sheets API errors."""

    def test_retries_on_429_rate_limit(self):
        """API call retries on 429 (rate limit) error."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        api_error = gs.exceptions.APIError(mock_response)

        # First call raises 429, second succeeds
        mock_ws = make_mock_worksheet()
        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = [api_error, mock_ws]

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch("time.sleep"):  # Don't actually sleep in tests
                result = mapping.fetch_remote_worksheet()

        self.assertTrue(len(result) > 0)
        self.assertEqual(mock_ss.get_worksheet_by_id.call_count, 2)

    def test_retries_on_500_server_error(self):
        """API call retries on 500 (server error)."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ws = make_mock_worksheet()
        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = [api_error, mock_ws]

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch("time.sleep"):
                result = mapping.fetch_remote_worksheet()

        self.assertTrue(len(result) > 0)

    def test_retries_on_503_service_unavailable(self):
        """API call retries on 503 (service unavailable)."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ws = make_mock_worksheet()
        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = [api_error, mock_ws]

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch("time.sleep"):
                result = mapping.fetch_remote_worksheet()

        self.assertTrue(len(result) > 0)

    def test_does_not_retry_on_403_forbidden(self):
        """API call does NOT retry on 403 (permission error)."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = api_error

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with self.assertRaises(Exception):
                mapping.fetch_remote_worksheet()

        # Should only try once (no retry)
        self.assertEqual(mock_ss.get_worksheet_by_id.call_count, 1)

    def test_does_not_retry_on_404_not_found(self):
        """API call does NOT retry on 404."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = api_error

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with self.assertRaises(Exception):
                mapping.fetch_remote_worksheet()

        self.assertEqual(mock_ss.get_worksheet_by_id.call_count, 1)

    def test_gives_up_after_max_retries(self):
        """API call raises after max retries (3) are exhausted."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = api_error  # Always fails

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch("time.sleep"):
                with self.assertRaises(Exception):
                    mapping.fetch_remote_worksheet()

        # 1 initial + 3 retries = 4 total attempts
        self.assertEqual(mock_ss.get_worksheet_by_id.call_count, 4)

    def test_uses_exponential_backoff(self):
        """Retries use exponential backoff delays (1s, 2s, 4s)."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.side_effect = api_error

        mock_client = MagicMock()
        mock_client.open_by_url.return_value = mock_ss

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch("time.sleep") as mock_sleep:
                with self.assertRaises(Exception):
                    mapping.fetch_remote_worksheet()

        # Should sleep with exponential backoff: 1, 2, 4
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertEqual(sleep_calls, [1, 2, 4])

    def test_retries_open_by_url_on_rate_limit(self):
        """Retries when open_by_url itself raises a rate limit error."""
        import gspread as gs

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        api_error = gs.exceptions.APIError(mock_response)

        mock_ws = make_mock_worksheet()
        mock_ss = MagicMock()
        mock_ss.get_worksheet_by_id.return_value = mock_ws

        mock_client = MagicMock()
        mock_client.open_by_url.side_effect = [api_error, mock_ss]

        mapping, mock_parent = make_worksheet_mapping()
        mock_parent.get_sheet_client.return_value = mock_client
        mock_parent.sheet_url = "https://docs.google.com/spreadsheets/d/test123"

        with patch_parent_doc(mock_parent):
            with patch("time.sleep"):
                result = mapping.fetch_remote_worksheet()

        self.assertTrue(len(result) > 0)
        self.assertEqual(mock_client.open_by_url.call_count, 2)


class TestPatchImporterSafety(FrappeTestCase):
    """Tests for patch_importer() using try/finally for safe cleanup."""

    def test_patch_importer_restores_on_exception(self):
        """patch_importer() restores original method even on exception."""
        from frappe.core.doctype.data_import.importer import Importer

        from sheets.sheets_workspace.doctype.spreadsheet.spreadsheet import patch_importer

        original_method = Importer.update_record

        with self.assertRaises(RuntimeError):
            with patch_importer():
                self.assertTrue(hasattr(Importer, "patched"))
                raise RuntimeError("Simulated failure")

        # After the fix, cleanup should happen even on exception
        self.assertFalse(hasattr(Importer, "patched"))
        self.assertEqual(Importer.update_record, original_method)
