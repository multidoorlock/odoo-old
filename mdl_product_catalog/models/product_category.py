from odoo import models

from .catalog_utils import clean_text


class ProductCategory(models.Model):
    _inherit = "product.category"

    def write(self, vals):
        previous_names = (
            {category.id: clean_text(category.name) for category in self}
            if "name" in vals
            else {}
        )
        result = super().write(vals)
        if previous_names and not self.env.context.get("skip_mdl_catalog_sync"):
            templates = self.env["product.template"].with_context(
                active_test=False
            ).search([("categ_id", "in", self.ids), ("mdl_sku_prefix", "!=", False)])
            templates._mdl_ensure_full_model_names(
                {
                    template.id: previous_names.get(template.categ_id.id)
                    for template in templates
                }
            )
            templates._mdl_sync_variant_codes()
        return result
