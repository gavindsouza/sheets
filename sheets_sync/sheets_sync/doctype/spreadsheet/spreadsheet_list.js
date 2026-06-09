frappe.listview_settings["SpreadSheet"] = {
    onload: function (list_view) {
        list_view.page.add_menu_item("SpreadSheet Settings", () => {
            frappe.set_route("Form", "SpreadSheet Settings");
        });
    },
};
