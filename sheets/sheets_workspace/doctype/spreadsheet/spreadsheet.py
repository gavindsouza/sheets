# Copyright (c) 2023, Gavin D'souza and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from typing import TYPE_CHECKING

import frappe
import gspread as gs
from croniter import croniter
from frappe.model.document import Document
from frappe.utils import get_link_to_form

import sheets
from sheets.api import describe_cron, get_all_frequency
from sheets.overrides import update_record_patch

if TYPE_CHECKING:
    from frappe.core.doctype.file import File

    from sheets.sheets_workspace.doctype.doctype_worksheet_mapping.doctype_worksheet_mapping import (
        DocTypeWorksheetMapping,
    )


class SpreadSheet(Document):
    worksheet_ids: "list[DocTypeWorksheetMapping]"
    server_script: str
    frequency_cron: str
    import_frequency: str
    sheet_url: str
    sheet_name: str

    @property
    def frequency_description(self):
        match self.import_frequency:
            case None | "":
                return
            case "Custom":
                return describe_cron(self.frequency_cron)
            case "Frequently":
                return describe_cron(f"0/{get_all_frequency()} * * * *")
            case _:
                return describe_cron(self.import_frequency)

    def get_sheet_client(self):
        if not hasattr(self, "_gc"):
            file: "File" = frappe.get_cached_doc(
                "File",
                {
                    "attached_to_doctype": sheets.SHEETS_SETTINGS,
                    "attached_to_name": sheets.SHEETS_SETTINGS,
                    "attached_to_field": sheets.SHEETS_CREDENTIAL_FIELD,
                },
            )
            self._gc = gs.service_account(file.get_full_path())
        return self._gc

    def validate(self):
        self.validate_base_settings()
        self.validate_sync_settings()
        self.validate_sheet_access()

    def validate_base_settings(self):
        # validate sheet url uniqueness
        if another_exists := frappe.get_all(
            self.doctype,
            filters={"sheet_url": self.sheet_url, "name": ("!=", self.name)},
            limit=1,
            pluck="name",
        ):
            frappe.throw(
                f"Sheet URL must be unique. Another sheet exists with the same URL: {get_link_to_form(self.doctype, another_exists[0])}",
                title="Sheet URL must be unique",
            )

    def validate_sync_settings(self):
        # validate cron pattern
        if self.frequency_cron and self.import_frequency == "Custom":
            croniter(self.frequency_cron)

        # setup server script
        if self.sheet_name and (
            self.has_value_changed("import_frequency") or self.has_value_changed("frequency_cron")
        ):
            script_name = f"SpreadSheet Import - {self.sheet_name}"

            if self.import_frequency == "Custom":
                event_frequency = "Cron"
            elif self.import_frequency == "Frequently":
                event_frequency = "All"
            else:
                event_frequency = self.import_frequency

            if not self.server_script:
                script = frappe.new_doc("Server Script").update(
                    {
                        "__newname": script_name,
                        "script_type": "Scheduler Event",
                        "script": f"frappe.get_doc('SpreadSheet', '{self.name}').trigger_import()",
                        "event_frequency": event_frequency,
                        "cron_format": self.frequency_cron,
                    }
                )

            else:
                script = frappe.get_doc(
                    "Server Script", self.server_script, for_update=True
                ).update(
                    {
                        "event_frequency": event_frequency,
                        "cron_format": self.frequency_cron,
                    }
                )

            script.disabled = not self.import_frequency
            script.save()
            self.server_script = script.name

    def validate_sheet_access(self):
        sheet_client = self.get_sheet_client()

        try:
            sheet = sheet_client.open_by_url(self.sheet_url)
        except gs.exceptions.APIError as e:
            frappe.throw(
                f"Share spreadsheet with the following Service Account Email and try again: <b>{sheet_client.auth.service_account_email}</b>",
                exc=e,
            )
        self._set_sheet_metadata(sheet)

    def _set_sheet_metadata(self, sheet: "gs.Spreadsheet"):
        # set sheet name if not set
        self.sheet_name = self.sheet_name or sheet.title

        # set & validate worksheet ids
        worksheet_ids = [str(w.id) for w in sheet.worksheets()]
        if "gid=" in self.sheet_url:
            self.sheet_url, gid = self.sheet_url.split("gid=", 1)
            if gid not in worksheet_ids:
                frappe.throw(f"Invalid Worksheet ID {gid}")
            if not self.get("worksheet_ids", {"worksheet_id": gid}):
                self.append(
                    "worksheet_ids",
                    {
                        "worksheet_id": gid,
                    },
                )
        elif not self.get("worksheet_ids"):
            self.extend("worksheet_ids", [{"worksheet_id": gid} for gid in worksheet_ids])

        # set default counter for worksheets
        for worksheet in self.worksheet_ids:
            worksheet.counter = worksheet.counter or 1

    @frappe.whitelist()
    def trigger_import(self):
        with patch_importer():
            for worksheet in self.worksheet_ids:
                worksheet.trigger_worksheet_import()
            self.save()
        frappe.msgprint("Import Triggered Successfully", indicator="blue", alert=True)
        return self


@contextmanager
def patch_importer():
    from frappe.core.doctype.data_import.importer import Importer

    _official_method = Importer.update_record
    Importer.update_record = update_record_patch
    Importer.patched = True
    yield
    Importer.update_record = _official_method
    del Importer.patched
