# Copyright (c) 2023, Gavin D'souza and Contributors
# See license.txt

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        time.sleep(10)
        return patch, hasattr(Importer, "patched")


class TestSpreadSheet(FrappeTestCase):
    def test_importer_monkey_patches(self):
        # Tested with gunicorn workers = 2, 10 & 17 - lgtm
        API_PATH = f"{get_site_url(frappe.local.site)}/api/method/{test_api.__module__}.{test_api.__qualname__}"
        patched, not_patched = {"patch": True}, {"patch": False}
        ARGS = [patched, not_patched, not_patched] * 3

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(get, API_PATH, params=arg) for arg in ARGS]
            for future in as_completed(futures):
                res = future.result().json()["message"]
                self.assertEqual(res[0], res[1])
