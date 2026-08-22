from odoo import api, fields, models

from .catalog_utils import clean_text


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    mdl_sku_component = fields.Char(
        string="רכיב מק״ט",
        help=(
            "החלק שיתווסף למק״ט של הווריאנט כאשר הערך נבחר. "
            "המק״ט הסופי נשמר בשדה המקורי 'מק״ט פנימי' של Odoo."
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "mdl_sku_component" in vals:
                vals["mdl_sku_component"] = clean_text(vals["mdl_sku_component"])
        return super().create(vals_list)

    def write(self, vals):
        if "mdl_sku_component" in vals:
            vals["mdl_sku_component"] = clean_text(vals["mdl_sku_component"])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals for field_name in ("name", "mdl_sku_component")
        ):
            self.template_value_ids.product_tmpl_id._mdl_sync_variant_codes()
        return result
