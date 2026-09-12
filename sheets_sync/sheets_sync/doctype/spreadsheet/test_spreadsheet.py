# Copyright (c) 2023, Gavin D'souza and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from sheets_sync.constants import UPDATE
from sheets_sync.overrides import SheetsImporter
from sheets_sync.tests.test_helpers import (
    cleanup_data_import,
    cleanup_todos,
    ensure_allow_import,
    make_csv,
    restore_allow_import,
)


def _create_data_import_with_csv(csv_data, reference_doctype="ToDo"):
    """Create a persisted Data Import UPDATE with an attached CSV file."""
    di = frappe.new_doc("Data Import")
    di.reference_doctype = reference_doctype
    di.import_type = UPDATE
    di.save()

    import_file = frappe.new_doc("File")
    import_file.update(
        {
            "attached_to_doctype": "Data Import",
            "attached_to_name": di.name,
            "attached_to_field": "import_file",
            "file_name": f"test-import-{frappe.generate_hash(length=6)}.csv",
            "is_private": 1,
        }
    )
    import_file.content = csv_data.encode("utf-8")
    import_file.save()

    di.import_file = import_file.file_url
    di.flags.ignore_links = True
    di.save()
    return di


class TestSheetsImporter(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self._todo_allow_import = ensure_allow_import("ToDo")
        self._created_imports = []
        self._created_todos = []

    def tearDown(self):
        self._set_unique_description(0)
        for di_name in self._created_imports:
            cleanup_data_import(di_name)
        cleanup_todos(self._created_todos)
        restore_allow_import("ToDo", self._todo_allow_import)
        super().tearDown()

    def _set_unique_description(self, unique):
        df = frappe.get_doc("DocField", {"parent": "ToDo", "fieldname": "description"})
        if df.unique != unique:
            df.unique = unique
            df.save()
            frappe.clear_cache(doctype="ToDo")

    def _run_update_import(self, csv_data):
        di = _create_data_import_with_csv(csv_data)
        self._created_imports.append(di.name)
        SheetsImporter("ToDo", data_import=di).import_data()
        return di

    def test_update_by_id(self):
        """SheetsImporter matches existing docs by the ID field and updates them."""
        marker = frappe.generate_hash(length=8)
        todo = frappe.new_doc("ToDo")
        todo.description = f"Import target {marker}"
        todo.status = "Open"
        todo.insert(ignore_permissions=True)
        frappe.db.commit()
        self._created_todos.append(todo.description)

        self._run_update_import(
            make_csv(
                ["ID", "Description", "Status"],
                [todo.name, todo.description, "Closed"],
            )
        )

        self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Closed")
        self.assertEqual(frappe.db.count("ToDo", {"description": todo.description}), 1)

    def test_update_by_unique_field(self):
        """Without an ID, SheetsImporter matches existing docs by the first unique field."""
        marker = frappe.generate_hash(length=8)
        description = f"Unique fallback match {marker}"
        self._set_unique_description(1)
        todo = frappe.new_doc("ToDo")
        todo.description = description
        todo.status = "Open"
        todo.insert(ignore_permissions=True)
        frappe.db.commit()
        self._created_todos.append(description)

        self._run_update_import(
            make_csv(
                ["Description", "Status"],
                [description, "Closed"],
            )
        )

        self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Closed")
        self.assertEqual(frappe.db.count("ToDo", {"description": description}), 1)

    def test_insert_when_no_match(self):
        """SheetsImporter creates a new doc when no existing doc matches the row."""
        description = f"New from upsert {frappe.generate_hash(length=8)}"
        self._run_update_import(
            make_csv(
                ["Description", "Status"],
                [description, "Open"],
            )
        )
        self._created_todos.append(description)

        self.assertEqual(frappe.db.count("ToDo", {"description": description}), 1)

    def test_no_changes_returns_existing(self):
        """SheetsImporter does not touch a doc whose row is unchanged."""
        marker = frappe.generate_hash(length=8)
        todo = frappe.new_doc("ToDo")
        todo.description = f"Already correct {marker}"
        todo.status = "Open"
        todo.insert(ignore_permissions=True)
        frappe.db.commit()
        self._created_todos.append(todo.description)

        self._run_update_import(
            make_csv(
                ["ID", "Description", "Status"],
                [todo.name, todo.description, "Open"],
            )
        )

        self.assertEqual(frappe.db.count("ToDo", {"description": todo.description}), 1)
        self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")
