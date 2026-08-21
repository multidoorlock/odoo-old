from odoo import api, fields, models

from .catalog_utils import clean_text


class ProductCategory(models.Model):
    _inherit = "product.category"

    mdl_group_code = fields.Char(
        string="קוד קבוצת פריטים",
        index=True,
        copy=False,
        help="החלק הראשון במק״ט. לדוגמה: 10 עבור קבוצת דלתות.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "mdl_group_code" in vals:
                vals["mdl_group_code"] = clean_text(vals["mdl_group_code"])
        return super().create(vals_list)

    def write(self, vals):
        if "mdl_group_code" in vals:
            vals["mdl_group_code"] = clean_text(vals["mdl_group_code"])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and (
            "mdl_group_code" in vals or "name" in vals
        ):
            templates = self.env["product.template"].with_context(active_test=False).search(
                [("categ_id", "child_of", self.ids)]
            )
            templates._mdl_sync_variant_codes()
        return result

