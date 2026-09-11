/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { x2ManyCommands } from "@web/core/orm_service";
import { useService } from "@web/core/utils/hooks";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";


export function quickSplitAmounts(remaining, quantity, lineAmount, rounding = 0.01) {
    const totalUnits = Math.round(remaining / rounding);
    const lineUnits = Math.round(lineAmount / rounding);
    if (!Number.isInteger(quantity) || quantity <= 0 || quantity > 1000 ||
        !Number.isFinite(lineAmount) || lineUnits <= 0 || totalUnits <= 0 ||
        Math.abs(lineAmount - lineUnits * rounding) > 1e-9) {
        return null;
    }
    const lastUnits = totalUnits - lineUnits * (quantity - 1);
    if (lastUnits <= 0 || lastUnits > lineUnits + Math.ceil(quantity / 2)) {
        return null;
    }
    return Array.from({ length: quantity }, (_, index) =>
        Number(((index === quantity - 1 ? lastUnits : lineUnits) * rounding).toFixed(12)));
}


export class QuickSplitDialog extends Component {
    static template = "l10n_il_hr_payroll_account.QuickSplitDialog";
    static components = { Dialog };
    static props = {
        amount: Number,
        paymentAmount: Number,
        existingCount: Number,
        existingAmount: Number,
        rounding: Number,
        currencyName: String,
        createLines: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ quantity: "", lineAmount: "", error: "", busy: false });
    }

    get rounding() {
        return this.props.rounding || 0.01;
    }

    roundCurrency(value) {
        return Number((Math.round((value + Number.EPSILON) / this.rounding) * this.rounding).toFixed(12));
    }

    onQuantityInput(event) {
        const quantity = Number(event.target.value);
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
        if (isCurrencyExact && lineUnits > 0 && lineUnits <= totalUnits) {
            this.state.quantity = String(Math.ceil(totalUnits / lineUnits));
        }
    }

    get amounts() {
        return quickSplitAmounts(
            this.props.amount, Number(this.state.quantity),
            Number(this.state.lineAmount), this.rounding);
    }

    get lastAmount() {
        return this.amounts?.at(-1);
    }

    async confirm() {
        if (this.state.busy) {
            return;
        }
        const amounts = this.amounts;
        if (!amounts) {
            this.state.error = _t(
                "Enter a whole number of new lines (1–1000) and a positive amount that fits the unallocated balance of %s %s. The last line includes the remainder.",
                this.props.amount,
                this.props.currencyName
            );
            return;
        }
        this.state.busy = true;
        try {
            await this.props.createLines(amounts);
            this.props.close();
        } catch (error) {
            this.state.error = error.message || _t("The lines could not be added.");
        } finally {
            this.state.busy = false;
        }
    }
}


export class QuickSplitLinesField extends X2ManyField {
    static template = "l10n_il_hr_payroll_account.QuickSplitLinesField";

    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }

    get showQuickCreate() {
        return !this.props.readonly && this.props.record.data.il_spread_type === "planned";
    }

    async openQuickCreate() {
        const list = this.props.record.data[this.props.name];
        if (!(await list.leaveEditMode({ validate: true }))) {
            return;
        }
        // Include saved rows on other pages and all unsaved edits. A displayed
        // page alone is not the full planned amount.
        await list.load({ offset: 0, limit: Math.max(list.count, 1) });
        const currency = this.props.record.data.currency_id;
        const rounding = this.props.record.data.il_currency_rounding || 0.01;
        const paymentAmount = this.props.record.data.amount || 0;
        const existingAmount = list.records.reduce(
            (sum, record) => sum + (Number(record.data.amount) || 0), 0);
        const amount = Math.round((paymentAmount - existingAmount) / rounding) * rounding;
        this.dialog.add(QuickSplitDialog, {
            amount,
            paymentAmount,
            existingCount: list.count,
            existingAmount,
            rounding,
            currencyName: currency?.display_name || currency?.name || "",
            createLines: this.createQuickLines.bind(this),
        });
    }

    async onAdd(params = {}) {
        const result = await super.onAdd(params);
        await this.resequenceClientLines();
        return result;
    }

    async resequenceClientLines() {
        const list = this.props.record.data[this.props.name];
        const commands = list.records.flatMap((record, index) => {
            const sequence = list.offset + index + 1;
            return Number(record.data.sequence) === sequence ? [] : [[
                x2ManyCommands.UPDATE, record.resId || record._virtualId, { sequence },
            ]];
        });
        if (commands.length) {
            await list.applyCommands(commands);
        }
    }

    async createQuickLines(amounts) {
        const list = this.props.record.data[this.props.name];
        const rounding = this.props.record.data.il_currency_rounding || 0.01;
        const existingAmount = list.records.reduce(
            (sum, record) => sum + (Number(record.data.amount) || 0), 0);
        const remainingUnits = Math.round(
            ((this.props.record.data.amount || 0) - existingAmount) / rounding);
        const proposedUnits = amounts.reduce(
            (sum, amount) => sum + Math.round(amount / rounding), 0);
        if (remainingUnits <= 0 || remainingUnits !== proposedUnits ||
            amounts.some((amount) => !Number.isFinite(amount) || amount <= 0)) {
            throw new Error(_t("The unallocated balance changed. Reopen quick creation."));
        }
        const existingSequences = list.records
            .map((record) => Number(record.data.sequence) || 0);
        const firstSequence = existingSequences.length ? Math.max(...existingSequences) + 1 : 1;
        // Native batch commands create every row before one parent onchange;
        // the user never sees rows being inserted and recalculated one by one.
        await list.applyCommands(amounts.map((amount, index) => [
            x2ManyCommands.CREATE, 0, { sequence: firstSequence + index, amount },
        ]));
    }
}

registry.category("fields").add("il_quick_split_lines", {
    ...x2ManyField,
    component: QuickSplitLinesField,
});
