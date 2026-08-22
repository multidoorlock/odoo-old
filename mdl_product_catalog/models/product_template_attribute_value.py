from odoo import fields, models

from .catalog_utils import clean_text


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    mdl_default_name_component = fields.Char(
        related="product_attribute_value_id.name",
        string="טקסט ברירת מחדל",
        readonly=False,
        help="שינוי כאן משנה את ערך המאפיין בכל הדגמים המשתמשים בו.",
    )
    mdl_default_sku_component = fields.Char(
        related="product_attribute_value_id.mdl_sku_component",
        string="מק״ט ברירת מחדל",
        readonly=False,
        help="שינוי כאן משנה את רכיב המק״ט בכל הדגמים המשתמשים בערך.",
    )
    mdl_sku_component_override = fields.Char(
        string="שינוי מק״ט",
        help=(
            "אופציונלי לדגם זה בלבד. אם ריק, ייעשה שימוש במק״ט ברירת "
            "המחדל של ערך המאפיין."
        ),
    )
    mdl_name_component_override = fields.Char(
        string="שינוי טקסט",
        help=(
            "אופציונלי לדגם זה בלבד. אם ריק, ייעשה שימוש בטקסט ברירת "
            "המחדל של ערך המאפיין."
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
