from odoo import api, fields, models

from .catalog_utils import clean_text


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    mdl_sku_component = fields.Char(
        string="רכיב מק״ט בסיסי",
        help="הרכיב שיתווסף למק״ט כאשר הערך משויך לדגם. ניתן לדרוס אותו בדגם מסוים.",
    )
    mdl_name_component = fields.Char(
        string="מלל בסיסי בשם",
        help="מלל חלופי לשם הערך. אם השדה ריק, ייעשה שימוש בשם הערך הרגיל.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for field_name in ("mdl_sku_component", "mdl_name_component"):
                if field_name in vals:
                    vals[field_name] = clean_text(vals[field_name])
        return super().create(vals_list)

    def write(self, vals):
        for field_name in ("mdl_sku_component", "mdl_name_component"):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in ("name", "mdl_sku_component", "mdl_name_component")
        ):
            self.template_value_ids.product_tmpl_id._mdl_sync_variant_codes()
        return result

