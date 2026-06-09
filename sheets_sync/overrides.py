import frappe

import sheets_sync


def has_permission(doc, ptype, user):
    if (doc.attached_to_doctype == doc.attached_to_name == sheets_sync.SHEETS_SETTINGS) and (
        doc.attached_to_field == sheets_sync.SHEETS_CREDENTIAL_FIELD
    ):
        raise frappe.PermissionError("Not allowed to access")


def get_initial_docs(self, doc, id_field, unique_field):
    try:
        if unique_field:
            existing_doc = frappe.get_doc(
                self.doctype, {unique_field.fieldname: doc.get(unique_field.fieldname)}
            )
            updated_doc = frappe.get_doc(
                self.doctype, {unique_field.fieldname: doc.get(unique_field.fieldname)}
            )
        else:
            existing_doc = frappe.get_doc(self.doctype, doc.get(id_field.fieldname))
            updated_doc = frappe.get_doc(self.doctype, doc.get(id_field.fieldname))

    except frappe.DoesNotExistError:
        frappe.clear_last_message()
        existing_doc = frappe.new_doc(self.doctype)
        updated_doc = frappe.new_doc(self.doctype)

    return existing_doc, updated_doc


def update_record_patch(self, doc):
    from frappe import _
    from frappe.core.doctype.data_import.importer import get_diff, get_id_field

    id_field = get_id_field(self.doctype)
    unique_field = None

    # override_1: If no id field is set, try to find a unique field
    if not doc.get(id_field.fieldname):
        unique_fields = [df for df in frappe.get_meta(self.doctype).fields if df.unique]
        for field in unique_fields:
            if doc.get(field.fieldname):
                unique_field = field
                break

    # override_2: Use unique field if id field is not set, insert if existing doc is not found
    existing_doc, updated_doc = get_initial_docs(self, doc, id_field, unique_field)
    updated_doc.update(doc)

    if get_diff(existing_doc, updated_doc):
        # update doc if there are changes
        updated_doc.flags.updater_reference = {
            "doctype": self.data_import.doctype,
            "docname": self.data_import.name,
            "label": _("via Data Import"),
        }
        updated_doc.save()
        return updated_doc

    # override_3: Return existing doc if no changes
    return existing_doc
