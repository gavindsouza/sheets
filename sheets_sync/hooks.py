from . import __version__ as app_version  # noqa

app_name = "sheets_sync"
app_title = "Sheets Sync"
app_publisher = "Gavin D'souza"
app_description = "Effortless synchronization between your online SpreadSheet Apps & ERPNext"
app_email = "gavin18d@gmail.com"
app_license = "GPLv3"

after_install = "sheets_sync.install.after_install"

has_permission = {
    "File": "sheets_sync.overrides.has_permission",
}

doc_events = {}
