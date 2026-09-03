from odoo import api, fields, models
from .catalog_utils import clean_text


class ProductCategory(models.Model):
    _inherit = "product.category"

    mdl_sku_component = fields.Char(
        string="מק״ט קטגוריה ישן (טכני)",
        index=True,
        help=(
            "שדה תאימות לקטלוג הקודם. קבוצת הפריטים והמק״ט שלה מנוהלים "
            "כעת בתבנית המוצר בנפרד מקטגוריית המוצר."
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
        return super().write(vals)
