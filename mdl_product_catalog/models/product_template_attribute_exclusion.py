from odoo import Command, api, fields, models


class ProductTemplateAttributeExclusion(models.Model):
    _inherit = "product.template.attribute.exclusion"

    mdl_source_attribute_id = fields.Many2one(
        comodel_name="product.attribute",
        related="product_template_attribute_value_id.attribute_id",
        string="מאפיין מקור",
        readonly=True,
    )

    def _mdl_merge_duplicate_pairs(self):
        """Keep each local incompatible pair in one rule only.

        Odoo already applies exclusions symmetrically, so A -> B and B -> A
        are the same condition.  Keep the rule the user just edited and
        remove only the duplicated pair from other rules.
        """
        if self.env.context.get("mdl_skip_exclusion_dedup"):
            return

        Exclusion = self.env["product.template.attribute.exclusion"]
        for rule_id in self.ids:
            keeper = Exclusion.browse(rule_id).exists()
            if not keeper:
                continue
            source = keeper.product_template_attribute_value_id
            template = keeper.product_tmpl_id
            if not source or source.product_tmpl_id != template:
                continue

            local_targets = keeper.value_ids.filtered(
                lambda target: target.product_tmpl_id == template
            )
            if not local_targets:
                continue

            other_rules = Exclusion.search(
                [
                    ("product_tmpl_id", "=", template.id),
                    ("id", "!=", keeper.id),
                ]
            )
            for target in local_targets:
                for other in other_rules.exists():
                    other_source = other.product_template_attribute_value_id
                    value_to_remove = self.env[
                        "product.template.attribute.value"
                    ]
                    if other_source == source and target in other.value_ids:
                        value_to_remove = target
                    elif other_source == target and source in other.value_ids:
                        value_to_remove = source
                    if not value_to_remove:
                        continue

                    remaining_values = other.value_ids - value_to_remove
                    other = other.with_context(mdl_skip_exclusion_dedup=True)
                    if remaining_values:
                        other.write(
                            {"value_ids": [Command.set(remaining_values.ids)]}
                        )
                    else:
                        other.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._mdl_merge_duplicate_pairs()
        return rules

    def write(self, vals):
        result = super().write(vals)
        if {
            "product_tmpl_id",
            "product_template_attribute_value_id",
            "value_ids",
        } & vals.keys():
            self._mdl_merge_duplicate_pairs()
        return result
