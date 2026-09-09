from odoo import api, fields, models


class MdlBlockedVariantPreview(models.TransientModel):
    _name = "mdl.blocked.variant.preview"
    _description = "Blocked Final Product Preview"
    _order = "final_sku, final_name, id"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product Group",
        required=True,
        readonly=True,
        index=True,
    )
    final_sku = fields.Char(
        string="Final SKU",
        readonly=True,
    )
    final_name = fields.Char(
        string="Final Product Name",
        readonly=True,
    )
    attribute_values = fields.Char(
        string="Attribute Values",
        readonly=True,
    )

    @api.model
    def _prepare_for_template(self, template):
        template.ensure_one()
        self.search(
            [
                ("create_uid", "=", self.env.uid),
                ("product_tmpl_id", "=", template.id),
            ]
        ).unlink()

        variant_lines = (
            template.valid_product_template_attribute_line_ids
            ._without_no_variant_attributes()
        )
        value_sets = [
            line.product_template_value_ids._only_active()
            for line in variant_lines
        ]
        rows = []
        seen_combinations = set()
        if value_sets and all(value_sets):
            import itertools

            for values in itertools.product(*value_sets):
                combination = self.env["product.template.attribute.value"]
                for value in values:
                    combination |= value
                if template._is_combination_possible_by_config(
                    combination,
                    ignore_no_variant=True,
                ):
                    continue
                key = frozenset(combination.ids)
                seen_combinations.add(key)
                final_sku, final_name, _missing = (
                    template._mdl_render_catalog_values(combination)
                )
                rows.append(
                    {
                        "product_tmpl_id": template.id,
                        "final_sku": final_sku or False,
                        "final_name": final_name or False,
                        "attribute_values": " | ".join(
                            f"{value.attribute_id.name}: "
                            f"{value.product_attribute_value_id.name}"
                            for value in combination.sorted(
                                lambda item: (
                                    item.attribute_line_id.sequence,
                                    item.attribute_id.sequence,
                                    item.id,
                                )
                            )
                        ),
                    }
                )

        # Preserve visibility of blocked records migrated from the legacy
        # catalog even when no current native exclusion represents them.
        legacy_blocked = template.with_context(
            active_test=False
        ).product_variant_ids.filtered(
            lambda product: not product.mdl_catalog_allowed
        )
        for product in legacy_blocked:
            combination = product.product_template_attribute_value_ids
            key = frozenset(combination.ids)
            if key in seen_combinations:
                continue
            final_sku, final_name, _missing = (
                template._mdl_render_catalog_values(combination)
            )
            rows.append(
                {
                    "product_tmpl_id": template.id,
                    "final_sku": final_sku or product.default_code or False,
                    "final_name": final_name or product.mdl_generated_name or False,
                    "attribute_values": " | ".join(
                        f"{value.attribute_id.name}: "
                        f"{value.product_attribute_value_id.name}"
                        for value in combination.sorted(
                            lambda item: (
                                item.attribute_line_id.sequence,
                                item.attribute_id.sequence,
                                item.id,
                            )
                        )
                    ),
                }
            )
        return self.create(rows)

