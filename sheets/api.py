import frappe
from cron_descriptor import get_description

CRON_MAP = {
    "Yearly": "0 0 1 1 *",
    "Monthly": "0 0 1 * *",
    "Weekly": "0 0 * * 0",
    "Daily": "0 0 * * *",
    "Hourly": "0 * * * *",
}


@frappe.whitelist(methods=["GET"])
def get_all_frequency():
    return (frappe.conf.scheduler_interval or 240) // 60


@frappe.whitelist(methods=["GET"])
def describe_cron(cron: str):
    if cron in CRON_MAP:
        cron = CRON_MAP[cron]
    return get_description(cron)


@frappe.whitelist()
def export_to_sheets(doc=None, method=None):
    """Generic export hook called on_update of any document or via scheduler."""
    if frappe.flags.in_patch or frappe.flags.in_install or frappe.flags.in_setup:
        return

    if doc:
        # 1. Update/Append specific document
        mappings = frappe.get_all("DocType Worksheet Mapping", filters={"mapped_doctype": doc.doctype})
        for m in mappings:
            mapping_doc = frappe.get_doc("DocType Worksheet Mapping", m.name)
            try:
                mapping_doc.trigger_export(doc)
            except Exception:
                frappe.log_error(title="Sheets Export Error", message=frappe.get_traceback())
    else:
        # 2. Scheduler call: Sync all mapped doctypes (all records)
        mappings = frappe.get_all("DocType Worksheet Mapping", fields=["name", "mapped_doctype"])
        for m in mappings:
            mapping_doc = frappe.get_doc("DocType Worksheet Mapping", m.name)
            docs = frappe.get_all(m.mapped_doctype)
            for d in docs:
                full_doc = frappe.get_doc(m.mapped_doctype, d.name)
                try:
                    mapping_doc.trigger_export(full_doc)
                except Exception:
                    continue


@frappe.whitelist()
def export_customers_to_sheets(doc=None, method=None, sheet_url=None):
    """Legacy wrapper for backward compatibility."""
    if not doc:
        # If called without a doc, sync all customers using the generic scheduler logic
        export_to_sheets(doc=None)
        return

    export_to_sheets(doc=doc)
