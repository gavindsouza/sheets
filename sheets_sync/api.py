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
