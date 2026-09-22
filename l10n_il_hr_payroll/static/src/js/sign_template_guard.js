/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SignTemplate } from "@sign/backend_components/sign_template/sign_template_action";

// Odoo can render the sidebar once while its asynchronous type list is still
// undefined (notably after following a stale browser action).  The native
// getter expects an array and otherwise crashes on `.filter()`.
patch(SignTemplate.prototype, {
    get signTemplateSidebarProps() {
        this.signItemTypes ||= [];
        return super.signTemplateSidebarProps;
    },
});
