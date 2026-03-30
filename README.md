<div align="center">

# Sheets (Advanced 2-Way Sync)

**Powerful Bi-directional Google Sheets connector for Frappe / ERPNext**

Sync data between Google Sheets and Frappe DocTypes — automatically, in real-time, with child table support.

[![CI](https://github.com/gavindsouza/sheets/actions/workflows/ci.yml/badge.svg)](https://github.com/gavindsouza/sheets/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Frappe](https://img.shields.io/badge/frappe-v15%20|%20v16-blue.svg)](https://frappeframework.com)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

</div>

---

## Key Features

- ** 2-Way Synchronization** — Import data from Sheets to ERPNext AND Export data from ERPNext to Sheets.
- ** Child Table Support** — Automatically flattens child tables (e.g., Sales Invoice Items, Bonded Products) for denormalized Google Sheets reporting.
- ** Real-time Export** — Data is pushed to your Google Sheet instantly whenever a record is saved in ERPNext.
- ** Automated Imports** — Schedule recurring imports with built-in cron support (hourly, daily, etc.).
- ** Zero-Code Dynamic Export** — One-click "Trigger Export" button for manual synchronization of any DocType.
- ** Incremental Sync** — Smart tracking to ensure only new/changed data is synced, preventing duplicates.

## How It Works

### Flow 1: Google Sheets → ERPNext (Import)

```
Google Sheets  →  API Call  →  Data Import Engine  →  ERPNext Records
```

### Flow 2: ERPNext → Google Sheets (Export/Push)

```
ERPNext Save Event  →  Export Engine  →  Gspread API  →  Google Sheets
```

## Installation

```bash
bench get-app https://github.com/gavindsouza/sheets.git
bench --site [your-site] install-app sheets
```

## Configuration

### 1. Google Service Account Setup

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account**, download the JSON credentials.
4. **Important:** Share your Google Sheet with the Service Account email.

### 2. Upload Credentials

Go to **SpreadSheet Settings** in Frappe and upload your JSON credentials file.

### 3. Create a SpreadSheet Mapping

1. Go to **SpreadSheet** > **New**.
2. Paste the URL of your Google Sheet.
3. Map the **Worksheet** to your target **DocType** (e.g., Customer, Sales Invoice).
4. Set the **Import Frequency** for incoming data.

## Using Export / Push-to-Sheet

Once a mapping is saved:

- **Instant Sync:** Editing or creating a record of that DocType will automatically push updates to the connected Google Sheet.
- **Manual Export:** Use the **Trigger Export** button in the SpreadSheet document to push all existing records.
- **Child Tables:** If your DocType has a child table (e.g., Items), the app will automatically create a row for every child record in the sheet.

## Supported DocTypes

- Works with any Standard or Custom DocType.
- Handles standard fields and custom child tables automatically.

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.
