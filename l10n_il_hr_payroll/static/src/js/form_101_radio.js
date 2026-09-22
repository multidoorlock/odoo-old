import { patch } from "@web/core/utils/patch";
import { SignablePDFIframe } from "@sign/components/sign_request/signable_PDF_iframe";

// Odoo's optional radio handler allows a selected option to be cleared.  In
// some Sign sessions the click handler is invoked more than once, so that
// toggle immediately clears the option and makes the control appear broken.
// Form 101 choices use conventional radio semantics: exactly the clicked
// option is selected, and another option in the set replaces it.
patch(SignablePDFIframe.prototype, {
    _selectForm101Radio(signItem) {
        const radioSet = this.radioSets[signItem.data.radio_set_id];
        radioSet.selected = signItem.data.id;
        for (const itemData of radioSet.items) {
            const renderedItem = this.getSignItemById(itemData.id);
            if (renderedItem) {
                renderedItem.el.checked = itemData.id === signItem.data.id;
            }
        }
        this.handleInput();
    },
    enableCustom(signItem) {
        super.enableCustom(signItem);
        if (signItem.data.form101Radio) {
            signItem.el.dataset.form101Patched = "1";
            // PDF.js also listens on the page for pointer/mouse interaction.
            // Keep those handlers from consuming a click intended for the
            // native form control.
            signItem.el.addEventListener("pointerdown", (event) => {
                event.stopImmediatePropagation();
                this._selectForm101Radio(signItem);
            }, true);
            for (const eventName of ["mousedown", "mouseup"]) {
                signItem.el.addEventListener(eventName, (event) => event.stopPropagation());
            }
            signItem.el.addEventListener("click", (event) => {
                event.stopImmediatePropagation();
                this._selectForm101Radio(signItem);
            }, true);
        }
    },
    handleRadioItemSelected(signItem) {
        if (!signItem.data.form101Radio) {
            return super.handleRadioItemSelected(signItem);
        }
        // Preserve whether the group is mandatory for validation, but use the
        // non-toggle branch while processing the click.  This prevents a
        // duplicated Sign click callback from immediately clearing the same
        // option again.
        const required = signItem.data.required;
        signItem.data.required = true;
        super.handleRadioItemSelected(signItem);
        signItem.data.required = required;
    },
});
