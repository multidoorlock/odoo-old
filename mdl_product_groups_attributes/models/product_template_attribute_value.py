from odoo import api, fields, models

from .catalog_utils import clean_text


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    mdl_catalog_managed = fields.Boolean(
        related="product_tmpl_id.mdl_catalog_managed",
        readonly=True,
    )

    mdl_default_name_component = fields.Char(
        related="product_attribute_value_id.name",
        string="טקסט ברירת מחדל",
        readonly=False,
        help="שינוי כאן משנה את ערך המאפיין בכל הקבוצות המשתמשות בו.",
    )
    mdl_default_sku_component = fields.Char(
        related="product_attribute_value_id.mdl_sku_component",
        string="מק״ט ברירת מחדל",
        readonly=False,
        help="שינוי כאן משנה את רכיב המק״ט בכל הקבוצות המשתמשות בערך.",
    )
    mdl_sku_component_override = fields.Char(
        string="שינוי מק״ט",
        help=(
            "אופציונלי לקבוצה זו בלבד. אם ריק, ייעשה שימוש במק״ט ברירת "
            "המחדל של ערך המאפיין."
        ),
    )
    mdl_name_component_override = fields.Char(
        string="שינוי טקסט",
        help=(
            "אופציונלי לקבוצה זו בלבד. אם ריק, ייעשה שימוש בטקסט ברירת "
            "המחדל של ערך המאפיין."
        ),
    )
    mdl_name_component_value = fields.Char(
        string="טקסט בקבוצה",
        compute="_compute_mdl_name_component_value",
        inverse="_inverse_mdl_name_component_value",
        help=(
            "הטקסט שבפועל יוצג בקבוצה. עריכה משנה רק את הקבוצה הזו; "
            "איפוס מחזיר לשם של ערך המאפיין."
        ),
    )
    mdl_sku_component_value = fields.Char(
        string="מק״ט בקבוצה",
        compute="_compute_mdl_sku_component_value",
        inverse="_inverse_mdl_sku_component_value",
        help=(
            "רכיב המק״ט שבפועל ישמש בקבוצה. עריכה משנה רק את הקבוצה הזו; "
            "איפוס מחזיר למק״ט ברירת המחדל של ערך המאפיין."
        ),
    )
    mdl_attribute_group_id = fields.Many2one(
        comodel_name="product.attribute",
        string="מאפיין",
        compute="_compute_mdl_attribute_group",
    )
    mdl_is_attribute_group_start = fields.Boolean(
        compute="_compute_mdl_attribute_group",
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

    @api.depends(
        "attribute_id.name",
        "attribute_line_id.product_template_value_ids",
    )
    def _compute_mdl_attribute_group(self):
        for value in self:
            line_values = value.attribute_line_id.product_template_value_ids
            first_value = line_values.sorted(
                lambda item: (item.product_attribute_value_id.id, item.id)
            )[:1]
            is_first = value == first_value
            value.mdl_is_attribute_group_start = is_first
            value.mdl_attribute_group_id = (
                value.attribute_id if is_first else False
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
        reactivated_rules = self.env[
            "product.template.attribute.exclusion"
        ]
        if vals.get("ptav_active") is True:
            reactivated_rules = self.env[
                "product.template.attribute.exclusion"
            ].search(
                [
                    ("mdl_is_catalog_condition", "=", True),
                    ("mdl_combination_value_ids", "in", self.ids),
                ]
            )
        for field_name in (
            "mdl_sku_component_override",
            "mdl_name_component_override",
        ):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        result = super().write(vals)
        if reactivated_rules:
            # Odoo may clear the native pair representation while a PTAV is
            # unavailable.  The MDL combination remains the source of truth,
            # so restore the native fields when the same PTAV is reactivated.
            reactivated_rules.exists()._mdl_sync_native_from_combination()
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in (
                "mdl_sku_component_override",
                "mdl_name_component_override",
                "mdl_name_component_value",
                "mdl_sku_component_value",
                "product_attribute_value_id",
                "ptav_active",
            )
        ):
            self.product_tmpl_id._mdl_ensure_full_model_names()
            self.product_tmpl_id._mdl_sync_variant_codes()
        return result

    def unlink(self):
        templates = self.product_tmpl_id
        removed_value_ids = set(self.ids)
        rules = self.env["product.template.attribute.exclusion"].search(
            [
                ("mdl_is_catalog_condition", "=", True),
                ("mdl_combination_value_ids", "in", self.ids),
            ]
        )
        rule_dependencies = {
            rule.id: set(rule.mdl_combination_value_ids.ids)
            & removed_value_ids
            for rule in rules
        }
        result = super().unlink()
        # Native Odoo commonly implements removal from an attribute line by
        # archiving the PTAV (``ptav_active = False``), even though the public
        # operation is named ``unlink``.  Keep catalog rules in that case so
        # re-adding the value restores the exact business rule.  Only discard
        # rules that became structurally invalid after a genuine deletion.
        deleted_value_ids = removed_value_ids - set(self.exists().ids)
        invalid_rules = rules.exists().filtered(
            lambda rule: (
                bool(rule_dependencies.get(rule.id, set()) & deleted_value_ids)
                or len(rule.mdl_combination_value_ids) < 2
            )
        )
        if invalid_rules:
            invalid_rules.with_context(
                mdl_skip_combination_sync=True
            ).unlink()
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        return result

    def action_mdl_reset_components(self):
        self.write(
            {
                "mdl_name_component_override": False,
                "mdl_sku_component_override": False,
            }
        )

    def action_mdl_reset_name_component(self):
        self.write({"mdl_name_component_override": False})

    def action_mdl_reset_sku_component(self):
        self.write({"mdl_sku_component_override": False})
