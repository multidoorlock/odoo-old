import itertools
from collections import Counter

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from .catalog_utils import clean_text, normalize_token, split_direction_marker


MODEL_ATTRIBUTE_NAME = "דגם"


def _name_without_group(group_name, model_name):
    group_name = clean_text(group_name)
    model_name = clean_text(model_name)
    if group_name and model_name == group_name:
        return ""
    prefix = f"{group_name} " if group_name else ""
    if prefix and model_name.startswith(prefix):
        return model_name[len(prefix):]
    return model_name


def _name_with_group(group_name, model_name):
    group_name = clean_text(group_name)
    model_name = _name_without_group(group_name, model_name)
    return clean_text(" ".join(part for part in (group_name, model_name) if part))


def _resolved_component(default_value, override_value):
    """Return an optional override, with an em dash meaning intentional blank."""
    default_value = clean_text(default_value)
    if default_value == "—":
        default_value = ""
    override_value = clean_text(override_value)
    if override_value == "—":
        return ""
    return override_value or default_value


def _override_from_effective_value(default_value, effective_value):
    """Store only a real deviation from the source value.

    An empty effective value is an intentional omission and is represented by
    an em dash internally.  This keeps an empty override available to mean
    "inherit from the source" while the user works with one effective field.
    """
    default_value = clean_text(default_value)
    if default_value == "—":
        default_value = ""
    effective_value = clean_text(effective_value)
    if effective_value == default_value:
        return False
    return effective_value or "—"


def _name_separator(value):
    """Return a natural separator between two displayed attribute values."""
    separator = str(value or "")
    return separator if separator.strip() else " "


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mdl_sku_prefix = fields.Char(
        string="Base SKU",
        compute="_compute_mdl_sku_prefix",
        inverse="_inverse_mdl_sku_prefix",
        store=True,
        index=True,
        copy=False,
        help=(
            "Computed from the product group SKU. Attribute values, including "
            "Model, are appended in attribute-row order. The final SKU is "
            "stored in Odoo's native Internal Reference field."
        ),
    )
    mdl_catalog_managed = fields.Boolean(
        string="Manage Names and SKUs by Attributes",
        default=False,
        index=True,
        copy=True,
        help=(
            "Enable for a template that represents a product group. Names, "
            "SKU components, attribute order, and combination rules are then "
            "managed on the Attributes tab. Regular Odoo products are unchanged."
        ),
    )
    mdl_group_default_name = fields.Char(
        string="Source Product Group Name",
        index="trigram",
        translate=True,
        help=(
            "Shared name for the products. Selecting a product category copies "
            "its name here, after which it can be adjusted for this group."
        ),
    )
    mdl_group_default_sku = fields.Char(
        string="Source Product Group SKU",
        index=True,
        help=(
            "Shared SKU component placed before attribute value components. "
            "Selecting a category copies its SKU component here."
        ),
    )
    mdl_group_name_override = fields.Char(
        string="Group Text Override",
        translate=True,
        help="Optional for this group. Enter — to omit the group from the name.",
    )
    mdl_group_sku_override = fields.Char(
        string="Group SKU Override",
        help="Optional for this group. Enter — to omit the group SKU component.",
    )
    mdl_model_default_name = fields.Char(
        string="Default Model Text",
        compute="_compute_mdl_model_default_name",
        inverse="_inverse_mdl_model_default_name",
        help="Model name without the product group name.",
    )
    mdl_model_sku_component = fields.Char(
        string="Default Model SKU",
        index=True,
        help="Default SKU component for the model.",
    )
    mdl_model_name_override = fields.Char(
        string="Model Text Override",
        translate=True,
        help="Optional. Enter — to omit the model from the product name.",
    )
    mdl_model_sku_override = fields.Char(
        string="Model SKU Override",
        help="Optional. Enter — to omit the model SKU component.",
    )
    mdl_group_name_value = fields.Char(
        string="Product Group Name",
        compute="_compute_mdl_group_name_value",
        inverse="_inverse_mdl_group_name_value",
        help=(
            "The group name used in product names. Editing creates an override "
            "for this group; reset restores the source group name."
        ),
    )
    mdl_group_sku_value = fields.Char(
        string="Product Group SKU",
        compute="_compute_mdl_group_sku_value",
        inverse="_inverse_mdl_group_sku_value",
        help=(
            "The group SKU component in use. Editing creates an override for "
            "this group; reset restores the source group SKU."
        ),
    )
    mdl_model_name_value = fields.Char(
        string="Model Name",
        compute="_compute_mdl_model_name_value",
        inverse="_inverse_mdl_model_name_value",
        help=(
            "The model name in use, without the group name. Editing creates an "
            "override for this model; reset restores its source name."
        ),
    )
    mdl_model_sku_value = fields.Char(
        string="Model SKU",
        compute="_compute_mdl_model_sku_value",
        inverse="_inverse_mdl_model_sku_value",
        help=(
            "The model SKU component in use. Editing creates an override for "
            "this model; reset restores the source component."
        ),
    )
    mdl_effective_base_name = fields.Char(
        string="Base Name",
        compute="_compute_mdl_effective_base_name",
        inverse="_inverse_mdl_effective_base_name",
        store=True,
        translate=True,
        help=(
            "The product name before attributes. By default it comes from the "
            "product group. Model is a regular, orderable attribute value."
        ),
    )
    mdl_model_as_attribute = fields.Boolean(
        string="Model Managed as Attribute",
        default=False,
        copy=True,
        help=(
            "Technical marker indicating that the legacy model was converted "
            "to a regular attribute value."
        ),
    )
    mdl_native_name_override = fields.Char(
        string="Custom Odoo Template Name",
        copy=False,
        translate=True,
        help=(
            "Technical field storing a template name explicitly selected by "
            "an Odoo action, such as duplicating with a custom name."
        ),
    )
    mdl_native_name_source = fields.Char(
        string="Source Name Before Odoo Override",
        copy=False,
        translate=True,
        help=(
            "Technical field storing the source name when a template is edited "
            "directly, allowing reset to restore the generated structure."
        ),
    )
    mdl_copy_requires_new_sku = fields.Boolean(
        string="New Group SKU Required",
        default=False,
        copy=False,
        help=(
            "Technical marker for a duplicated template. Internal references "
            "remain empty until a different group SKU is assigned."
        ),
    )
    mdl_copy_source_group_sku = fields.Char(
        string="Copied Source Group SKU",
        copy=False,
        help=(
            "Technical value used until the duplicated group receives a SKU "
            "that differs from the source group."
        ),
    )
    mdl_model_value_summary = fields.Char(
        string="Models",
        compute="_compute_mdl_model_value_summary",
        help="Model attribute values assigned to the product group.",
    )
    mdl_attribute_value_ids = fields.One2many(
        comodel_name="product.template.attribute.value",
        inverse_name="product_tmpl_id",
        string="Group Attribute Values",
    )
    mdl_exclusion_ids = fields.One2many(
        comodel_name="product.template.attribute.exclusion",
        inverse_name="product_tmpl_id",
        string="Combination Rules",
        help=(
            "Each row defines an allowed or blocked combination of two or more "
            "values. A rule can depend on Model and several attributes."
        ),
    )
    mdl_active_variant_count = fields.Integer(
        string="Active Products",
        compute="_compute_mdl_variant_overview",
    )
    mdl_archived_variant_count = fields.Integer(
        string="Archived Products",
        compute="_compute_mdl_variant_overview",
    )
    mdl_blocked_variant_count = fields.Integer(
        string="Blocked Combinations",
        compute="_compute_mdl_variant_overview",
    )
    @api.depends(
        "attribute_line_ids.mdl_is_model_attribute",
        "attribute_line_ids.value_ids.name",
    )
    def _compute_mdl_model_value_summary(self):
        for template in self:
            model_values = template.attribute_line_ids.filtered(
                "mdl_is_model_attribute"
            ).value_ids
            template.mdl_model_value_summary = ", ".join(
                model_values.sorted(
                    lambda value: (value.sequence, value.id)
                ).mapped("name")
            ) or False

    # Kept out of the form: users manage the readable format through the
    # ordered attribute rows and their single "Text After" field.
    mdl_variant_base_name = fields.Char(
        string="Legacy Base Name (Unused)",
        copy=True,
        translate=True,
    )
    mdl_name_suffix = fields.Char(
        string="Final Format Text (Technical)",
        copy=True,
        translate=True,
    )

    @api.depends(
        "mdl_group_default_sku",
        "mdl_group_sku_override",
        "mdl_model_sku_component",
        "mdl_model_sku_override",
        "mdl_model_as_attribute",
    )
    def _compute_mdl_sku_prefix(self):
        for template in self:
            group_sku = _resolved_component(
                template.mdl_group_default_sku,
                template.mdl_group_sku_override,
            )
            model_sku = (
                ""
                if template.mdl_model_as_attribute
                else _resolved_component(
                    template.mdl_model_sku_component,
                    template.mdl_model_sku_override,
                )
            )
            template.mdl_sku_prefix = f"{group_sku}{model_sku}" or False

    def _inverse_mdl_sku_prefix(self):
        for template in self:
            effective_value = clean_text(template.mdl_sku_prefix)
            source_value = clean_text(
                f"{template.mdl_group_default_sku or ''}"
                f"{'' if template.mdl_model_as_attribute else template.mdl_model_sku_component or ''}"
            )
            if template.mdl_model_as_attribute:
                values = {
                    "mdl_group_sku_override": _override_from_effective_value(
                        template.mdl_group_default_sku,
                        effective_value,
                    ),
                    "mdl_model_sku_override": "—",
                }
            elif effective_value == source_value:
                values = {
                    "mdl_group_sku_override": False,
                    "mdl_model_sku_override": False,
                }
            else:
                values = {
                    "mdl_group_sku_override": "—",
                    "mdl_model_sku_override": effective_value or "—",
                }
            template.with_context(skip_mdl_catalog_sync=True).write(values)
        self._mdl_sync_variant_codes()

    @api.depends("name", "mdl_group_default_name")
    def _compute_mdl_model_default_name(self):
        for template in self:
            template.mdl_model_default_name = _name_without_group(
                template.mdl_group_default_name,
                template.name,
            )

    def _inverse_mdl_model_default_name(self):
        for template in self:
            full_name = _name_with_group(
                template.mdl_group_default_name,
                template.mdl_model_default_name,
            )
            if full_name and template.name != full_name:
                template.with_context(skip_mdl_catalog_sync=True).name = full_name

    @api.depends("mdl_group_default_name", "mdl_group_name_override")
    def _compute_mdl_group_name_value(self):
        for template in self:
            template.mdl_group_name_value = _resolved_component(
                template.mdl_group_default_name,
                template.mdl_group_name_override,
            )

    def _inverse_mdl_group_name_value(self):
        for template in self:
            override = _override_from_effective_value(
                template.mdl_group_default_name,
                template.mdl_group_name_value,
            )
            if template.mdl_group_name_override != override:
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_group_name_override": override}
                )

    @api.depends("mdl_group_default_sku", "mdl_group_sku_override")
    def _compute_mdl_group_sku_value(self):
        for template in self:
            template.mdl_group_sku_value = _resolved_component(
                template.mdl_group_default_sku,
                template.mdl_group_sku_override,
            )

    def _inverse_mdl_group_sku_value(self):
        for template in self:
            override = _override_from_effective_value(
                template.mdl_group_default_sku,
                template.mdl_group_sku_value,
            )
            if template.mdl_group_sku_override != override:
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_group_sku_override": override}
                )

    @api.depends("name", "mdl_group_default_name", "mdl_model_name_override")
    def _compute_mdl_model_name_value(self):
        for template in self:
            template.mdl_model_name_value = _resolved_component(
                _name_without_group(template.mdl_group_default_name, template.name),
                template.mdl_model_name_override,
            )

    def _inverse_mdl_model_name_value(self):
        for template in self:
            override = _override_from_effective_value(
                _name_without_group(template.mdl_group_default_name, template.name),
                template.mdl_model_name_value,
            )
            if template.mdl_model_name_override != override:
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_model_name_override": override}
                )

    @api.depends("mdl_model_sku_component", "mdl_model_sku_override")
    def _compute_mdl_model_sku_value(self):
        for template in self:
            template.mdl_model_sku_value = _resolved_component(
                template.mdl_model_sku_component,
                template.mdl_model_sku_override,
            )

    def _inverse_mdl_model_sku_value(self):
        for template in self:
            override = _override_from_effective_value(
                template.mdl_model_sku_component,
                template.mdl_model_sku_value,
            )
            if template.mdl_model_sku_override != override:
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_model_sku_override": override}
                )

    @api.depends(
        "name",
        "mdl_group_default_name",
        "mdl_group_name_override",
        "mdl_model_name_override",
        "mdl_model_as_attribute",
        "mdl_native_name_override",
    )
    def _compute_mdl_effective_base_name(self):
        for template in self:
            native_override = clean_text(template.mdl_native_name_override)
            if native_override:
                template.mdl_effective_base_name = _resolved_component(
                    "",
                    native_override,
                )
                continue
            group_name = _resolved_component(
                template.mdl_group_default_name,
                template.mdl_group_name_override,
            )
            model_name = (
                ""
                if template.mdl_model_as_attribute
                else _resolved_component(
                    _name_without_group(
                        template.mdl_group_default_name,
                        template.name,
                    ),
                    template.mdl_model_name_override,
                )
            )
            template.mdl_effective_base_name = clean_text(
                " ".join(part for part in (group_name, model_name) if part)
            )

    def _inverse_mdl_effective_base_name(self):
        for template in self:
            effective_value = clean_text(template.mdl_effective_base_name)
            if clean_text(template.mdl_native_name_override):
                values = {
                    "mdl_native_name_override": effective_value or "—",
                }
                if effective_value:
                    values["name"] = effective_value
                template.with_context(skip_mdl_catalog_sync=True).write(
                    values
                )
                continue
            source_value = _name_with_group(
                template.mdl_group_default_name,
                (
                    ""
                    if template.mdl_model_as_attribute
                    else _name_without_group(
                        template.mdl_group_default_name,
                        template.name,
                    )
                ),
            )
            if template.mdl_model_as_attribute:
                values = {
                    "mdl_group_name_override": _override_from_effective_value(
                        template.mdl_group_default_name,
                        effective_value,
                    ),
                    "mdl_model_name_override": "—",
                }
            elif effective_value == source_value:
                values = {
                    "mdl_group_name_override": False,
                    "mdl_model_name_override": False,
                }
            else:
                values = {
                    "mdl_group_name_override": "—",
                    "mdl_model_name_override": effective_value or "—",
                }
            template.with_context(skip_mdl_catalog_sync=True).write(values)
        self._mdl_ensure_full_model_names()
        self._mdl_sync_variant_codes()

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for template, vals in zip(self, vals_list):
            if not template.mdl_catalog_managed:
                continue
            if "mdl_native_name_override" not in default:
                if "name" in default or template.mdl_native_name_override:
                    # Preserve the name generated by Odoo, including its
                    # translated duplicate suffix, for a source whose native
                    # template name was explicitly customized.
                    vals["mdl_native_name_override"] = (
                        "—"
                        if (
                            "name" not in default
                            and clean_text(template.mdl_native_name_override)
                            == "—"
                        )
                        else clean_text(vals.get("name"))
                    )
            if "mdl_group_default_name" not in default:
                if "name" in default:
                    # ``name`` is part of Odoo's public copy contract.  Keep
                    # the catalog source aligned with an explicitly supplied
                    # copied name instead of letting the post-copy catalog
                    # normalization silently restore the source group name.
                    vals["mdl_group_default_name"] = clean_text(
                        default["name"]
                    )
                else:
                    vals["mdl_group_default_name"] = _(
                        "%s (copy)",
                        template.mdl_group_default_name,
                    )
            if vals.get("mdl_native_name_override"):
                if template.mdl_model_as_attribute:
                    model_values = template.attribute_line_ids.filtered(
                        "mdl_is_model_attribute"
                    ).product_template_value_ids._only_active()
                    model_name = (
                        model_values.product_attribute_value_id.name
                        if len(model_values) == 1
                        else ""
                    )
                else:
                    model_name = _name_without_group(
                        template.mdl_group_default_name,
                        template.mdl_native_name_source or template.name,
                    )
                vals["mdl_native_name_source"] = _name_with_group(
                    vals.get("mdl_group_default_name"),
                    model_name,
                )
            source_group_sku = _resolved_component(
                template.mdl_group_default_sku,
                template.mdl_group_sku_override,
            )
            if (
                "mdl_group_default_sku" in default
                and "mdl_group_sku_override" not in default
            ):
                # An explicitly supplied copied source must not be hidden by
                # the source template's inherited per-group override.
                vals["mdl_group_sku_override"] = False
            copied_group_sku = _resolved_component(
                vals.get("mdl_group_default_sku"),
                vals.get("mdl_group_sku_override"),
            )
            requires_new_sku = (
                not copied_group_sku
                or copied_group_sku == source_group_sku
            )
            vals["mdl_copy_requires_new_sku"] = requires_new_sku
            vals["mdl_copy_source_group_sku"] = (
                source_group_sku if requires_new_sku else False
            )
            if not requires_new_sku:
                vals["mdl_group_default_sku"] = copied_group_sku
                vals["mdl_group_sku_override"] = False
        return vals_list

    def copy(self, default=None):
        default = dict(default or {})
        # Native copy recreates variants.  Defer catalog synchronization until
        # overrides/rules have been mapped and a distinct group SKU is known;
        # otherwise every generated internal reference would be duplicated.
        copied = super(
            ProductTemplate,
            self.with_context(skip_mdl_catalog_sync=True),
        ).copy(default=default)
        # The skip flag is needed only while Odoo creates the duplicate.  Do
        # not leak it to the recordset returned to normal callers: subsequent
        # edits (for example assigning the new group SKU) must synchronize in
        # the usual way.
        copied = copied.with_context(skip_mdl_catalog_sync=False)
        for source_template, copied_template in zip(self, copied):
            if not (
                source_template.mdl_catalog_managed
                and copied_template.mdl_catalog_managed
            ):
                copied_template.mdl_exclusion_ids.filtered(
                    "mdl_is_catalog_condition"
                ).unlink()
                if not copied_template.mdl_catalog_managed:
                    copied_template.with_context(
                        skip_mdl_catalog_sync=True
                    ).write(
                        {
                            "mdl_copy_requires_new_sku": False,
                            "mdl_copy_source_group_sku": False,
                        }
                    )
                continue
            copied_values = {
                (
                    value.attribute_id.id,
                    value.product_attribute_value_id.id,
                ): value
                for value in (
                    copied_template.attribute_line_ids
                    .product_template_value_ids
                    ._only_active()
                )
            }
            source_values = (
                source_template.attribute_line_ids
                .product_template_value_ids
                ._only_active()
            )
            value_map = {}
            for source in source_values:
                key = (
                    source.attribute_id.id,
                    source.product_attribute_value_id.id,
                )
                target = copied_values.get(key)
                if not target:
                    # Replacing ``attribute_line_ids`` is part of Odoo's copy
                    # API.  A missing value can therefore be intentional.
                    continue
                value_map[source.id] = target
                target.with_context(skip_mdl_catalog_sync=True).write(
                    {
                        "mdl_name_component_override": (
                            source.mdl_name_component_override
                        ),
                        "mdl_sku_component_override": (
                            source.mdl_sku_component_override
                        ),
                    }
                )

            rule_values = []
            for rule in source_template.mdl_exclusion_ids.filtered(
                "mdl_is_catalog_condition"
            ):
                mapped_values = [
                    value_map[value_id].id
                    for value_id in rule.mdl_combination_value_ids.ids
                    if value_id in value_map
                ]
                if len(mapped_values) != len(rule.mdl_combination_value_ids):
                    # Do not transplant a rule that references a line removed
                    # through ``copy(default=...)``.
                    continue
                rule_values.append(
                    {
                        "product_tmpl_id": copied_template.id,
                        "mdl_is_catalog_condition": True,
                        "mdl_rule_type": rule.mdl_rule_type,
                        "mdl_combination_value_ids": [
                            Command.set(mapped_values)
                        ],
                    }
                )
            if rule_values:
                self.env["product.template.attribute.exclusion"].create(
                    rule_values
                )

            target_variants = copied_template.with_context(
                active_test=False
            ).product_variant_ids
            variants_by_values = {}
            for product in target_variants:
                key = frozenset(
                    product.product_template_attribute_value_ids
                    ._only_active()
                    .product_attribute_value_id.ids
                )
                variants_by_values.setdefault(key, []).append(product)
            legacy_blocked = source_template.with_context(
                active_test=False
            ).product_variant_ids.filtered(
                lambda product: not product.mdl_catalog_allowed
            )
            for source_product in legacy_blocked:
                key = frozenset(
                    source_product.product_template_attribute_value_ids
                    ._only_active()
                    .product_attribute_value_id.ids
                )
                candidates = variants_by_values.get(key, [])
                if len(candidates) == 1:
                    target_product = candidates[0]
                    target_product.with_context(
                        skip_mdl_catalog_sync=True
                    ).write(
                        {
                            "mdl_catalog_allowed": False,
                            "active": False,
                        }
                    )
            copied_template._mdl_ensure_full_model_names()
            if copied_template.mdl_copy_requires_new_sku:
                target_variants.with_context(
                    skip_mdl_catalog_sync=True
                ).write({"default_code": False})
            else:
                copied_template._mdl_sync_variant_codes()
        return copied

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            category = self.env["product.category"].browse(
                vals.get("categ_id")
            ).exists()
            is_catalog_values = any(
                field_name in vals and clean_text(vals.get(field_name))
                for field_name in (
                    "mdl_group_default_name",
                    "mdl_group_default_sku",
                    "mdl_model_sku_component",
                    "mdl_group_name_override",
                    "mdl_group_sku_override",
                    "mdl_model_name_override",
                    "mdl_model_sku_override",
                    "mdl_name_suffix",
                )
            )
            explicit_catalog = bool(
                vals.get("mdl_catalog_managed") or is_catalog_values
            )
            if is_catalog_values:
                vals.setdefault("mdl_catalog_managed", True)
            if category and explicit_catalog:
                vals.setdefault("mdl_group_default_name", category.name)
                vals.setdefault(
                    "mdl_group_default_sku",
                    category.mdl_sku_component,
                )
            for field_name in (
                "mdl_group_default_name",
                "mdl_group_default_sku",
                "mdl_group_name_override",
                "mdl_group_sku_override",
                "mdl_model_sku_component",
                "mdl_model_name_override",
                "mdl_model_sku_override",
                "mdl_native_name_override",
                "mdl_native_name_source",
                "mdl_copy_source_group_sku",
            ):
                if field_name in vals:
                    vals[field_name] = clean_text(vals[field_name])
        templates = super().create(vals_list)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        return templates

    @api.onchange("categ_id")
    def _onchange_mdl_category_sources(self):
        """Use the selected native Odoo category as the group source."""
        for template in self.filtered("mdl_catalog_managed"):
            if not template.categ_id:
                continue
            template.mdl_group_default_name = clean_text(
                template.categ_id.name
            )
            template.mdl_group_default_sku = clean_text(
                template.categ_id.mdl_sku_component
            )

    @api.onchange("mdl_catalog_managed")
    def _onchange_mdl_catalog_managed(self):
        """Seed empty sources without overwriting settings on re-enable."""
        for template in self.filtered("mdl_catalog_managed"):
            if not template.categ_id:
                continue
            if not template.mdl_group_default_name:
                template.mdl_group_default_name = clean_text(
                    template.categ_id.name
                )
            if not template.mdl_group_default_sku:
                template.mdl_group_default_sku = clean_text(
                    template.categ_id.mdl_sku_component
                )

    def write(self, vals):
        vals = dict(vals)
        catalog_source_fields = (
            "mdl_group_default_name",
            "mdl_group_default_sku",
            "mdl_group_name_override",
            "mdl_group_sku_override",
            "mdl_model_sku_component",
            "mdl_model_name_override",
            "mdl_model_sku_override",
        )
        has_catalog_values = any(
            field_name in vals and clean_text(vals.get(field_name))
            for field_name in catalog_source_fields
        )
        will_enable_catalog = (
            vals.get("mdl_catalog_managed") is True
            if "mdl_catalog_managed" in vals
            else has_catalog_values
        )
        newly_managed_ids = (
            self.filtered(lambda template: not template.mdl_catalog_managed).ids
            if will_enable_catalog
            else []
        )
        category = (
            self.env["product.category"].browse(vals.get("categ_id")).exists()
            if "categ_id" in vals and vals.get("categ_id")
            else self.env["product.category"]
        )
        catalog_active_for_all = (
            vals.get("mdl_catalog_managed") is True
            or (
                "mdl_catalog_managed" not in vals
                and all(template.mdl_catalog_managed for template in self)
            )
        )
        if category and catalog_active_for_all:
            vals.setdefault(
                "mdl_group_default_name",
                clean_text(category.name),
            )
            vals.setdefault(
                "mdl_group_default_sku",
                clean_text(category.mdl_sku_component),
            )
        group_name_was_provided = "mdl_group_default_name" in vals
        group_sku_was_provided = "mdl_group_default_sku" in vals
        pending_source_skus = {
            template.id: (
                clean_text(template.mdl_copy_source_group_sku)
                or _resolved_component(
                    template.mdl_group_default_sku,
                    template.mdl_group_sku_override,
                )
            )
            for template in self.filtered("mdl_copy_requires_new_sku")
        }
        native_name_sources = {}
        if (
            "name" in vals
            and "mdl_native_name_override" not in vals
            and not self.env.context.get("skip_mdl_catalog_sync")
        ):
            native_name_sources = {
                template.id: clean_text(template.name)
                for template in self.filtered("mdl_catalog_managed")
                if not template.mdl_native_name_source
            }
        if "mdl_native_name_override" not in vals:
            if "name" in vals and not self.env.context.get(
                "skip_mdl_catalog_sync"
            ) and (
                vals.get("mdl_catalog_managed") is True
                or all(template.mdl_catalog_managed for template in self)
            ):
                vals["mdl_native_name_override"] = clean_text(vals["name"])
            elif (
                "mdl_group_default_name" in vals
                and not self.env.context.get("skip_mdl_catalog_sync")
            ):
                vals["mdl_native_name_override"] = False
                vals.setdefault("mdl_native_name_source", False)
        previous_group_names = (
            {
                template.id: clean_text(template.mdl_group_default_name)
                for template in self
            }
            if "mdl_group_default_name" in vals
            else {}
        )
        for field_name in (
            "mdl_group_default_name",
            "mdl_group_default_sku",
            "mdl_group_name_override",
            "mdl_group_sku_override",
            "mdl_model_sku_component",
            "mdl_model_name_override",
            "mdl_model_sku_override",
            "mdl_native_name_override",
            "mdl_native_name_source",
            "mdl_copy_source_group_sku",
        ):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        if has_catalog_values:
            vals.setdefault("mdl_catalog_managed", True)
        result = super().write(vals)
        for template in self.browse(newly_managed_ids).exists():
            seed_values = {}
            if not group_name_was_provided and not template.mdl_group_default_name:
                seed_values["mdl_group_default_name"] = clean_text(
                    template.categ_id.name
                )
            if not group_sku_was_provided and not template.mdl_group_default_sku:
                seed_values["mdl_group_default_sku"] = clean_text(
                    template.categ_id.mdl_sku_component
                )
            if seed_values:
                super(
                    ProductTemplate,
                    template.with_context(skip_mdl_catalog_sync=True),
                ).write(seed_values)
        for template_id, source_group_sku in pending_source_skus.items():
            template = self.browse(template_id).exists()
            if not template or not template.mdl_copy_requires_new_sku:
                continue
            effective_group_sku = _resolved_component(
                template.mdl_group_default_sku,
                template.mdl_group_sku_override,
            )
            if (
                effective_group_sku
                and effective_group_sku != source_group_sku
            ):
                # Promote the distinct value to the copied group's source.
                # Resetting the override later can therefore never restore the
                # source template's duplicate internal references.
                super(
                    ProductTemplate,
                    template.with_context(skip_mdl_catalog_sync=True),
                ).write(
                    {
                        "mdl_group_default_sku": effective_group_sku,
                        "mdl_group_sku_override": False,
                        "mdl_copy_requires_new_sku": False,
                        "mdl_copy_source_group_sku": False,
                    }
                )
        for template_id, source_name in native_name_sources.items():
            template = self.browse(template_id).exists()
            if template and source_name:
                super(
                    ProductTemplate,
                    template.with_context(skip_mdl_catalog_sync=True),
                ).write({"mdl_native_name_source": source_name})
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in (
                "name",
                "mdl_group_default_name",
                "mdl_group_default_sku",
                "mdl_model_default_name",
                "mdl_group_name_override",
                "mdl_group_sku_override",
                "mdl_model_sku_component",
                "mdl_model_name_override",
                "mdl_model_sku_override",
                "mdl_group_name_value",
                "mdl_group_sku_value",
                "mdl_model_name_value",
                "mdl_model_sku_value",
                "mdl_model_as_attribute",
                "mdl_catalog_managed",
                "mdl_native_name_override",
            )
        ):
            self._mdl_ensure_full_model_names(previous_group_names)
            self._mdl_sync_variant_codes()
        return result

    def action_mdl_reset_group_values(self):
        self.ensure_one()
        self.write(
            {
                "mdl_group_name_override": False,
                "mdl_group_sku_override": False,
            }
        )

    def action_mdl_reset_model_values(self):
        self.ensure_one()
        self.write(
            {
                "mdl_model_name_override": False,
                "mdl_model_sku_override": False,
            }
        )

    def action_mdl_reset_base_name(self):
        self.ensure_one()
        values = {
            "mdl_group_name_override": False,
            "mdl_model_name_override": False,
            "mdl_native_name_override": False,
            "mdl_native_name_source": False,
        }
        if self.mdl_native_name_source:
            values["name"] = self.mdl_native_name_source
        self.write(values)

    def action_mdl_reset_base_sku(self):
        self.ensure_one()
        self.write(
            {
                "mdl_group_sku_override": False,
                "mdl_model_sku_override": False,
            }
        )

    def action_mdl_reset_base_values(self):
        self.ensure_one()
        values = {
            "mdl_group_name_override": False,
            "mdl_group_sku_override": False,
            "mdl_model_name_override": False,
            "mdl_model_sku_override": False,
            "mdl_native_name_override": False,
            "mdl_native_name_source": False,
        }
        if self.mdl_native_name_source:
            values["name"] = self.mdl_native_name_source
        self.write(values)

    def _mdl_ensure_full_model_names(self, previous_group_names=None):
        previous_group_names = previous_group_names or {}
        for template in self.filtered("mdl_catalog_managed"):
            native_override = clean_text(template.mdl_native_name_override)
            if native_override:
                native_name = _resolved_component("", native_override)
                if native_name and template.name != native_name:
                    super(
                        ProductTemplate,
                        template.with_context(skip_mdl_catalog_sync=True),
                    ).write({"name": native_name})
                continue
            if template.mdl_model_as_attribute:
                model_values = template.attribute_line_ids.filtered(
                    "mdl_is_model_attribute"
                ).product_template_value_ids._only_active()
                model_name = (
                    model_values.product_attribute_value_id.name
                    if len(model_values) == 1
                    else ""
                )
                full_name = _name_with_group(
                    template.mdl_group_default_name,
                    model_name,
                )
                if full_name and template.name != full_name:
                    super(
                        ProductTemplate,
                        template.with_context(skip_mdl_catalog_sync=True),
                    ).write({"name": full_name})
                continue
            previous_group = previous_group_names.get(
                template.id,
                template.mdl_group_default_name,
            )
            model_name = _name_without_group(previous_group, template.name)
            full_name = _name_with_group(
                template.mdl_group_default_name,
                model_name,
            )
            updates = {}
            if full_name and template.name != full_name:
                updates["name"] = full_name
            if updates:
                super(
                    ProductTemplate,
                    template.with_context(skip_mdl_catalog_sync=True),
                ).write(updates)

    def _mdl_render_catalog_values(self, combination):
        self.ensure_one()
        ordered_values = combination.sorted(
            lambda item: (
                item.attribute_line_id.sequence,
                item.attribute_id.sequence,
                item.attribute_id.id,
                item.id,
            )
        )
        sku_parts = [clean_text(self.mdl_sku_prefix)]
        missing_components = []
        values_by_line = {value.attribute_line_id.id: value for value in ordered_values}
        for value in ordered_values:
            if value.attribute_id.create_variant == "no_variant":
                continue
            component = value._mdl_get_sku_component()
            if component == "—":
                continue
            if component:
                sku_parts.append(component)
            else:
                missing_components.append(value.display_name)

        final_name = clean_text(self.mdl_effective_base_name)
        deferred_name_markers = []
        displayed_values = 0
        previous_line_suffix = ""
        last_line_had_text = False
        ordered_lines = self.attribute_line_ids.filtered("active").sorted(
            lambda item: (item.sequence, item.attribute_id.sequence, item.id)
        )
        for line in ordered_lines:
            value = values_by_line.get(line.id)
            if not value:
                continue
            value_name = value._mdl_get_name_component()
            if "פתיחה" in normalize_token(line.attribute_id.name):
                value_name, marker = split_direction_marker(value_name)
                if marker:
                    deferred_name_markers.append(marker)
            if value_name:
                if not displayed_values and final_name:
                    final_name += " "
                elif displayed_values:
                    final_name += previous_line_suffix
                final_name += value_name
                displayed_values += 1
                last_line_had_text = True
            else:
                last_line_had_text = False
            # "Text After" is the separator before the next row.  Deferring
            # it until the next non-empty value keeps optional values such as
            # "ללא הלבשה" from leaving a dangling '+' in the final name.
            previous_line_suffix = _name_separator(line.mdl_name_suffix)
        terminal_text = self.mdl_name_suffix or ""
        if not terminal_text and last_line_had_text:
            # Backward compatibility for formats created before terminal text
            # was stored on the template itself.
            terminal_text = previous_line_suffix
        if terminal_text:
            final_name += terminal_text
        if deferred_name_markers:
            final_name += " " + " ".join(deferred_name_markers)
        return "".join(sku_parts), clean_text(final_name), missing_components

    def _mdl_get_catalog_issues(self, include_sync_state=False):
        self.ensure_one()
        if not self.mdl_catalog_managed:
            return []

        issues = []
        if self.mdl_copy_requires_new_sku:
            issues.append(
                _("This duplicated product group needs a new group SKU.")
            )
        if not self.mdl_group_default_name:
            issues.append(_("The product group has no name."))
        if not self.categ_id:
            issues.append(_("No product category is selected."))

        dynamic_attributes = self.attribute_line_ids.attribute_id.filtered(
            lambda attribute: attribute.create_variant == "dynamic"
        )
        if dynamic_attributes:
            issues.append(
                _(
                    "These attributes create variants dynamically, so not all "
                    "combinations will be generated: %(attributes)s.",
                    attributes=", ".join(dynamic_attributes.mapped("name")),
                )
            )

        variants = self.with_context(active_test=False).product_variant_ids
        rendered = {
            product: self._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            for product in variants
        }
        generated_skus = [sku for sku, _name, _missing in rendered.values() if sku]
        for sku, count in Counter(generated_skus).items():
            if count > 1:
                issues.append(
                    _("SKU %(sku)s is generated for %(count)s products in the group.",
                      sku=sku, count=count)
                )

        for product, (sku, _name, missing) in rendered.items():
            if missing:
                issues.append(
                    _(
                        "Product %(product)s is missing SKU components for: %(values)s.",
                        product=product.id,
                        values=", ".join(missing),
                    )
                )
            if include_sync_state and sku and product.default_code != sku:
                issues.append(
                    _("Product %(product)s has not yet been updated to SKU %(sku)s.",
                      product=product.id, sku=sku)
                )

        if generated_skus:
            external_products = self.env["product.product"].with_context(
                active_test=False
            ).search(
                [
                    ("id", "not in", variants.ids),
                    ("default_code", "in", list(set(generated_skus))),
                ]
            )
            for product in external_products:
                issues.append(
                    _(
                        "SKU %(sku)s already belongs to another product: %(product)s.",
                        sku=product.default_code,
                        product=product.product_tmpl_id.name,
                    )
                )
        return list(dict.fromkeys(issues))

    def _mdl_sync_variant_codes(self):
        if self.env.context.get("skip_mdl_catalog_sync"):
            return
        for template in self:
            # Catalog data belongs to the product identity, not to its current
            # archive state.  Keep internal references ready for a native Odoo
            # unarchive and include archived IDs in collision/QA checks.
            products = template.with_context(
                active_test=False
            ).product_variant_ids
            # Refresh names explicitly as part of the same automatic sync.
            # This also makes disabling and re-enabling catalog management
            # deterministic without deleting the saved configuration.
            products._compute_mdl_catalog_values()
            if (
                template.mdl_catalog_managed
                and not template.mdl_copy_requires_new_sku
            ):
                products._mdl_sync_default_code()
            products.invalidate_recordset(["display_name"])

    @api.depends(
        "product_variant_ids.active",
        "product_variant_ids.mdl_catalog_allowed",
        "attribute_line_ids.product_template_value_ids.ptav_active",
        "attribute_line_ids.attribute_id.create_variant",
        "mdl_exclusion_ids.mdl_rule_type",
        "mdl_exclusion_ids.mdl_combination_value_ids",
    )
    def _compute_mdl_variant_overview(self):
        for template in self:
            variants = template.with_context(
                active_test=False
            ).product_variant_ids
            legacy_blocked = variants.filtered(
                lambda product: not product.mdl_catalog_allowed
            )
            variant_lines = (
                template.valid_product_template_attribute_line_ids
                ._without_no_variant_attributes()
            )
            value_sets = [
                line.product_template_value_ids._only_active()
                for line in variant_lines
            ]
            total_combinations = 1
            for values in value_sets:
                total_combinations *= len(values)
            possible_combinations = list(
                template._filter_combinations_impossible_by_config(
                    itertools.product(*value_sets),
                    ignore_no_variant=True,
                )
            )
            blocked_count = max(
                total_combinations - len(possible_combinations),
                len(legacy_blocked),
            )
            active = variants.filtered(
                lambda product: (
                    product.active and product.mdl_catalog_allowed
                )
            )
            archived = variants.filtered(
                lambda product: (
                    not product.active and product.mdl_catalog_allowed
                )
            )
            template.mdl_active_variant_count = len(active)
            template.mdl_archived_variant_count = len(archived)
            template.mdl_blocked_variant_count = blocked_count

    @api.model
    def _mdl_get_model_attribute(self):
        attribute = self.env.ref(
            "mdl_product_groups_attributes.product_attribute_model",
            raise_if_not_found=False,
        )
        if not attribute:
            attribute = self.env["product.attribute"].create(
                {
                    "name": MODEL_ATTRIBUTE_NAME,
                    "sequence": 1,
                    "display_type": "select",
                    "create_variant": "always",
                }
            )
            self.env["ir.model.data"].sudo().create(
                {
                    "module": "mdl_product_groups_attributes",
                    "name": "product_attribute_model",
                    "model": "product.attribute",
                    "res_id": attribute.id,
                    "noupdate": True,
                }
            )
        if (
            attribute.create_variant != "always"
            or attribute.display_type == "multi"
        ):
            raise UserError(
                _(
                    "The module's Model attribute must create variants "
                    "instantly and use a regular selection display."
                )
            )
        return attribute

    def _mdl_model_line_for_conversion(self, fallback_attribute):
        """Return one compatible native model line, if the template has one."""
        self.ensure_one()
        model_lines = self.attribute_line_ids.filtered(
            lambda line: (
                line.mdl_is_model_attribute
                or line.attribute_id == fallback_attribute
                or normalize_token(line.attribute_id.name)
                == normalize_token(MODEL_ATTRIBUTE_NAME)
            )
        )
        if len(model_lines) > 1:
            raise UserError(
                _(
                    "Template %(template)s has multiple Model attribute rows. "
                    "Keep one row before conversion.",
                    template=self.display_name,
                )
            )
        model_line = model_lines[:1]
        if model_line and (
            model_line.attribute_id.create_variant != "always"
            or model_line.attribute_id.display_type == "multi"
        ):
            raise UserError(
                _(
                    "The Model attribute on %(template)s is not configured to "
                    "create variants instantly.",
                    template=self.display_name,
                )
            )
        return model_line

    def _mdl_model_value_for_conversion(self, model_line, derived_name):
        """Select the legacy model from an existing native Model line.

        The line may already contain several legitimate model values.  The
        legacy template name identifies the one value whose old name/SKU
        overrides must be migrated; every value on the line stays untouched.
        """
        self.ensure_one()
        derived_name = clean_text(derived_name)
        if not model_line:
            return self.env["product.attribute.value"]
        if not derived_name and len(model_line.value_ids) == 1:
            return model_line.value_ids
        if not derived_name:
            # A group-only legacy template has no single model component to
            # migrate.  A native multi-value Model line is already complete;
            # keep every value and do not choose an arbitrary PTAV.
            return self.env["product.attribute.value"]
        matches = model_line.value_ids.filtered(
            lambda value: (
                normalize_token(value.name) == normalize_token(derived_name)
            )
        )
        if len(matches) == 1:
            return matches
        available = ", ".join(model_line.value_ids.mapped("name"))
        if not matches:
            raise UserError(
                _(
                    "No value matching model %(model)s was found on the Model "
                    "row of %(template)s. Available values: %(values)s.",
                    template=self.display_name,
                    model=derived_name or "—",
                    values=available or "—",
                )
            )
        raise UserError(
            _(
                "Multiple values on %(template)s match model %(model)s. Make "
                "the value names unique before conversion.",
                template=self.display_name,
                model=derived_name,
            )
        )

    def _mdl_convert_models_to_attributes(self):
        """Move the legacy model component into a normal, ordered attribute.

        When no Model line exists, a single-value line lets Odoo 19 extend the
        existing variants without recreating their IDs.  A pre-existing native
        Model line may already contain several values; it is reused untouched
        and only the value matching the legacy model receives legacy overrides.
        """
        converted = self.env["product.template"]
        default_model_attribute = self._mdl_get_model_attribute()
        Value = self.env["product.attribute.value"]
        Line = self.env["product.template.attribute.line"]
        templates = self.with_context(active_test=False).filtered(
            lambda template: (
                template.mdl_catalog_managed
                and not template.mdl_model_as_attribute
            )
        )

        # Validate and disambiguate every pre-existing model line before
        # touching any template.
        # This produces one clear upgrade error without leaving a mixed state.
        for template in templates:
            model_line = template._mdl_model_line_for_conversion(
                default_model_attribute
            )
            derived_name = _name_without_group(
                template.mdl_group_default_name or template.categ_id.name,
                template.mdl_native_name_source or template.name,
            )
            template._mdl_model_value_for_conversion(
                model_line,
                derived_name,
            )
            lookup_name = derived_name or _resolved_component(
                derived_name,
                template.mdl_model_name_override,
            )
            if not model_line and lookup_name:
                global_matches = Value.with_context(active_test=False).search(
                    [("attribute_id", "=", default_model_attribute.id)]
                ).filtered(
                    lambda value: (
                        normalize_token(value.name)
                        == normalize_token(lookup_name)
                    )
                )
                if len(global_matches) > 1:
                    raise UserError(
                        _(
                            "Multiple global Model values match %(model)s for "
                            "%(template)s. Make the value names unique before conversion.",
                            model=lookup_name,
                            template=template.display_name,
                        )
                    )

        for template in templates:
            archived_product_ids = template.product_variant_ids.filtered(
                lambda product: not product.active
            ).ids
            model_line = template._mdl_model_line_for_conversion(
                default_model_attribute
            )
            model_attribute = (
                model_line.attribute_id
                if model_line
                else default_model_attribute
            )
            group_name = clean_text(
                template.mdl_group_default_name or template.categ_id.name
            )
            group_sku = clean_text(
                template.mdl_group_default_sku
                or template.categ_id.mdl_sku_component
            )
            derived_model_name = _name_without_group(
                group_name,
                template.mdl_native_name_source or template.name,
            )
            existing_model_value = template._mdl_model_value_for_conversion(
                model_line,
                derived_model_name,
            )
            source_model_name = clean_text(
                existing_model_value.name
                if existing_model_value
                else _name_without_group(
                    group_name,
                    template.mdl_native_name_source or template.name,
                )
            )
            effective_model_name = _resolved_component(
                source_model_name,
                template.mdl_model_name_override,
            )
            effective_model_sku = _resolved_component(
                template.mdl_model_sku_component,
                template.mdl_model_sku_override,
            )

            # A template whose native name is only the group has no model.
            # Keep its exact SKU by folding the legacy model code into the
            # group component instead of inventing a duplicate model value.
            if not source_model_name and not effective_model_name:
                effective_group_sku = _resolved_component(
                    group_sku,
                    template.mdl_group_sku_override,
                )
                folded_group_sku = f"{effective_group_sku}{effective_model_sku}"
                if model_line:
                    model_line.with_context(
                        skip_mdl_catalog_sync=True,
                        mdl_preserve_variant_ids=True,
                    ).write({"mdl_is_model_attribute": True})
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {
                        "mdl_catalog_managed": True,
                        "mdl_group_default_name": group_name,
                        "mdl_group_default_sku": folded_group_sku,
                        "mdl_group_sku_override": False,
                        "mdl_model_name_override": "—",
                        "mdl_model_sku_override": "—",
                        "mdl_model_as_attribute": True,
                    }
                )
                template.invalidate_recordset()
                template._mdl_sync_variant_codes()
                self.env["product.product"].browse(
                    archived_product_ids
                ).exists().with_context(skip_mdl_catalog_sync=True).write(
                    {"active": False}
                )
                converted |= template
                continue

            if not source_model_name:
                source_model_name = effective_model_name

            values = Value.with_context(active_test=False).search(
                [("attribute_id", "=", model_attribute.id)]
            )
            matching_values = values.filtered(
                lambda item: (
                    normalize_token(item.name)
                    == normalize_token(source_model_name)
                )
            )
            if not existing_model_value and len(matching_values) > 1:
                raise UserError(
                    _(
                        "Multiple global Model values match %(model)s for %(template)s.",
                        model=source_model_name,
                        template=template.display_name,
                    )
                )
            model_value = (
                existing_model_value
                if existing_model_value
                else matching_values
            )
            if not model_value:
                model_value = Value.with_context(
                    skip_mdl_catalog_sync=True
                ).create(
                    {
                        "name": source_model_name,
                        "attribute_id": model_attribute.id,
                        "sequence": len(values) * 10 + 10,
                        "mdl_sku_component": effective_model_sku or "—",
                    }
                )
            elif not model_value.active:
                model_value.with_context(skip_mdl_catalog_sync=True).write(
                    {"active": True}
                )

            if model_line:
                line_values = {"mdl_is_model_attribute": True}
                if len(model_line.value_ids) == 1:
                    # Preserve legacy single-value conversion semantics.  A
                    # pre-existing multi-value line is already native Odoo
                    # configuration and its line-wide choices stay untouched.
                    line_values.update(
                        {
                            "active": True,
                        }
                    )
                model_line.with_context(
                    skip_mdl_catalog_sync=True,
                    mdl_preserve_variant_ids=True,
                ).write(line_values)
            else:
                existing_sequences = template.attribute_line_ids.mapped(
                    "sequence"
                )
                sequence = min(existing_sequences) - 10 if existing_sequences else 10
                model_line = Line.with_context(
                    skip_mdl_catalog_sync=True,
                    mdl_preserve_variant_ids=True,
                ).create(
                    {
                        "product_tmpl_id": template.id,
                        "attribute_id": model_attribute.id,
                        "sequence": sequence,
                        "value_ids": [Command.set(model_value.ids)],
                        "mdl_is_model_attribute": True,
                    }
                )

            template_value = model_line.product_template_value_ids.filtered(
                lambda item: item.product_attribute_value_id == model_value
            )[:1]
            template_value.with_context(skip_mdl_catalog_sync=True).write(
                {
                    "mdl_name_component_override": (
                        _override_from_effective_value(
                            model_value.name,
                            effective_model_name,
                        )
                    ),
                    "mdl_sku_component_override": (
                        _override_from_effective_value(
                            model_value.mdl_sku_component,
                            effective_model_sku,
                        )
                    ),
                }
            )
            template.with_context(skip_mdl_catalog_sync=True).write(
                {
                    "mdl_catalog_managed": True,
                    "mdl_group_default_name": group_name,
                    "mdl_group_default_sku": group_sku,
                    "mdl_model_name_override": "—",
                    "mdl_model_sku_override": "—",
                    "mdl_model_as_attribute": True,
                }
            )
            template.invalidate_recordset()
            template._mdl_ensure_full_model_names()
            template._mdl_sync_variant_codes()
            self.env["product.product"].browse(
                archived_product_ids
            ).exists().with_context(skip_mdl_catalog_sync=True).write(
                {"active": False}
            )
            converted |= template
        return converted

    def action_mdl_convert_model_to_attribute(self):
        converted = self._mdl_convert_models_to_attributes()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Model Conversion Complete"),
                "message": _(
                    "Model was converted to a regular attribute in %(count)s groups.",
                    count=len(converted),
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _create_variant_ids(self):
        if self.env.context.get("mdl_defer_variant_rebuild"):
            return True
        result = super()._create_variant_ids()
        pending_copies = self.filtered("mdl_copy_requires_new_sku")
        pending_copies.with_context(
            active_test=False
        ).product_variant_ids.filtered("default_code").with_context(
            skip_mdl_catalog_sync=True
        ).write({"default_code": False})
        disallowed = self.with_context(
            active_test=False
        ).product_variant_ids.filtered(
            lambda product: not product.mdl_catalog_allowed
        )
        disallowed.filtered("active").with_context(
            skip_mdl_catalog_sync=True
        ).write({"active": False})
        return result

    def _mdl_catalog_rule_sets(self):
        self.ensure_one()
        rules = self.mdl_exclusion_ids.filtered("mdl_is_catalog_condition")
        forbidden = [
            frozenset(rule.mdl_combination_value_ids.ids)
            for rule in rules.filtered(
                lambda item: (
                    item.mdl_rule_type == "forbidden"
                    and len(item.mdl_combination_value_ids) >= 2
                )
            )
        ]
        allowed = [
            frozenset(rule.mdl_combination_value_ids.ids)
            for rule in rules.filtered(
                lambda item: (
                    item.mdl_rule_type == "allowed"
                    and len(item.mdl_combination_value_ids) >= 2
                )
            )
        ]
        return forbidden, allowed

    def _filter_combinations_impossible_by_config(
        self,
        combination_tuples,
        ignore_no_variant=False,
    ):
        """Apply MDL rules that may contain more than Odoo's native pair."""
        self.ensure_one()
        forbidden, allowed = self._mdl_catalog_rule_sets()
        possible = super()._filter_combinations_impossible_by_config(
            combination_tuples,
            ignore_no_variant=ignore_no_variant,
        )
        for combination in possible:
            combination_ids = frozenset(combination.ids)
            if any(rule <= combination_ids for rule in forbidden):
                continue
            if allowed and not any(rule <= combination_ids for rule in allowed):
                continue
            yield combination

    def _get_attribute_exclusions(
        self,
        parent_combination=None,
        parent_name=None,
        combination_ids=None,
    ):
        """Expose n-ary and allow-list rules to Odoo's native configurator."""
        result = super()._get_attribute_exclusions(
            parent_combination=parent_combination,
            parent_name=parent_name,
            combination_ids=combination_ids,
        )
        self.ensure_one()
        forbidden, allowed = self._mdl_catalog_rule_sets()
        custom_forbidden = [rule for rule in forbidden if len(rule) > 2]
        if not custom_forbidden and not allowed:
            return result

        selected_ids = set(combination_ids or [])
        lines = (
            self.valid_product_template_attribute_line_ids
            ._without_no_variant_attributes()
        )
        value_sets = [
            line.product_template_value_ids.filtered(
                lambda value: value.ptav_active or value.id in selected_ids
            )
            for line in lines
        ]
        custom_archived = []
        for combination_tuple in itertools.product(*value_sets):
            combination = self.env[
                "product.template.attribute.value"
            ].concat(*combination_tuple)
            combination_set = frozenset(combination.ids)
            if any(rule <= combination_set for rule in custom_forbidden) or (
                allowed
                and not any(rule <= combination_set for rule in allowed)
            ):
                custom_archived.append(tuple(combination.ids))
        result["archived_combinations"] = list(
            dict.fromkeys(
                list(result.get("archived_combinations", []))
                + custom_archived
            )
        )
        return result

    def action_mdl_check_and_rebuild(self):
        self.ensure_one()
        self._create_variant_ids()
        self.invalidate_recordset()
        issues = self._mdl_get_catalog_issues(include_sync_state=False)
        if issues:
            raise UserError(
                _(
                    "Products cannot be updated until these issues are fixed:\n%s",
                    "\n".join(f"• {issue}" for issue in issues),
                )
            )
        self._mdl_sync_variant_codes()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Update Complete"),
                "message": _(
                    "%(count)s products were updated in the group.",
                    count=len(self.product_variant_ids),
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _mdl_variant_action(self, title, extra_domain=None):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "product.product_variant_action"
        )
        normal_form = self.env.ref("product.product_normal_form_view")
        action["name"] = title
        action["views"] = [
            (view_id, view_type)
            for view_id, view_type in action.get("views", [])
            if view_type != "form"
        ] + [(normal_form.id, "form")]
        action["domain"] = [
            ("product_tmpl_id", "=", self.id),
            *(extra_domain or []),
        ]
        action["context"] = {
            "active_test": False,
            "default_product_tmpl_id": self.id,
            "search_default_product_tmpl_id": self.id,
            "form_view_ref": "product.product_normal_form_view",
        }
        return action

    def action_mdl_open_active_variants(self):
        return self._mdl_variant_action(
            "Active Products",
            [("active", "=", True), ("mdl_catalog_allowed", "=", True)],
        )

    def action_mdl_open_archived_variants(self):
        return self._mdl_variant_action(
            "Archived Products",
            [("active", "=", False), ("mdl_catalog_allowed", "=", True)],
        )

    def action_mdl_open_blocked_rules(self):
        self.ensure_one()
        previews = self.env["mdl.blocked.variant.preview"]._prepare_for_template(
            self
        )
        list_view = self.env.ref(
            "mdl_product_groups_attributes.mdl_blocked_variant_preview_list_view"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Blocked Products"),
            "res_model": "mdl.blocked.variant.preview",
            "view_mode": "list",
            "views": [(list_view.id, "list")],
            "domain": [("id", "in", previews.ids)],
            "context": {
                "create": False,
                "edit": False,
                "delete": False,
            },
        }

    def action_mdl_open_variants(self):
        return self._mdl_variant_action(_("Group Products"))

    @api.depends("name", "default_code", "mdl_catalog_managed")
    @api.depends_context("display_default_code", "lang")
    def _compute_display_name(self):
        super()._compute_display_name()
        for template in self.filtered("mdl_catalog_managed"):
            # A template is the product group, not one final variant.  Odoo's
            # native related default_code can mirror the sole variant and must
            # therefore never leak into the group title.
            template.display_name = template.name

    @api.model
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        results = super().name_search(name, domain, operator, limit)
        positive_operators = {"=", "ilike", "=ilike", "like", "=like"}
        if not name or operator not in positive_operators:
            return results
        existing_ids = [record_id for record_id, _display_name in results]
        remaining = None if not limit else max(limit - len(results), 0)
        if remaining == 0:
            return results
        variant_domain = Domain.OR(
            [
                Domain("default_code", operator, name),
                Domain("mdl_effective_name", operator, name),
            ]
        )
        extra_domain = Domain(domain or Domain.TRUE)
        extra_domain &= Domain.OR(
            [
                Domain("mdl_sku_prefix", operator, name),
                Domain("product_variant_ids", "any", variant_domain),
            ]
        )
        if existing_ids:
            extra_domain &= Domain("id", "not in", existing_ids)
        extra_templates = self.search(extra_domain, limit=remaining)
        return results + [
            (template.id, template.display_name) for template in extra_templates
        ]
