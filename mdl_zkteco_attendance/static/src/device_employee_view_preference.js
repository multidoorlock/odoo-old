/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { actionService } from "@web/webclient/actions/action_service";

const ACTION_XML_ID = "mdl_zkteco_attendance.action_device_employee";
const STORAGE_KEY = "mdlAttendanceDeviceEmployeeViewType";
const SAVED_VIEW_TYPES = ["list", "kanban"];

patch(actionService, {
    start(env) {
        const service = super.start(env);
        const switchView = service.switchView;

        service.switchView = async (viewType, props = {}, { newWindow } = {}) => {
            if (
                !env.isSmall &&
                service.currentController?.action?.xml_id === ACTION_XML_ID &&
                SAVED_VIEW_TYPES.includes(viewType)
            ) {
                browser.localStorage.setItem(STORAGE_KEY, viewType);
            }
            return switchView(viewType, props, { newWindow });
        };
        return service;
    },
});

async function deviceEmployeeActionPreference(env, action, options) {
    const savedViewType = browser.localStorage.getItem(STORAGE_KEY);
    const viewType = SAVED_VIEW_TYPES.includes(savedViewType) ? savedViewType : undefined;
    const nextAction = await env.services.action.loadAction(ACTION_XML_ID);

    return env.services.action.doAction(
        {
            ...nextAction,
            context: action.context,
            domain: action.domain,
        },
        { ...options, viewType }
    );
}

registry
    .category("actions")
    .add("mdl_zkteco_attendance.device_employee_preference", deviceEmployeeActionPreference);
