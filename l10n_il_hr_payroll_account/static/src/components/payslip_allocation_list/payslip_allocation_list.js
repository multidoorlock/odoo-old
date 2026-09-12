/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

export class PayslipAllocationListController extends ListController {
    static template = "l10n_il_hr_payroll_account.PayslipAllocationListView";

    async openRecord(record, options) {
        if (!(await this.model.root.leaveEditMode())) {
            return;
        }
        if (this.env.inDialog) {
            // Native action-list navigation is disabled inside an action
            // dialog. Open the native form on top, keeping this selection
            // session and its proposed amounts in the underlying popup.
            const formView = this.env.config.views.find((view) => view[1] === "form");
            return this.dialogService.add(FormViewDialog, {
                resModel: record.resModel,
                resId: record.resId,
                viewId: formView?.[0] || false,
                context: record.context,
                readonly: true,
                preventCreate: true,
                preventEdit: true,
                canExpand: false,
            });
        }
        return super.openRecord(record, options);
    }
}

export class PayslipAllocationListRenderer extends ListRenderer {
    get canSelectRecord() {
        // A checkbox click is also a way to finish the current amount edit.
        // The handlers below wait for Odoo's validation/save before selecting.
        return !this.props.list.model.useSampleModel;
    }

    async toggleRecordSelection(record, event) {
        if (await this.props.list.leaveEditMode()) {
            return super.toggleRecordSelection(record, event);
        }
    }

    async toggleSelection() {
        if (await this.props.list.leaveEditMode()) {
            return super.toggleSelection();
        }
    }
}

registry.category("views").add("il_payslip_allocation_autosave_list", {
    ...listView,
    Controller: PayslipAllocationListController,
    Renderer: PayslipAllocationListRenderer,
});
