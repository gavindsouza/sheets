import json
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
    @property
    def spreadsheet_doc(self) -> "SpreadSheet":
        from sheets.sheets_workspace.doctype.spreadsheet.spreadsheet import SpreadSheet

        if not hasattr(self, "_spreadsheet_doc_cache") or not self._spreadsheet_doc_cache:
            if not self.parent:
                frappe.throw(f"Parent SpreadSheet is missing for worksheet mapping: {self.name}")
            self._spreadsheet_doc_cache = frappe.get_cached_doc("SpreadSheet", self.parent)
        return self._spreadsheet_doc_cache

    def trigger_worksheet_import(self):
        if not self.mapped_doctype:
            frappe.throw("Mapped DocType is required to trigger import.")

        try:
            import_type = self.get_import_type()
            if import_type == UPSERT:
                res = self.trigger_upsert_worksheet_import()
            elif import_type == INSERT:
                res = self.trigger_insert_worksheet_import()
            else:
                raise ValueError(f"Invalid import type: {self.import_type}")
            
            # Clear error log on success
            if self.sync_error_log:
                self.db_set("sync_error_log", "")
            return res
        except Exception as e:
            self.log_sync_error(str(e))
            raise e

    def log_sync_error(self, message):
        """Feature 3: Log errors to sync_error_log."""
        timestamp = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        error_msg = f"[{timestamp}] {message}\n"
        current_log = self.sync_error_log or ""
        # Keep only the last 5000 chars to avoid blob overflow
        new_log = (error_msg + current_log)[:5000]
        self.db_set("sync_error_log", new_log)

    def check_filters(self, doc):
        """Feature 4: Check if document matches filters."""
        if not self.export_filters:
            return True
        try:
            filters = frappe.parse_json(self.export_filters)
            if not isinstance(filters, dict):
                return True
            for key, val in filters.items():
                if str(doc.get(key)) != str(val):
                    return False
            return True
        except Exception:
            return True

    def format_worksheet(self, worksheet):
        """Feature 5: Bold headers and freeze top row. + Dropdowns."""
        try:
            import re
            from gspread.utils import ValidationConditionType, rowcol_to_a1
            # Bold Header (Row 1)
            worksheet.format("1", {"textFormat": {"bold": True}})
            # Freeze Row 1
            worksheet.freeze(rows=1)

            # Feature: Auto-Dropdowns for Select fields
            header = worksheet.row_values(1)
            dt_meta = frappe.get_meta(self.mapped_doctype)
            field_labels = {df.label: df.fieldname for df in dt_meta.fields}
            # Custom mappings for common fields
            field_labels["Mobile No"] = "mobile_no"
            field_labels["Mobile"] = "mobile_no"
            field_labels["Email Id"] = "email_id"
            field_labels["Email"] = "email_id"
            field_labels["Organization Name"] = "custom_organization_name"

            for idx, col_label in enumerate(header):
                fieldname = field_labels.get(col_label)
                if not fieldname:
                    continue
                
                field = dt_meta.get_field(fieldname)
                options = []
                if field and field.fieldtype == "Select" and field.options:
                    options = [o.strip() for o in field.options.split("\n") if o.strip()]
                elif field and field.fieldtype == "Link" and field.options:
                    # Feature: Also support Link fields (top 100)
                    options = frappe.get_all(field.options, limit=100, pluck="name")

                if options:
                    # Get column range e.g. B2:B1000
                    col_a1 = rowcol_to_a1(1, idx + 1)
                    col_letter = re.sub(r"\d+", "", col_a1)
                    cell_range = f"{col_letter}2:{col_letter}1000"
                    
                    try:
                        worksheet.add_validation(
                            cell_range,
                            ValidationConditionType.one_of_list,
                            options,
                            showCustomUi=True
                        )
                    except Exception:
                        continue
        except Exception as e:
            self.log_sync_error(f"Format error: {str(e)}")

    def trigger_export(self, doc):
        """Generic export logic: Update sheet row if ID exists, else append."""
        import gspread

        # 1. Get Worksheet
        client = self.spreadsheet_doc.get_sheet_client()
        sh = client.open_by_url(self.spreadsheet_doc.sheet_url)
        worksheet = sh.get_worksheet_by_id(self.worksheet_id)

        # 2. Get Header
        header = worksheet.row_values(1)
        if not header:
            return

        # 3. Build Field Mapping (Label -> Fieldname)
        dt_meta = frappe.get_meta(doc.doctype)
        field_labels = {df.label: df.fieldname for df in dt_meta.fields}
        # Add common aliases for robust mapping
        field_labels["ID"] = "name"
        field_labels["Name"] = "name"
        field_labels["Mobile No"] = "mobile_no"
        field_labels["Mobile"] = "mobile_no"
        field_labels["Email Id"] = "email_id"
        field_labels["Email"] = "email_id"
        field_labels["Organization Name"] = "custom_organization_name"

        # 4. Prepare data for the row
        row_data = []
        id_col_idx = -1
        for idx, col in enumerate(header):
            if col == "ID":
                id_col_idx = idx + 1
            
            fieldname = field_labels.get(col)
            if fieldname:
                val = doc.get(fieldname)
                if val is None:
                    row_data.append("")
                else:
                    row_data.append(str(val))
            else:
                row_data.append("")

        # Search & Filter Check
        if not self.check_filters(doc):
            return

        # 5. Search for existing record by ID
        if id_col_idx != -1:
            try:
                cell = worksheet.find(doc.name, in_column=id_col_idx)
                if cell:
                    # Update the found row
                    # gspread update expects a list of lists for a range
                    range_label = f"A{cell.row}"
                    worksheet.update(range_label, [row_data])
                    self.format_worksheet(worksheet)
                    return
            except (gspread.exceptions.CellNotFound, gspread.exceptions.APIError):
                pass

        # 6. Append if not found or no ID column
        worksheet.append_row(row_data)
        self.format_worksheet(worksheet)

    def fetch_past_successful_imports(self, import_type: str):
        return frappe.get_all(
            "Data Import",
            filters={
                "spreadsheet_id": self.spreadsheet_doc.name,
                "worksheet_id": self.name,
                "import_type": import_type,
                "status": ("in", ["Success", "Partial Success"]),
                "import_file": ["not like", "%/"],
            },
            fields=["name", "import_file"],
            order_by="creation",
        )

    def get_file_content(self, file_url):
        if not file_url or file_url.endswith("/"):
            return None
            
        import os
        try:
            file_doc = frappe.get_doc(doctype="File", file_url=file_url, file_name="")
            file_path = file_doc.get_full_path()
            
            if os.path.isdir(file_path):
                return None
                
            content = file_doc.get_content()
            if isinstance(content, bytes):
                return content.decode("utf-8")
            return content
        except Exception:
            return None

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
            self.get_file_content(x.import_file)
            for x in successful_update_imports
            if x.import_file
        )

        insert_csv_generator = (
            self.get_file_content(x.import_file)
            for x in successful_insert_imports
            if x.import_file
        )

        # 1. generate csv file with all the inserted data imported
        data_imported_csv_file = []
        for csv_file in insert_csv_generator:  # order of imports (first to last)
            if not csv_file:
                continue
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
            if not csv_file:
                continue
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
        remote_worksheet_csv = self.fetch_remote_worksheet()
        remote_rows = frappe.utils.csvutils.read_csv_content(remote_worksheet_csv)
        
        # Convert remote_rows (list of lists) to a list of CSV-formatted lines for comparison
        # This ensures that SequenceMatcher works on full rows, handling newlines properly.
        def rows_to_csv_lines(rows):
            buf = StringIO()
            csv_writer(buf).writerows(rows)
            return buf.getvalue().splitlines()

        equivalent_remote_csv = rows_to_csv_lines(remote_rows[: self.counter])

        diff_opcodes = SequenceMatcher(
            None, data_imported_csv, equivalent_remote_csv
        ).get_grouped_opcodes(0)

        available_data_updates = data_imported_csv[:1]
        for group in diff_opcodes:
            for tag, i1, i2, j1, j2 in group:
                if tag != "equal":
                    available_data_updates.extend(equivalent_remote_csv[j1:j2])

        if len(available_data_updates) > 1:
            di = self.create_data_import("\n".join(available_data_updates), import_type=UPDATE)
            di.start_import()
            self.last_update_import = di.name
            self.save()

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
        return f"{self.spreadsheet_doc.sheet_name}-worksheet-{self.worksheet_id}-{frappe.generate_hash(length=6)}.csv"

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

        data_import.spreadsheet_id = self.spreadsheet_doc.name
        data_import.worksheet_id = self.name
        data_import.import_file = import_file.file_url
        data_import.flags.ignore_links = True

        return data_import.save()

    def fetch_remote_worksheet(self):
        import gspread as gs

        for attempt in range(1 + MAX_RETRIES):
            try:
                remote_spreadsheet = self.spreadsheet_doc.get_sheet_client().open_by_url(
                    self.spreadsheet_doc.sheet_url
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

        # Filter out empty rows (where all cells are empty)
        values = [v for v in values if any(v)]

        buffer = StringIO()
        csv_writer(buffer).writerows(values)
        return buffer.getvalue()

    def preview_data(self, max_rows=10) -> dict:
        """Fetch a preview of the worksheet data for mapping verification.

        Returns a dict with:
          - header: list of column names
          - rows: list of data rows (up to max_rows)
          - total_rows: total number of data rows in the worksheet
          - field_mapping: dict mapping column names to matched DocType fields
        """
        import gspread as gs

        try:
            remote_spreadsheet = self.spreadsheet_doc.get_sheet_client().open_by_url(
                self.spreadsheet_doc.sheet_url
            )
            remote_worksheet = remote_spreadsheet.get_worksheet_by_id(self.worksheet_id)
        except (gs.exceptions.APIError, gs.exceptions.WorksheetNotFound):
            return {"header": [], "rows": [], "total_rows": 0, "field_mapping": {}}

        values = remote_worksheet.get_all_values()
        if not values:
            return {"header": [], "rows": [], "total_rows": 0, "field_mapping": {}}

        header = values[0]
        data_rows = values[1:]
        total_rows = len(data_rows)

        field_mapping = {}
        if self.mapped_doctype:
            dt_meta = frappe.get_meta(self.mapped_doctype)
            field_labels = {df.label: df.fieldname for df in dt_meta.fields}
            for col in header:
                if col in field_labels:
                    field_mapping[col] = field_labels[col]
                elif col == "Mobile":
                    field_mapping[col] = "mobile_no"
                elif col == "Email":
                    field_mapping[col] = "email_id"
                elif col == "ID":
                    field_mapping[col] = "name"

        return {
            "header": header,
            "rows": data_rows[:max_rows],
            "total_rows": total_rows,
            "field_mapping": field_mapping,
        }

    def fetch_remote_spreadsheet(self) -> str:
        full_sheet_content = self.fetch_remote_worksheet()
        counter = 0 if self.reset_worksheet_on_import else self.counter

        if counter:
            full_rows = frappe.utils.csvutils.read_csv_content(full_sheet_content)
            # Reconstruct CSV from header + offset onwards
            header = full_rows[:1]
            data_rows = full_rows[counter:]
            
            buffer = StringIO()
            csv_writer(buffer).writerows(header + data_rows)
            return buffer.getvalue()
            
        return full_sheet_content

    @cached_property
    def worksheet_id_field(self) -> str:
        worksheet_gdoc = (
            self.spreadsheet_doc.get_sheet_client()
            .open_by_url(self.spreadsheet_doc.sheet_url)
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
