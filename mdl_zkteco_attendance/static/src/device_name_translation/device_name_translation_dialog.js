/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { TranslationDialog } from "@web/views/fields/translation_dialog";
import { onWillStart, useState } from "@odoo/owl";

const DEVICE_CARD_MODEL = "mdl.attendance.device.employee";
const DEVICE_NAME_FIELD = "device_name";

patch(TranslationDialog.prototype, {
    setup() {
        super.setup(...arguments);
        this.mdlDeviceNameLanguage = useState({ code: null });

        onWillStart(async () => {
            if (this.isMdlDeviceNameTranslation) {
                this.mdlDeviceNameLanguage.code = await this.orm.call(
                    this.props.resModel,
                    "get_device_name_language_code",
                    [[this.props.resId]]
                );
            }
        });
    },

    get isMdlDeviceNameTranslation() {
        return (
            this.props.resModel === DEVICE_CARD_MODEL &&
            this.props.fieldName === DEVICE_NAME_FIELD
        );
    },

    onMdlDeviceNameLanguageChange(event) {
        this.mdlDeviceNameLanguage.code = event.target.value;
    },

    async onSave() {
        if (this.isMdlDeviceNameTranslation && this.mdlDeviceNameLanguage.code) {
            await this.orm.call(
                this.props.resModel,
                "set_device_name_language_code",
                [[this.props.resId], this.mdlDeviceNameLanguage.code]
            );
        }
        return super.onSave(...arguments);
    },
});
