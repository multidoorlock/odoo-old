from odoo import fields, models


class ProductTemplateAttributeExclusion(models.Model):
    _inherit = "product.template.attribute.exclusion"

    mdl_source_attribute_id = fields.Many2one(
        comodel_name="product.attribute",
        related="product_template_attribute_value_id.attribute_id",
        string="מאפיין מקור",
        readonly=True,
    )

