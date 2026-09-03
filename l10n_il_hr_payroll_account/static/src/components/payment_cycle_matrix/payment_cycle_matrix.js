/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class PaymentCycleMatrix extends Component {
    static template = "l10n_il_hr_payroll_account.PaymentCycleMatrix";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState(JSON.parse(JSON.stringify(
            this.props.record.data[this.props.name] || { types: [], employees: [] }
        )));
    }

    async changeAmount(employee, amountData, event) {
        const amount = Number(event.target.value || 0);
        amountData.amount = amount;
        await this.orm.call("il.payment.cycle.wizard", "update_matrix_value", [
            [this.props.record.resId], employee.id, amountData.type_id, amount, false,
        ]);
    }

    async changeBank(employee, event) {
        const bankId = Number(event.target.value || 0) || false;
        employee.bank_id = bankId;
        await this.orm.call("il.payment.cycle.wizard", "update_matrix_value", [
            [this.props.record.resId], employee.id, false, false, bankId,
        ]);
    }
}

registry.category("fields").add("il_payment_cycle_matrix", {
    component: PaymentCycleMatrix,
    supportedTypes: ["json"],
});
