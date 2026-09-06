# Copyright (c) 2023, Gavin D'souza and Contributors
# See license.txt

import os

import frappe
from frappe.core.doctype.data_import.importer import Importer
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_site_url
from requests import get

from sheets_sync.sheets_sync.doctype.spreadsheet.spreadsheet import patch_importer


def whitelist_for_ci(fn):
    if os.environ.get("CI"):
        return frappe.whitelist(allow_guest=True)(fn)
    return fn


@whitelist_for_ci
def test_api(patch: bool = True):
    if not patch:
        return patch, hasattr(Importer, "patched")
    with patch_importer():
        return patch, hasattr(Importer, "patched")


class TestSpreadSheet(FrappeTestCase):
    def test_importer_patch_is_scoped(self):
        official = Importer.update_record
        self.assertFalse(hasattr(Importer, "patched"))

        with patch_importer():
            self.assertTrue(hasattr(Importer, "patched"))
            self.assertIsNot(Importer.update_record, official)

        self.assertFalse(hasattr(Importer, "patched"))
        self.assertIs(Importer.update_record, official)

    def test_importer_patch_http(self):
        API_PATH = f"{get_site_url(frappe.local.site)}/api/method/{test_api.__module__}.{test_api.__qualname__}"
        response = get(API_PATH, params={"patch": True}).json()["message"]
        self.assertEqual(str(response[0]), str(response[1]))
