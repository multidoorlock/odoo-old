/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { MonetaryField, monetaryField } from "@web/views/fields/monetary/monetary_field";

/** Save through Odoo's normal input hook when the amount loses focus or tabs. */
export class PayslipAutosaveMonetaryField extends MonetaryField {
    get inputOptions() {
        return { ...super.inputOptions, shouldSave: () => true };
    }
}

/** Native monetary input with an optimistic concurrency token for this row. */
export class PayslipLinkAmountField extends PayslipAutosaveMonetaryField {
    setup() {
        super.setup();
        this.editSnapshot = null;
        this.snapshotUpdatePending = false;
        useEffect(() => {
            this.resetCleanSnapshot();
        }, () => [this.props.record.dirty, this.props.record.data.il_payslip_link_snapshot]);
    }

    resetCleanSnapshot() {
        // Record.update is queued by the relational model's mutex. While it
        // waits, the row may still be clean, even though typing has started.
        if (!this.props.record.dirty && !this.snapshotUpdatePending) {
            this.editSnapshot = null;
        }
    }

    async onInput(event) {
        super.onInput(event);
        const record = this.props.record;
        this.resetCleanSnapshot();
        // Capture before any onchange or save can refresh the displayed row.
        // Record.update uses Odoo's mutex: this token update precedes the
        // native monetary input's amount update on change/tab/row save.
        if (this.editSnapshot === null) {
            this.editSnapshot = record.data.il_payslip_link_snapshot;
            this.snapshotUpdatePending = true;
            try {
                await record.update({ il_payslip_link_write_token: this.editSnapshot });
            } finally {
                this.snapshotUpdatePending = false;
            }
        }
    }
}

registry.category("fields").add("il_payslip_link_amount", {
    ...monetaryField,
    component: PayslipLinkAmountField,
});

registry.category("fields").add("il_payslip_candidate_amount", {
    ...monetaryField,
    component: PayslipAutosaveMonetaryField,
});
