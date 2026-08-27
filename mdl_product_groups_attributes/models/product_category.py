from odoo import api, fields, models
from odoo.fields import Domain

from .catalog_utils import clean_text


class ProductCategory(models.Model):
    _inherit = "product.category"

    mdl_sku_component = fields.Char(
        string="מק״ט ברירת מחדל",
        index=True,
        help=(
            "רכיב המק״ט הבסיסי של קבוצת הפריטים. שינוי הערך משפיע על כל "
            "הדגמים בקבוצה שלא הוגדרה בהם דריסה."
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
        previous_names = (
            {category.id: clean_text(category.name) for category in self}
            if "name" in vals
            else {}
        )
        result = super().write(vals)
        if (
            any(field_name in vals for field_name in ("name", "mdl_sku_component"))
            and not self.env.context.get("skip_mdl_catalog_sync")
        ):
            templates = self.env["product.template"].with_context(
                active_test=False
            ).search(
                Domain("categ_id", "in", self.ids)
                & Domain.OR(
                    [
                        Domain("mdl_model_sku_component", "!=", False),
                        Domain("mdl_model_sku_override", "!=", False),
                        Domain("mdl_sku_prefix", "!=", False),
                    ]
                )
            )
            if previous_names:
                templates._mdl_ensure_full_model_names(
                    {
                        template.id: previous_names.get(template.categ_id.id)
                        for template in templates
                    }
                )
            templates._mdl_sync_variant_codes()
        return result
