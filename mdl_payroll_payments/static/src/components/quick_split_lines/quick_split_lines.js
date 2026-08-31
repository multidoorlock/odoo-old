/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";


export class QuickSplitDialog extends Component {
    static template = "mdl_payroll_payments.QuickSplitDialog";
    static components = { Dialog };
    static props = {
        amount: Number,
        rounding: Number,
        currencyName: String,
        createLines: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ quantity: "", lineAmount: "", error: "" });
    }

    get rounding() {
        return this.props.rounding || 0.01;
    }

    roundCurrency(value) {
        return Math.round((value + Number.EPSILON) / this.rounding) * this.rounding;
    }

    onQuantityInput(event) {
        const quantity = Number.parseInt(event.target.value, 10);
        this.state.quantity = event.target.value;
        this.state.error = "";
        this.state.lineAmount = Number.isInteger(quantity) && quantity > 0
            ? String(this.roundCurrency(this.props.amount / quantity))
            : "";
    }

    onAmountInput(event) {
        const lineAmount = Number(event.target.value);
        this.state.lineAmount = event.target.value;
        this.state.error = "";
        this.state.quantity = "";
        if (!(lineAmount > 0)) {
            return;
        }
        const totalUnits = Math.round(this.props.amount / this.rounding);
        const lineUnits = Math.round(lineAmount / this.rounding);
        const isCurrencyExact = Math.abs(lineAmount - lineUnits * this.rounding) < 1e-9;
        if (isCurrencyExact && lineUnits > 0 && totalUnits % lineUnits === 0) {
            this.state.quantity = String(totalUnits / lineUnits);
        }
    }

    async confirm() {
        const quantity = Number.parseInt(this.state.quantity, 10);
        const lineAmount = Number(this.state.lineAmount);
        const totalUnits = Math.round(this.props.amount / this.rounding);
        const lineUnits = Math.round(lineAmount / this.rounding);
        const isCurrencyExact = Math.abs(lineAmount - lineUnits * this.rounding) < 1e-9;
        if (!Number.isInteger(quantity) || quantity <= 0 || !(lineAmount > 0)) {
            this.state.error = _t("Quantity and amount per line must be greater than zero.");
            return;
        }
        if (!isCurrencyExact || quantity * lineUnits !== totalUnits) {
            this.state.error = _t(
                "The split lines total must equal the payment amount. Make sure quantity multiplied by amount per line equals %s %s.",
                this.props.amount,
                this.props.currencyName
            );
            return;
        }
        await this.props.createLines(quantity, lineUnits * this.rounding);
        this.props.close();
    }
}


export class QuickSplitLinesField extends X2ManyField {
    static template = "mdl_payroll_payments.QuickSplitLinesField";

    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }

    get showQuickCreate() {
        return !this.props.record.resId && this.props.record.data.il_spread_type === "planned";
    }

    openQuickCreate() {
        const currency = this.props.record.data.currency_id;
        this.dialog.add(QuickSplitDialog, {
            amount: this.props.record.data.amount || 0,
            rounding: this.props.record.data.il_currency_rounding || 0.01,
            currencyName: currency?.display_name || currency?.name || "",
            createLines: this.createQuickLines.bind(this),
        });
    }

    async createQuickLines(quantity, amount) {
        const list = this.props.record.data[this.props.name];
        const existingSequences = list.records
            .map((record) => Number(record.data.sequence) || 0);
        let sequence = existingSequences.length ? Math.max(...existingSequences) + 1 : 1;
        for (let index = 0; index < quantity; index++) {
            const record = await list.addNewRecord({
                mode: "edit",
                position: "bottom",
                context: this.props.record.context,
            });
            await record.update({ sequence: sequence++, amount });
        }
    }
}

registry.category("fields").add("il_quick_split_lines", {
    ...x2ManyField,
    component: QuickSplitLinesField,
});
