from odoo import api, fields, models
from odoo.fields import Command

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
    mdl_name_component_value = fields.Char(
        string="טקסט בדגם",
        compute="_compute_mdl_name_component_value",
        inverse="_inverse_mdl_name_component_value",
        help=(
            "הטקסט שבפועל יוצג בדגם. עריכה משנה רק את הדגם הזה; "
            "איפוס מחזיר לשם של ערך המאפיין."
        ),
    )
    mdl_sku_component_value = fields.Char(
        string="מק״ט בדגם",
        compute="_compute_mdl_sku_component_value",
        inverse="_inverse_mdl_sku_component_value",
        help=(
            "רכיב המק״ט שבפועל ישמש בדגם. עריכה משנה רק את הדגם הזה; "
            "איפוס מחזיר למק״ט ברירת המחדל של ערך המאפיין."
        ),
    )
    mdl_excluded_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="לא תואם עם",
        compute="_compute_mdl_excluded_value_ids",
        inverse="_inverse_mdl_excluded_value_ids",
        help=(
            "ערכים בדגם שלא ניתן לבחור יחד עם הערך הזה. "
            "הכלל נשמר במנגנון התאימות הרגיל של Odoo."
        ),
    )

    @staticmethod
    def _resolved_component(source_value, override_value):
        override_value = clean_text(override_value)
        if override_value == "—":
            return ""
        return override_value or clean_text(source_value)

    @staticmethod
    def _override_from_effective_value(source_value, effective_value):
        source_value = clean_text(source_value)
        effective_value = clean_text(effective_value)
        if effective_value == source_value:
            return False
        return effective_value or "—"

    @api.depends(
        "product_attribute_value_id.name",
        "mdl_name_component_override",
    )
    def _compute_mdl_name_component_value(self):
        for value in self:
            value.mdl_name_component_value = self._resolved_component(
                value.product_attribute_value_id.name,
                value.mdl_name_component_override,
            )

    def _inverse_mdl_name_component_value(self):
        for value in self:
            override = self._override_from_effective_value(
                value.product_attribute_value_id.name,
                value.mdl_name_component_value,
            )
            if value.mdl_name_component_override != override:
                value.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_name_component_override": override}
                )

    @api.depends(
        "product_attribute_value_id.mdl_sku_component",
        "mdl_sku_component_override",
    )
    def _compute_mdl_sku_component_value(self):
        for value in self:
            value.mdl_sku_component_value = self._resolved_component(
                value.product_attribute_value_id.mdl_sku_component,
                value.mdl_sku_component_override,
            )

    def _inverse_mdl_sku_component_value(self):
        for value in self:
            override = self._override_from_effective_value(
                value.product_attribute_value_id.mdl_sku_component,
                value.mdl_sku_component_value,
            )
            if value.mdl_sku_component_override != override:
                value.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_sku_component_override": override}
                )

    def _mdl_local_excluded_values(self):
        """Return same-template exclusions as a symmetric value set."""
        self.ensure_one()
        template = self.product_tmpl_id
        if not template:
            return self.env["product.template.attribute.value"]

        outgoing_rules = self.exclude_for.filtered(
            lambda rule: rule.product_tmpl_id == template
        )
        excluded_values = outgoing_rules.value_ids.filtered(
            lambda other: (
                other.product_tmpl_id == template
                and other.attribute_id != self.attribute_id
                and other.ptav_active
            )
        )

        incoming_rules = self.env[
            "product.template.attribute.exclusion"
        ].search(
            [
                ("product_tmpl_id", "=", template.id),
                ("value_ids", "in", self.ids),
            ]
        )
        excluded_values |= incoming_rules.product_template_attribute_value_id.filtered(
            lambda other: (
                other.product_tmpl_id == template
                and other.attribute_id != self.attribute_id
                and other.ptav_active
            )
        )
        return excluded_values

    @api.depends(
        "exclude_for.value_ids",
        "product_tmpl_id.mdl_attribute_value_ids.exclude_for.value_ids",
    )
    def _compute_mdl_excluded_value_ids(self):
        for value in self:
            value.mdl_excluded_value_ids = value._mdl_local_excluded_values()

    def _inverse_mdl_excluded_value_ids(self):
        Exclusion = self.env["product.template.attribute.exclusion"]
        templates_to_invalidate = self.env["product.template"]

        for value in self:
            template = value.product_tmpl_id
            if not template:
                continue

            desired_values = value.mdl_excluded_value_ids.filtered(
                lambda other: (
                    other != value
                    and other.product_tmpl_id == template
                    and other.attribute_id != value.attribute_id
                    and other.ptav_active
                )
            )
            existing_values = value._mdl_local_excluded_values()
            values_to_remove = existing_values - desired_values
            values_to_add = desired_values - existing_values

            if values_to_remove:
                outgoing_rules = value.exclude_for.filtered(
                    lambda rule: rule.product_tmpl_id == template
                )
                for rule in outgoing_rules:
                    remaining_values = rule.value_ids - values_to_remove
                    if remaining_values == rule.value_ids:
                        continue
                    if remaining_values:
                        rule.write(
                            {"value_ids": [Command.set(remaining_values.ids)]}
                        )
                    else:
                        rule.unlink()

                incoming_rules = Exclusion.search(
                    [
                        ("product_tmpl_id", "=", template.id),
                        ("value_ids", "in", value.ids),
                        (
                            "product_template_attribute_value_id",
                            "in",
                            values_to_remove.ids,
                        ),
                    ]
                )
                for rule in incoming_rules:
                    remaining_values = rule.value_ids - value
                    if remaining_values:
                        rule.write(
                            {"value_ids": [Command.set(remaining_values.ids)]}
                        )
                    else:
                        rule.unlink()

            if values_to_add:
                Exclusion.create(
                    {
                        "product_template_attribute_value_id": value.id,
                        "product_tmpl_id": template.id,
                        "value_ids": [Command.set(values_to_add.ids)],
                    }
                )

            templates_to_invalidate |= template

        templates_to_invalidate.mdl_attribute_value_ids.invalidate_recordset(
            ["mdl_excluded_value_ids"]
        )

    def _mdl_get_sku_component(self):
        self.ensure_one()
        override = clean_text(self.mdl_sku_component_override)
        return override or clean_text(
            self.product_attribute_value_id.mdl_sku_component
        )

    def _mdl_get_name_component(self):
        self.ensure_one()
        return self._resolved_component(
            self.product_attribute_value_id.name,
            self.mdl_name_component_override,
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
                "mdl_name_component_value",
                "mdl_sku_component_value",
                "product_attribute_value_id",
            )
        ):
            self.product_tmpl_id._mdl_sync_variant_codes()
        return result

    def action_mdl_reset_components(self):
        self.write(
            {
                "mdl_name_component_override": False,
                "mdl_sku_component_override": False,
            }
        )
        return {"type": "ir.actions.client", "tag": "reload"}
