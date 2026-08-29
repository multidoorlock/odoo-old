from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError


DEFER_VARIANT_REBUILD_CONTEXT_KEY = "mdl_defer_variant_rebuild"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _create_variant_ids(self):
        """Let exclusion updates make their native and MDL state atomic."""
        if self.env.context.get(DEFER_VARIANT_REBUILD_CONTEXT_KEY):
            return True
        return super()._create_variant_ids()


class ProductTemplateAttributeExclusion(models.Model):
    _inherit = "product.template.attribute.exclusion"

    mdl_is_catalog_condition = fields.Boolean(
        string="תנאי קטלוג",
        default=False,
        index=True,
    )
    mdl_rule_type = fields.Selection(
        selection=[
            ("forbidden", "שילוב אסור"),
            ("allowed", "שילוב מותר"),
        ],
        string="סוג כלל",
        default="forbidden",
        required=True,
        help=(
            "שילוב אסור חוסם כל פריט שמכיל את כל הערכים שנבחרו. אם קיימים "
            "כללי שילוב מותר, רק פריטים שמתאימים לפחות לאחד מהם יהיו זמינים."
        ),
    )
    mdl_combination_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        relation="mdl_product_exclusion_combination_rel",
        column1="exclusion_id",
        column2="ptav_id",
        string="ערכי הכלל",
        help=(
            "בחר שני ערכים או יותר ממאפיינים שונים. ניתן ליצור גם תנאי "
            "שתלוי בדגם ובכמה מאפיינים יחד."
        ),
    )

    @api.constrains(
        "mdl_is_catalog_condition",
        "mdl_combination_value_ids",
        "mdl_rule_type",
        "product_tmpl_id",
    )
    def _check_mdl_combination_values(self):
        for rule in self.filtered("mdl_is_catalog_condition"):
            values = rule.mdl_combination_value_ids
            if len(values) < 2:
                raise ValidationError(
                    "בכל כלל שילוב יש לבחור לפחות שני ערכים."
                )
            if any(value.product_tmpl_id != rule.product_tmpl_id for value in values):
                raise ValidationError(
                    "ניתן לבחור רק ערכים השייכים לקבוצה הנוכחית."
                )
            if any(
                value.attribute_id.create_variant == "no_variant"
                for value in values
            ):
                raise ValidationError(
                    "לא ניתן להשתמש בכלל שילוב בערך של מאפיין שאינו יוצר "
                    "וריאנטים."
                )
            if len(values.attribute_id) != len(values):
                raise ValidationError(
                    "בכל כלל ניתן לבחור ערך אחד בלבד מכל מאפיין."
                )
            uses_custom_rule_engine = (
                rule.mdl_rule_type == "allowed" or len(values) > 2
            )
            has_no_variant_line = any(
                line.attribute_id.create_variant == "no_variant"
                for line in rule.product_tmpl_id.attribute_line_ids
            )
            if uses_custom_rule_engine and has_no_variant_line:
                raise ValidationError(
                    "כלל מותר או כלל של שלושה ערכים ומעלה אינו נתמך "
                    "בקבוצה שיש בה מאפיין שאינו יוצר וריאנטים."
                )
            if uses_custom_rule_engine and rule.product_tmpl_id.has_dynamic_attributes():
                raise ValidationError(
                    "כלל מותר או כלל של שלושה ערכים ומעלה דורש שמאפייני "
                    "הקבוצה ייצרו וריאנטים באופן מיידי."
                )

    @staticmethod
    def _mdl_value_sort_key(value):
        return (value.attribute_line_id.id, value.id)

    def _mdl_sync_native_from_combination(self):
        for rule in self:
            values = rule.mdl_combination_value_ids.sorted(
                self._mdl_value_sort_key
            )
            if (
                not rule.mdl_is_catalog_condition
                or rule.mdl_rule_type != "forbidden"
                or len(values) != 2
            ):
                rule.with_context(mdl_skip_combination_sync=True).write(
                    {
                        "product_template_attribute_value_id": False,
                        "value_ids": [Command.clear()],
                    }
                )
                continue
            source, target = values
            rule.with_context(mdl_skip_combination_sync=True).write(
                {
                    "mdl_is_catalog_condition": True,
                    "mdl_rule_type": "forbidden",
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
            native_targets = rule.value_ids
            targets = native_targets.filtered(
                lambda target: (
                    target.product_tmpl_id == template
                    and target.attribute_id != source.attribute_id
                )
            ).sorted(self._mdl_value_sort_key)
            if set(targets.ids) != set(native_targets.ids):
                # Native Odoo exclusions can also target values belonging to
                # optional or accessory products.  A mixed local/external rule
                # must remain entirely native: partially normalizing it would
                # silently discard the external part of the rule.
                if rule.mdl_is_catalog_condition:
                    rule.with_context(mdl_skip_combination_sync=True).write(
                        {
                            "mdl_is_catalog_condition": False,
                            "mdl_combination_value_ids": [Command.clear()],
                        }
                    )
                continue
            if not targets:
                continue

            first_target = targets[:1]
            rule.with_context(mdl_skip_combination_sync=True).write(
                {
                    "mdl_is_catalog_condition": True,
                    "mdl_rule_type": "forbidden",
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
                    "mdl_rule_type": "forbidden",
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

    def _mdl_merge_duplicate_rules(self, protected_rules=None):
        """Keep one row when the same unordered rule was entered twice.

        Records returned by a multi-create are protected.  Deleting one of
        them before ``create()`` returns violates Odoo's create contract and
        leaves callers holding a non-existing record.  Existing duplicates
        and helper rows made while expanding native exclusions can still be
        folded safely; two equivalent rows submitted in the *same* batch stay
        separate and can be edited normally.
        """
        if self.env.context.get("mdl_skip_combination_sync"):
            return

        Exclusion = self.env["product.template.attribute.exclusion"]
        protected_ids = set(protected_rules.ids) if protected_rules else set()
        for rule_id in self.ids:
            keeper = Exclusion.browse(rule_id).exists()
            if not keeper or not keeper.mdl_is_catalog_condition:
                continue
            combination = frozenset(keeper.mdl_combination_value_ids.ids)
            if len(combination) < 2:
                continue
            candidates = Exclusion.search(
                [
                    ("product_tmpl_id", "=", keeper.product_tmpl_id.id),
                    ("mdl_is_catalog_condition", "=", True),
                    ("mdl_rule_type", "=", keeper.mdl_rule_type),
                    ("id", "!=", keeper.id),
                ]
            )
            duplicates = candidates.filtered(
                lambda other: (
                    other.id not in protected_ids
                    and frozenset(other.mdl_combination_value_ids.ids)
                    == combination
                )
            )
            if duplicates:
                duplicates.with_context(mdl_skip_combination_sync=True).unlink()

    @api.model_create_multi
    def create(self, vals_list):
        deferred_self = self.with_context(
            **{DEFER_VARIANT_REBUILD_CONTEXT_KEY: True}
        )
        rules = super(
            ProductTemplateAttributeExclusion,
            deferred_self,
        ).create(vals_list)
        if self.env.context.get("mdl_skip_combination_sync"):
            return rules

        templates = rules.product_tmpl_id
        combination_rules = rules.filtered("mdl_combination_value_ids")
        combination_rules._mdl_sync_native_from_combination()
        native_rules = rules - combination_rules
        normalized_rules = native_rules._mdl_expand_native_rules()
        (combination_rules | normalized_rules)._mdl_merge_duplicate_rules(
            protected_rules=rules,
        )
        if not self.env.context.get(DEFER_VARIANT_REBUILD_CONTEXT_KEY):
            templates.with_context(
                **{DEFER_VARIANT_REBUILD_CONTEXT_KEY: False}
            )._create_variant_ids()
        return rules.with_env(self.env)

    def write(self, vals):
        templates = self.product_tmpl_id
        deferred_self = self.with_context(
            **{DEFER_VARIANT_REBUILD_CONTEXT_KEY: True}
        )
        result = super(
            ProductTemplateAttributeExclusion,
            deferred_self,
        ).write(vals)
        if self.env.context.get("mdl_skip_combination_sync"):
            return result

        rules = deferred_self
        templates |= rules.product_tmpl_id
        if {
            "mdl_combination_value_ids",
            "mdl_rule_type",
            "mdl_is_catalog_condition",
        } & vals.keys():
            rules._mdl_sync_native_from_combination()
            normalized_rules = rules
        elif {
            "product_tmpl_id",
            "product_template_attribute_value_id",
            "value_ids",
        } & vals.keys():
            normalized_rules = rules._mdl_expand_native_rules()
        else:
            normalized_rules = rules
        normalized_rules._mdl_merge_duplicate_rules()
        if not self.env.context.get(DEFER_VARIANT_REBUILD_CONTEXT_KEY):
            templates.with_context(
                **{DEFER_VARIANT_REBUILD_CONTEXT_KEY: False}
            )._create_variant_ids()
        return result
