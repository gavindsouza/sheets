from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def create_data_import_fields():
    create_custom_field(
        "Data Import",
        {
            "fieldname": "spreadsheet_id",
            "label": "SpreadSheet ID",
            "fieldtype": "Link",
            "options": "SpreadSheet",
            "insert_after": "import_file",
            "read_only": 1,
        },
    )
    create_custom_field(
        "Data Import",
        {
            "fieldname": "worksheet_id",
            "label": "Worksheet ID",
            "fieldtype": "Link",
            "options": "DocType Worksheet Mapping",
            "insert_after": "spreadsheet_id",
            "hidden": 1,
        },
    )


def after_install():
    create_data_import_fields()
