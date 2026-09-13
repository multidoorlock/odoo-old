from odoo import api, fields, models


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    mdl_name_prefix = fields.Char(
        string="Legacy Prefix (Unused)",
        help="Compatibility field; row order and Text After are used now.",
    )
    mdl_name_suffix = fields.Char(
        string="Text After",
        translate=True,
        help=(
            "Separator between this attribute value and the next attribute. "
            "A normal space is added automatically; / and + remain attached."
        ),
    )
    mdl_variant_creation_mode = fields.Selection(
        related="attribute_id.create_variant",
        string="Variant Creation",
        readonly=True,
    )
    mdl_is_model_attribute = fields.Boolean(
        string="Converted Model Row",
        default=False,
        copy=True,
        help=(
            "Technical compatibility marker. The row behaves like any other attribute."
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            lines.product_tmpl_id._mdl_ensure_full_model_names()
            lines.product_tmpl_id._mdl_sync_variant_codes()
        return lines

    def write(self, vals):
        templates_before = self.product_tmpl_id
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates = templates_before | self.product_tmpl_id
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        return result

    def unlink(self):
        templates = self.product_tmpl_id
        result = super().unlink()
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        return result
