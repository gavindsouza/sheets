<div align="center">

# Sheets

**Google Sheets connector for Frappe / ERPNext**

Sync data from Google Sheets directly into your Frappe DocTypes — automatically, on a schedule, with zero code.

[![CI](https://github.com/gavindsouza/sheets/actions/workflows/ci.yml/badge.svg)](https://github.com/gavindsouza/sheets/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Frappe](https://img.shields.io/badge/frappe-v15%20|%20v16-blue.svg)](https://frappeframework.com)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/gavindsouza/sheets)](https://github.com/gavindsouza/sheets/releases)

</div>

---

## Key Features

- **Automated imports** — Schedule recurring imports with built-in cron support (hourly, daily, weekly, or custom cron expressions)
- **Worksheet-to-DocType mapping** — Map individual worksheets to any Frappe DocType with fine-grained control
- **Insert & Upsert modes** — Insert new records or intelligently update existing records while inserting new ones
- **Incremental sync** — Tracks the last imported row to only fetch new data on subsequent runs
- **Built on Frappe Data Import** — Leverages Frappe's native Data Import engine for reliable, auditable imports
- **Credential security** — Service account credentials are stored as private files with enforced permission checks

## How It Works

```
Google Sheets  →  Sheets App  →  Data Import  →  Your DocType
    (API)        (Scheduler)     (Frappe Core)    (Records)
```

1. Configure a Google Service Account and upload credentials
2. Create a **SpreadSheet** document, paste the sheet URL
3. Map worksheets to target DocTypes
4. Set an import frequency — Sheets handles the rest

Each import fetches only new rows (since the last sync), generates a CSV, creates a Frappe Data Import record, and enqueues the import job. Full audit trail via Data Import logs.

## Installation

```bash
bench get-app https://github.com/gavindsouza/sheets.git
bench --site your-site install-app sheets
```

## Configuration

### 1. Create a Google Service Account

Follow the [gspread guide for Service Accounts](https://docs.gspread.org/en/latest/oauth2.html#for-bots-using-service-account):

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** and download the JSON credentials file
4. Share your Google Sheet with the service account email

### 2. Upload Credentials

Navigate to **SpreadSheet Settings** in Frappe and upload the service account JSON file.

### 3. Create a SpreadSheet Document

1. Go to **SpreadSheet** > **New**
2. Paste the Google Sheets URL
3. The app auto-detects available worksheets
4. For each worksheet, set:
   - **Mapped DocType** — the target DocType for imported records
   - **Import Type** — Insert (new records only) or Upsert (update existing + insert new)
   - **Mute Emails** / **Submit After Import** — optional flags
5. Set the **Import Frequency** (Hourly, Daily, Weekly, Monthly, Yearly, or a custom cron expression)
6. Save — the app validates sheet access and creates a scheduled Server Script

### 4. Trigger Imports

Imports run automatically per your schedule. You can also trigger an import manually from the SpreadSheet document using the **Trigger Import** button.

## DocTypes

| DocType | Purpose |
|---|---|
| **SpreadSheet** | Core document — links a Google Sheet URL to import settings and schedules |
| **SpreadSheet Settings** | Stores Google Service Account credentials |
| **DocType Worksheet Mapping** | Child table — maps a worksheet to a target DocType with import configuration |

## Supported Versions

| Component | Version |
|---|---|
| Frappe | v15, v16 |
| Python | 3.10+ |
| gspread | 6.x |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Write tests for new functionality
4. Submit a pull request

```bash
# Run tests locally
bench --site your-site run-tests --app sheets
```

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

Copyright &copy; 2023, [Gavin D'souza](https://github.com/gavindsouza)
