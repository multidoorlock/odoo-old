from odoo import api, fields, models


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    mdl_name_mode = fields.Selection(
        selection=[
            ("value", "ערך המאפיין"),
            ("attribute_value", "שם המאפיין + הערך"),
            ("hidden", "לא להציג בשם"),
        ],
        string="הצגה בשם",
        default="value",
        required=True,
        help="קובע כיצד המאפיין יוצג בשם הסופי של הווריאנט.",
    )
    mdl_name_prefix = fields.Char(
        string="טקסט לפני ישן (לא בשימוש)",
        help="שדה טכני לגרסאות קודמות; סדר השורות והטקסט שאחרי משמשים כעת.",
    )
    mdl_name_suffix = fields.Char(
        string="טקסט אחרי",
        help=(
            "רווח, /, +, -, או כל טקסט קבוע שיופיע אחרי ערך המאפיין "
            "ולפני המאפיין הבא."
        ),
    )

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
