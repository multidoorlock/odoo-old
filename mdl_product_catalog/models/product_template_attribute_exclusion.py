from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplateAttributeExclusion(models.Model):
    _inherit = "product.template.attribute.exclusion"

    mdl_is_catalog_condition = fields.Boolean(
        string="תנאי קטלוג",
        default=False,
        index=True,
    )
    mdl_combination_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        relation="mdl_product_exclusion_combination_rel",
        column1="exclusion_id",
        column2="ptav_id",
        string="שילוב אסור",
        help="בחר בדיוק שני ערכים שלא ניתן לשלב יחד.",
    )

    @api.constrains(
        "mdl_is_catalog_condition",
        "mdl_combination_value_ids",
        "product_tmpl_id",
    )
    def _check_mdl_combination_values(self):
        for rule in self.filtered("mdl_is_catalog_condition"):
            values = rule.mdl_combination_value_ids
            if len(values) != 2:
                raise ValidationError(
                    "בכל שורת שילוב אסור יש לבחור בדיוק שני ערכים."
                )
            if any(value.product_tmpl_id != rule.product_tmpl_id for value in values):
                raise ValidationError(
                    "ניתן לבחור רק ערכים השייכים לדגם הנוכחי."
                )
            if len(values.attribute_id) != 2:
                raise ValidationError(
                    "שילוב אסור חייב לכלול ערכים משני מאפיינים שונים."
                )

    @staticmethod
    def _mdl_value_sort_key(value):
        return (value.attribute_line_id.id, value.id)

    def _mdl_sync_native_from_combination(self):
        for rule in self:
            values = rule.mdl_combination_value_ids.sorted(
                self._mdl_value_sort_key
            )
            if len(values) != 2:
                continue
            source, target = values
            rule.with_context(mdl_skip_combination_sync=True).write(
                {
                    "mdl_is_catalog_condition": True,
                    "product_template_attribute_value_id": source.id,
                    "value_ids": [Command.set(target.ids)],
                }
            )

    def _mdl_expand_native_rules(self):
        """Represent each local native exclusion pair as one catalog row."""
        Exclusion = self.env["product.template.attribute.exclusion"]
        normalized = Exclusion

        for rule_id in self.ids:
            rule = Exclusion.browse(rule_id).exists()
            if not rule:
                continue
            source = rule.product_template_attribute_value_id
            template = rule.product_tmpl_id
            if not source or source.product_tmpl_id != template:
                continue
            targets = rule.value_ids.filtered(
                lambda target: (
                    target.product_tmpl_id == template
                    and target.attribute_id != source.attribute_id
                )
            ).sorted(self._mdl_value_sort_key)
            if not targets:
                continue

            first_target = targets[:1]
            rule.with_context(mdl_skip_combination_sync=True).write(
                {
                    "mdl_is_catalog_condition": True,
                    "mdl_combination_value_ids": [
                        Command.set((source | first_target).ids)
                    ],
                    "value_ids": [Command.set(first_target.ids)],
                }
            )
            normalized |= rule

            extra_values = [
                {
                    "product_tmpl_id": template.id,
                    "product_template_attribute_value_id": source.id,
                    "value_ids": [Command.set(target.ids)],
                    "mdl_is_catalog_condition": True,
                    "mdl_combination_value_ids": [
                        Command.set((source | target).ids)
                    ],
                }
                for target in targets[1:]
            ]
            if extra_values:
                normalized |= Exclusion.with_context(
                    mdl_skip_combination_sync=True
                ).create(extra_values)

        return normalized

    def _mdl_merge_duplicate_pairs(self):
        """Keep one row when the same unordered pair was entered twice."""
        if self.env.context.get("mdl_skip_combination_sync"):
            return

        Exclusion = self.env["product.template.attribute.exclusion"]
        for rule_id in self.ids:
            keeper = Exclusion.browse(rule_id).exists()
            if not keeper or not keeper.mdl_is_catalog_condition:
                continue
            pair = frozenset(keeper.mdl_combination_value_ids.ids)
            if len(pair) != 2:
                continue
            candidates = Exclusion.search(
                [
                    ("product_tmpl_id", "=", keeper.product_tmpl_id.id),
                    ("mdl_is_catalog_condition", "=", True),
                    ("id", "!=", keeper.id),
                ]
            )
            duplicates = candidates.filtered(
                lambda other: (
                    frozenset(other.mdl_combination_value_ids.ids) == pair
                )
            )
            if duplicates:
                duplicates.with_context(mdl_skip_combination_sync=True).unlink()

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        if self.env.context.get("mdl_skip_combination_sync"):
            return rules

        combination_rules = rules.filtered("mdl_combination_value_ids")
        combination_rules._mdl_sync_native_from_combination()
        native_rules = rules - combination_rules
        normalized_rules = native_rules._mdl_expand_native_rules()
        (combination_rules | normalized_rules)._mdl_merge_duplicate_pairs()
        return rules

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("mdl_skip_combination_sync"):
            return result

        if "mdl_combination_value_ids" in vals:
            self._mdl_sync_native_from_combination()
            normalized_rules = self
        elif {
            "product_tmpl_id",
            "product_template_attribute_value_id",
            "value_ids",
        } & vals.keys():
            normalized_rules = self._mdl_expand_native_rules()
        else:
            normalized_rules = self
        normalized_rules._mdl_merge_duplicate_pairs()
        return result
