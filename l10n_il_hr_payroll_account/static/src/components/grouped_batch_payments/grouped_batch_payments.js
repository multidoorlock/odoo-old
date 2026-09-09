/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { View } from "@web/views/view";
import { Component } from "@odoo/owl";

export class GroupedBatchPayments extends Component {
    static template = "l10n_il_hr_payroll_account.GroupedBatchPayments";
    static components = { View };
    static props = { ...standardFieldProps };

    setup() {
        this.actionService = useService("action");
    }

    get viewProps() {
        const batchId = this.props.record.resId;
        return {
            resModel: "account.payment",
            type: "list",
            viewId: this.props.record.data.il_grouped_payment_view_id,
            domain: batchId ? [["batch_payment_id", "=", batchId]] : [["id", "=", 0]],
            groupBy: ["il_batch_group", "il_employee_id"],
            orderBy: [
                { name: "il_employee_id", asc: true },
                { name: "il_payment_cycle_type_id", asc: true },
                { name: "date", asc: true },
                { name: "id", asc: true },
            ],
            context: {
                create: false,
                delete: false,
                form_view_initial_mode: "edit",
            },
            display: { controlPanel: false },
            allowSelectors: false,
            selectRecord: (resId, options = {}) => this.openPayment(resId, options),
        };
    }

    openPayment(resId, { newWindow } = {}) {
        return this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "account.payment",
                res_id: resId,
                views: [[false, "form"]],
                context: { form_view_initial_mode: "edit" },
            },
            { newWindow }
        );
    }
}

registry.category("fields").add("il_grouped_batch_payments", {
    component: GroupedBatchPayments,
    supportedTypes: ["many2many"],
});
