/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { MonetaryField, monetaryField } from "@web/views/fields/monetary/monetary_field";

/** Native monetary input with an optimistic concurrency token for this row. */
export class PayslipLinkAmountField extends MonetaryField {
    setup() {
        super.setup();
        this.editSnapshot = null;
        useEffect(() => {
            if (!this.props.record.dirty) {
                this.editSnapshot = null;
            }
        }, () => [this.props.record.dirty, this.props.record.data.il_payslip_link_snapshot]);
    }

    async onInput(event) {
        super.onInput(event);
        const record = this.props.record;
        // Capture before any onchange or save can refresh the displayed row.
        // Record.update uses Odoo's mutex: this token update precedes the
        // native monetary input's amount update on change/tab/row save.
        if (this.editSnapshot === null) {
            this.editSnapshot = record.data.il_payslip_link_snapshot;
            await record.update({ il_payslip_link_write_token: this.editSnapshot });
        }
    }
}

registry.category("fields").add("il_payslip_link_amount", {
    ...monetaryField,
    component: PayslipLinkAmountField,
});
