# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-04-01

First stable release.

### Added

- **Google Sheets integration** via `gspread` 6.x with Service Account authentication
- **SpreadSheet** DocType for managing Google Sheets connections with URL-based configuration
- **SpreadSheet Settings** DocType for secure storage of Google Service Account credentials
- **DocType Worksheet Mapping** for mapping individual worksheets to target Frappe DocTypes
- **Scheduled imports** with configurable frequency (Hourly, Daily, Weekly, Monthly, Yearly, Custom cron)
- **Insert mode** for appending new records from sheet data
- **Upsert mode** for updating existing records while inserting new ones, using diff-based change detection
- **Incremental sync** — tracks row counter per worksheet to only fetch new data on subsequent imports
- **Auto-detection** of worksheets and GID-based worksheet targeting from sheet URLs
- **Custom fields** on Data Import (`spreadsheet_id`, `worksheet_id`) for full audit trail
- **Credential protection** via `has_permission` hook preventing unauthorized access to service account files
- **Patched Data Import update logic** supporting unique field lookups and insert-on-missing for upsert operations
- **Cron description** API for human-readable schedule display
- **Frappe v15 and v16** compatibility
- **CI pipeline** testing against Frappe v15, v16, and develop branches

[1.0.0]: https://github.com/gavindsouza/sheets/releases/tag/v1.0.0
