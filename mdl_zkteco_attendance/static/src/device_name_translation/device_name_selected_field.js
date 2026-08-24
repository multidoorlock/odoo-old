/** @odoo-module **/

import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class DeviceNameSelectedField extends CharField {
    static template = "mdl_zkteco_attendance.DeviceNameSelectedField";
    static components = CharField.components;
}

registry.category("fields").add("mdl_device_name_selected", {
    ...charField,
    component: DeviceNameSelectedField,
});
