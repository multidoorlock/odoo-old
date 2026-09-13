from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .catalog_utils import clean_text


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    mdl_catalog_managed = fields.Boolean(
        related="product_tmpl_id.mdl_catalog_managed",
        readonly=True,
    )

    mdl_default_name_component = fields.Char(
        related="product_attribute_value_id.name",
        string="Default Text",
        readonly=False,
        help="Changing this updates the attribute value in every group that uses it.",
    )
    mdl_default_sku_component = fields.Char(
        related="product_attribute_value_id.mdl_sku_component",
        string="Default SKU",
        readonly=False,
        help="Changing this updates the SKU component in every group that uses it.",
    )
    mdl_sku_component_override = fields.Char(
        string="SKU Override",
        help=(
            "Optional for this group only. When empty, the attribute value's "
            "default SKU component is used."
        ),
    )
    mdl_name_component_override = fields.Char(
        string="Text Override",
        translate=True,
        help=(
            "Optional for this group only. When empty, the attribute value's "
            "default text is used."
        ),
    )
    mdl_name_component_value = fields.Char(
        string="Group Text",
        compute="_compute_mdl_name_component_value",
        inverse="_inverse_mdl_name_component_value",
        translate=True,
        help=(
            "The text displayed in this group. Editing affects only this "
            "group; reset restores the attribute value name."
        ),
    )
    mdl_sku_component_value = fields.Char(
        string="Group SKU",
        compute="_compute_mdl_sku_component_value",
        inverse="_inverse_mdl_sku_component_value",
        help=(
            "The SKU component used in this group. Editing affects only this "
            "group; reset restores the attribute value's default SKU."
        ),
    )
    mdl_attribute_group_id = fields.Many2one(
        comodel_name="product.attribute",
        string="Attribute Group Heading",
        compute="_compute_mdl_attribute_group",
    )
    mdl_is_attribute_group_start = fields.Boolean(
        compute="_compute_mdl_attribute_group",
    )

    @staticmethod
    def _resolved_component(source_value, override_value):
        source_value = clean_text(source_value)
        if source_value == "—":
            source_value = ""
        override_value = clean_text(override_value)
        if override_value == "—":
            return ""
        return override_value or source_value

    @staticmethod
    def _override_from_effective_value(source_value, effective_value):
        source_value = clean_text(source_value)
        if source_value == "—":
            source_value = ""
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
            if clean_text(value.mdl_name_component_override) != clean_text(override):
                value.with_context(skip_mdl_catalog_sync=True)._update_field_translations(
                    "mdl_name_component_value",
                    {self.env.lang or "en_US": value.mdl_name_component_value},
                )

    def get_field_translations(self, field_name, langs=None):
        if field_name != "mdl_name_component_value":
            return super().get_field_translations(field_name, langs=langs)
        self.ensure_one()
        self.check_access("read")
        self._check_field_access(self._fields[field_name], "read")
        langs = langs or [code for code, _name in self.env["res.lang"].get_installed()]
        return [
            {
                "lang": lang,
                "source": "",
                "value": self.with_context(lang=lang).mdl_name_component_value,
            }
            for lang in sorted(set(langs))
        ], {"translation_type": "char", "translation_show_source": False}

    def _update_field_translations(self, field_name, translations, digest=None, source_lang=""):
        if field_name not in ("mdl_name_component_value", "mdl_name_component_override"):
            return super()._update_field_translations(
                field_name, translations, digest=digest, source_lang=source_lang,
            )
        self.ensure_one()
        self.check_access("write")
        self._check_field_access(self._fields[field_name], "write")
        installed = {code for code, _name in self.env["res.lang"].get_installed()} | {"en_US"}
        if not isinstance(translations, dict) or any(
            value is not None and value is not False and not isinstance(value, str)
            for value in translations.values()
        ):
            raise ValidationError(_("Attribute text translations must be a language-to-text mapping."))
        if (set(translations) | {source_lang or "en_US"}) - installed:
            raise ValidationError(_("Activate the language before adding an attribute text translation."))
        if not translations:
            return True
        updates = {}
        for lang, text in translations.items():
            value = self.with_context(lang=lang)
            if field_name == "mdl_name_component_value":
                text = self._override_from_effective_value(
                    value.product_attribute_value_id.name, text,
                )
            # Empty text in an override restores this language's source. A
            # False translated Char would clear every stored language instead.
            updates[lang] = clean_text(text)
        override_field = self._fields["mdl_name_component_override"]
        previous = override_field._get_stored_translations(self) or {}
        if not previous or "en_US" in updates:
            # Odoo fills a missing English base from the first translation.
            # Preserve every untouched installed language's existing fallback
            # when the first override or its English value is edited.
            for lang in installed - updates.keys():
                if lang not in previous:
                    updates[lang] = previous.get("en_US", "")
        result = super(
            ProductTemplateAttributeValue,
            self.with_context(skip_mdl_catalog_sync=True),
        )._update_field_translations(
            "mdl_name_component_override", updates, digest=digest,
            source_lang=source_lang,
        )
        self.invalidate_recordset(["mdl_name_component_value"])
        if result and not self.env.context.get("skip_mdl_catalog_sync"):
            for lang in translations:
                template = self.product_tmpl_id.with_context(lang=lang)
                template._mdl_ensure_full_model_names()
                template._mdl_sync_variant_codes()
        return result

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
        # Keep the em dash as an internal omission marker for the renderer.
        # The effective field shown to users resolves it to an empty value.
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
        if "mdl_name_component_value" in vals:
            # Discard the inverse's protected cache, including a False value
            # that would otherwise mark this translated field empty in all langs.
            self.invalidate_recordset(["mdl_name_component_value"])
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
        self.action_mdl_reset_name_component()
        self.action_mdl_reset_sku_component()

    def action_mdl_reset_name_component(self):
        for value in self:
            value._update_field_translations(
                "mdl_name_component_override", {self.env.lang or "en_US": ""},
            )

    def action_mdl_reset_sku_component(self):
        self.write({"mdl_sku_component_override": False})
