from . import __version__ as app_version  # noqa

app_name = "sheets"
app_title = "Sheets"
app_publisher = "Gavin D'souza"
app_description = "Effortless synchronization between your online SpreadSheet Apps & ERPNext"
app_email = "gavin18d@gmail.com"
app_license = "GPLv3"

after_install = "sheets.install.after_install"

has_permission = {
    "File": "sheets.overrides.has_permission",
}

doc_events = {
    "*": {
        "on_update": "sheets.api.export_to_sheets"
    }
}

scheduler_events = {
    "hourly": [
        "sheets.api.export_to_sheets"
    ]
}
