# Copyright (c) 2023, Gavin D'souza and contributors
# For license information, please see license.txt

import time
from csv import reader as csv_reader
from csv import writer as csv_writer
from difflib import SequenceMatcher
from functools import cached_property
from io import StringIO
from typing import TYPE_CHECKING

import frappe
from frappe.core.doctype.data_import.importer import get_autoname_field
from frappe.model.document import Document
from frappe.utils import get_link_to_form

from sheets.constants import INSERT, UPDATE, UPSERT

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3

if TYPE_CHECKING:
    from frappe.core.doctype.data_import.data_import import DataImport

ACCEPTABLE_IMPORT_STATUSES = ("Success", "Partial Success")


class DocTypeWorksheetMapping(Document):
    def trigger_worksheet_import(self):
        if not self.mapped_doctype:
            frappe.throw("Mapped DocType is required to trigger import.")

        import_type = self.get_import_type()
        if import_type == UPSERT:
            return self.trigger_upsert_worksheet_import()
        elif import_type == INSERT:
            return self.trigger_insert_worksheet_import()
        else:
            raise ValueError(f"Invalid import type: {self.import_type}")

    def fetch_past_successful_imports(self, import_type: str):
        return frappe.get_all(
            "Data Import",
            filters={
                "spreadsheet_id": self.parent_doc.name,
                "worksheet_id": self.name,
                "import_type": import_type,
                "status": ("in", ["Success", "Partial Success"]),
            },
            fields=["name", "import_file"],
            order_by="creation",
        )

    def trigger_upsert_worksheet_import(self):
        successful_insert_imports = self.fetch_past_successful_imports(import_type=INSERT)

        if not successful_insert_imports:
            frappe.msgprint(
                "No successful inserts found to continue UPSERT. Falling back to INSERT instead.",
                alert=True,
                indicator="orange",
            )
            return self.trigger_insert_worksheet_import()

        successful_update_imports = self.fetch_past_successful_imports(import_type=UPDATE)
        update_csv_geneator = (
            frappe.get_doc(doctype="File", file_url=x.import_file, file_name="").get_content()
            for x in successful_update_imports
        )

        insert_csv_generator = (
            frappe.get_doc(doctype="File", file_url=x.import_file, file_name="").get_content()
            for x in successful_insert_imports
        )

        # 1. generate csv file with all the inserted data imported
        data_imported_csv_file = []
        for csv_file in insert_csv_generator:  # order of imports (first to last)
            rows = list(csv_reader(StringIO(csv_file)))
            if not data_imported_csv_file:
                data_imported_csv_file = rows
            else:
                data_imported_csv_file.extend(rows[1:])  # skip header

        if not data_imported_csv_file:
            frappe.msgprint(
                "No imported data found to compare for UPSERT.",
                alert=True,
                indicator="orange",
            )
            return self.trigger_insert_worksheet_import()

        data_imported_csv_file_header = data_imported_csv_file[0]

        id_field = self.worksheet_id_field
        if id_field not in data_imported_csv_file_header:
            frappe.throw(
                f"ID field '{id_field}' not found in imported data columns: "
                f"{', '.join(data_imported_csv_file_header)}"
            )

        id_field_imported_index = data_imported_csv_file_header.index(id_field)

        # 2. apply updates captured over the csv file
        for csv_file in update_csv_geneator:
            update_csv_reader = csv_reader(StringIO(csv_file))

            header_row = next(update_csv_reader)
            id_field_index = header_row.index(self.worksheet_id_field)

            for update_row in update_csv_reader:
                for idx, data_row in enumerate(data_imported_csv_file):
                    if update_row[id_field_index] == data_row[id_field_imported_index]:
                        data_imported_csv_file[idx] = update_row
                        continue

        # convert list of lists back to CSV lines using proper csv module
        csv_buffer = StringIO()
        csv_writer(csv_buffer).writerows(data_imported_csv_file)
        data_imported_csv = csv_buffer.getvalue().splitlines()

        # 3. compare generated csv with remote csv to calculate updates
        equivalent_remote_csv = self.fetch_remote_worksheet().splitlines()[: self.counter]

        diff_opcodes = SequenceMatcher(
            None, data_imported_csv, equivalent_remote_csv
        ).get_grouped_opcodes(0)
        diff_slices = [y[3:5] for y in [x[1] for x in diff_opcodes]]

        available_data_updates = data_imported_csv[:1] + [
            item
            for sublist in [equivalent_remote_csv[slice(*x)] for x in diff_slices]
            for item in sublist
        ]

        if len(available_data_updates) > 1:
            di = self.create_data_import("\n".join(available_data_updates), import_type=UPDATE)
            di.start_import()
            self.last_update_import = di.name
            self.save()
        else:
            frappe.msgprint(
                "No updates found to continue UPSERT. Falling back to INSERT instead.",
                alert=True,
                indicator="orange",
            )
            return self.trigger_insert_worksheet_import()

    def trigger_insert_worksheet_import(self):
        if self.last_import:
            last_data_import_status = frappe.db.get_value(
                "Data Import", self.last_import, "status"
            )

            if last_data_import_status not in ACCEPTABLE_IMPORT_STATUSES:
                frappe.throw(
                    f"Skipping import as last import has status '{last_data_import_status}'. "
                    f"Fix issues in {get_link_to_form('Data Import', self.last_import, 'the last import')} and try again. "
                    f"Acceptable statues are: {', '.join(ACCEPTABLE_IMPORT_STATUSES)}",
                )

            if self.reset_worksheet_on_import:
                # spreadsheet = self.get_sheet_client().open_by_url(self.sheet_url)
                # worksheet = spreadsheet.get_worksheet_by_id(worksheet.worksheet_id)
                # worksheet.delete_rows(2, worksheet.counter - 1)
                # worksheet.counter = 0
                frappe.throw(
                    "Enabling this feature would delete all imported data from the worksheet."
                    "Contact Sheets Support if you need to enable this feature."
                )

        data = self.fetch_remote_spreadsheet()

        # length includes header row
        if (counter := len(data.splitlines())) > 1:
            di = self.create_data_import(data)
            frappe.enqueue_doc(
                di.doctype, di.name, method="start_import", enqueue_after_commit=True
            )
            self.last_import = di.name
            self.counter = (self.counter or 1) + (counter - 1)  # subtract header row
        else:
            frappe.msgprint("No data found to import.", alert=True, indicator="orange")

        return self.save()

    def get_import_type(self):
        match self.import_type:
            case "Insert":
                return INSERT
            case "Upsert":
                return UPSERT
            case _:
                raise ValueError(f"Invalid import type: {self.import_type}")

    def generate_import_file_name(self):
        return f"{self.parent_doc.sheet_name}-worksheet-{self.worksheet_id}-{frappe.generate_hash(length=6)}.csv"

    def create_data_import(self, data: str, import_type=INSERT) -> "DataImport":
        data_import = frappe.new_doc("Data Import")
        data_import.update(
            {
                "reference_doctype": self.mapped_doctype,
                "import_type": import_type,
                "mute_emails": self.mute_emails,
                "submit_after_import": self.submit_after_import,
            }
        )
        data_import.save()

        import_file = frappe.new_doc("File")
        import_file.update(
            {
                "attached_to_doctype": data_import.doctype,
                "attached_to_name": data_import.name,
                "attached_to_field": "import_file",
                "file_name": self.generate_import_file_name(),
                "is_private": 1,
            }
        )
        import_file.content = data.encode("utf-8")
        import_file.save()

        data_import.spreadsheet_id = self.parent_doc.name
        data_import.worksheet_id = self.name
        data_import.import_file = import_file.file_url
        data_import.flags.ignore_links = True

        return data_import.save()

    def fetch_remote_worksheet(self):
        import gspread as gs

        for attempt in range(1 + MAX_RETRIES):
            try:
                remote_spreadsheet = self.parent_doc.get_sheet_client().open_by_url(
                    self.parent_doc.sheet_url
                )
                remote_worksheet = remote_spreadsheet.get_worksheet_by_id(self.worksheet_id)
                break
            except gs.exceptions.APIError as e:
                status_code = getattr(e.response, "status_code", None)
                if status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                    time.sleep(2**attempt)
                    continue
                frappe.throw(
                    f"Failed to fetch worksheet {self.worksheet_id} from remote spreadsheet: {e}",
                    title="Google Sheets API Error",
                )
            except gs.exceptions.WorksheetNotFound:
                frappe.throw(
                    f"Worksheet with ID {self.worksheet_id} not found in the spreadsheet.",
                    title="Worksheet Not Found",
                )

        values = remote_worksheet.get_all_values()
        if not values:
            return ""

        buffer = StringIO()
        csv_writer(buffer).writerows(values)
        return buffer.getvalue()

    def fetch_remote_spreadsheet(self) -> str:
        full_sheet_content = self.fetch_remote_worksheet()
        counter = 0 if self.reset_worksheet_on_import else self.counter

        if counter:
            full_sheet_lines = full_sheet_content.splitlines()
            return "\n".join(full_sheet_lines[:1] + full_sheet_lines[counter:])
        return full_sheet_content

    @cached_property
    def worksheet_id_field(self) -> str:
        worksheet_gdoc = (
            self.parent_doc.get_sheet_client()
            .open_by_url(self.parent_doc.sheet_url)
            .get_worksheet_by_id(self.worksheet_id)
        )
        header_row = worksheet_gdoc.row_values(1)

        if "ID" in header_row:
            return "ID"

        autoname_field = get_autoname_field(self.mapped_doctype)
        if autoname_field and autoname_field.label in header_row:
            return autoname_field.label

        dt = frappe.get_meta(self.mapped_doctype)
        unique_fields = [df.label for df in dt.fields if df.unique]

        for field in unique_fields:
            if field in header_row:
                return field

        # Note: Should we provide a `self.id_field` field to allow users to specify the ID field?
        frappe.throw(f"Could not find ID or Unique field in {self.doctype}")
