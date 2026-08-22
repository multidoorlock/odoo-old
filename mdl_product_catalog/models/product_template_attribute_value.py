from odoo import fields, models

from .catalog_utils import clean_text


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    mdl_sku_component_override = fields.Char(
        string="דריסת רכיב מק״ט בדגם",
        help=(
            "אופציונלי. אם ריק, ייעשה שימוש ברכיב המק״ט של ערך המאפיין."
        ),
    )
    mdl_name_component_override = fields.Char(
        string="דריסת מלל בדגם",
        help=(
            "אופציונלי. אם ריק, ייעשה שימוש בשם הרגיל של ערך המאפיין."
        ),
    )

    def _mdl_get_sku_component(self):
        self.ensure_one()
        return clean_text(
            self.mdl_sku_component_override
            or self.product_attribute_value_id.mdl_sku_component
        )

    def _mdl_get_name_component(self):
        self.ensure_one()
        return clean_text(
            self.mdl_name_component_override
            or self.product_attribute_value_id.name
        )

    def write(self, vals):
        for field_name in (
            "mdl_sku_component_override",
            "mdl_name_component_override",
        ):
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
