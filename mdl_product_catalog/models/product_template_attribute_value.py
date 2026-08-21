from odoo import api, fields, models

from .catalog_utils import clean_text


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    mdl_base_sku_component = fields.Char(
        string="רכיב מק״ט בסיסי",
        related="product_attribute_value_id.mdl_sku_component",
        readonly=True,
    )
    mdl_sku_component_override = fields.Char(
        string="רכיב מק״ט בדגם",
        help="אופציונלי. אם ריק, ייעשה שימוש ברכיב המק״ט הבסיסי של ערך המאפיין.",
    )
    mdl_effective_sku_component = fields.Char(
        string="רכיב מק״ט בפועל",
        compute="_compute_mdl_catalog_components",
        store=True,
    )
    mdl_name_component_override = fields.Char(
        string="מלל בשם בדגם",
        help="אופציונלי. מאפשר לשנות את המלל רק בדגם הנוכחי.",
    )
    mdl_effective_name_component = fields.Char(
        string="מלל בשם בפועל",
        compute="_compute_mdl_catalog_components",
        store=True,
    )
    mdl_format_token = fields.Char(
        string="מציין בפורמט",
        compute="_compute_mdl_format_token",
    )

    @api.depends(
        "mdl_sku_component_override",
        "mdl_name_component_override",
        "product_attribute_value_id.mdl_sku_component",
        "product_attribute_value_id.mdl_name_component",
        "product_attribute_value_id.name",
    )
    def _compute_mdl_catalog_components(self):
        for value in self:
            base_value = value.product_attribute_value_id
            value.mdl_effective_sku_component = clean_text(
                value.mdl_sku_component_override or base_value.mdl_sku_component
            )
            value.mdl_effective_name_component = clean_text(
                value.mdl_name_component_override
                or base_value.mdl_name_component
                or base_value.name
            )

    @api.depends("attribute_id.name")
    def _compute_mdl_format_token(self):
        for value in self:
            value.mdl_format_token = (
                f"[{clean_text(value.attribute_id.name)}]"
                if value.attribute_id.name
                else False
            )

    def write(self, vals):
        for field_name in ("mdl_sku_component_override", "mdl_name_component_override"):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in (
                "mdl_sku_component_override",
                "mdl_name_component_override",
                "product_attribute_value_id",
            )
        ):
            self.product_tmpl_id._mdl_sync_variant_codes()
        return result

    def action_mdl_open_configuration(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "ערך מאפיין בדגם",
            "res_model": "product.template.attribute.value",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

