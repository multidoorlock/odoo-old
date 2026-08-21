from odoo import api, models


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            lines.product_tmpl_id._mdl_sync_variant_codes()
        return lines

    def write(self, vals):
        templates_before = self.product_tmpl_id
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            (templates_before | self.product_tmpl_id)._mdl_sync_variant_codes()
        return result

    def unlink(self):
        templates = self.product_tmpl_id
        result = super().unlink()
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates._mdl_sync_variant_codes()
        return result

