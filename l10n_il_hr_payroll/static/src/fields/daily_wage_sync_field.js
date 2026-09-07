/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useRecordObserver } from "@web/model/relational_model/utils";
import {
    monetaryField,
    MonetaryField,
} from "@web/views/fields/monetary/monetary_field";

/**
 * Keep the additional-day rate in step with a day-rate edit in the open form.
 *
 * This intentionally lives in the web client: imports, RPC create/write calls,
 * and other server-side changes must not silently replace a separately agreed
 * additional-day rate. The observer also sees a monthly day rate that changes
 * after an onchange response, even though that field is readonly in the form.
 */
export class DailyWageSyncField extends MonetaryField {
    setup() {
        super.setup();
        this.observedRecord = null;
        this.previousDailyWage = undefined;

        useRecordObserver(async (record) => {
            const dailyWage = record.data.mdl_daily_wage;
            if (record !== this.observedRecord) {
                this.observedRecord = record;
                this.previousDailyWage = dailyWage;
                return;
            }
            if (dailyWage === this.previousDailyWage) {
                return;
            }
            this.previousDailyWage = dailyWage;
            if (record.data.mdl_additional_day_wage !== dailyWage) {
                await record.update({ mdl_additional_day_wage: dailyWage });
            }
        });
    }
}

export const dailyWageSyncField = {
    ...monetaryField,
    component: DailyWageSyncField,
};

registry.category("fields").add("mdl_daily_wage_sync", dailyWageSyncField);
