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
    override_value = clean_text(override_value)
    if override_value == "—":
        return ""
    return override_value or clean_text(default_value)


def _override_from_effective_value(default_value, effective_value):
    """Store only a real deviation from the source value.

    An empty effective value is an intentional omission and is represented by
    an em dash internally.  This keeps an empty override available to mean
    "inherit from the source" while the user works with one effective field.
    """
    default_value = clean_text(default_value)
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
        string="מק״ט בסיס",
        compute="_compute_mdl_sku_prefix",
        inverse="_inverse_mdl_sku_prefix",
        store=True,
        index=True,
        copy=False,
        help=(
            "מחושב מרכיב המק״ט של קבוצת הפריטים. ערכי המאפיינים, לרבות "
            "דגם, מתווספים לפי סדר שורות המאפיינים. "
            "המק״ט הסופי נשמר בשדה המקורי 'מק״ט פנימי' של הווריאנט."
        ),
    )
    mdl_catalog_managed = fields.Boolean(
        string="מנוהל כקבוצת פריטים",
        default=False,
        index=True,
        copy=True,
        help=(
            "שדה טכני שמפריד בין עצם ניהול הקבוצה לבין תוכן מק״ט הבסיס. "
            "כך גם קבוצה שמקבלת את כל המק״ט מערכי המאפיינים נשארת מנוהלת."
        ),
    )
    mdl_group_default_name = fields.Char(
        string="שם המקור של קבוצת הפריטים",
        index=True,
        help=(
            "שם הבסיס המשותף לפריטים בקבוצה. השדה נפרד מקטגוריית המוצר "
            "כדי שניתן יהיה לשנות קטגוריה בלי לשנות שמות פריטים."
        ),
    )
    mdl_group_default_sku = fields.Char(
        string="מק״ט בסיס לקבוצה",
        index=True,
        help="רכיב המק״ט המשותף שמופיע לפני רכיבי ערכי המאפיינים.",
    )
    mdl_group_name_override = fields.Char(
        string="שינוי טקסט לקבוצה",
        help="אופציונלי לקבוצה זו בלבד. הזן — כדי לא להציג את הבסיס בשם.",
    )
    mdl_group_sku_override = fields.Char(
        string="שינוי מק״ט לקבוצה",
        help="אופציונלי לקבוצה זו בלבד. הזן — כדי לא להוסיף את רכיב הקבוצה.",
    )
    mdl_model_default_name = fields.Char(
        string="טקסט ברירת מחדל לדגם",
        compute="_compute_mdl_model_default_name",
        inverse="_inverse_mdl_model_default_name",
        help="שם הדגם ללא שם קבוצת הפריטים.",
    )
    mdl_model_sku_component = fields.Char(
        string="מק״ט ברירת מחדל לדגם",
        index=True,
        help="רכיב המק״ט הבסיסי של הדגם.",
    )
    mdl_model_name_override = fields.Char(
        string="שינוי טקסט לדגם",
        help="אופציונלי. הזן — כדי לא להציג את הדגם בשם הפריט.",
    )
    mdl_model_sku_override = fields.Char(
        string="שינוי מק״ט לדגם",
        help="אופציונלי. הזן — כדי לא להוסיף את רכיב הדגם למק״ט.",
    )
    mdl_group_name_value = fields.Char(
        string="שם קבוצת פריטים",
        compute="_compute_mdl_group_name_value",
        inverse="_inverse_mdl_group_name_value",
        help=(
            "מציג את שם הקבוצה שבפועל ייכנס לשם הפריט. עריכה יוצרת שינוי "
            "לקבוצה הזו בלבד; איפוס מחזיר לשם קבוצת הפריטים."
        ),
    )
    mdl_group_sku_value = fields.Char(
        string="מק״ט קבוצת פריטים",
        compute="_compute_mdl_group_sku_value",
        inverse="_inverse_mdl_group_sku_value",
        help=(
            "מציג את רכיב המק״ט הקבוצתי שבפועל. עריכה יוצרת שינוי לקבוצה "
            "הזו בלבד; איפוס מחזיר למק״ט הבסיס של הקבוצה."
        ),
    )
    mdl_model_name_value = fields.Char(
        string="שם הדגם",
        compute="_compute_mdl_model_name_value",
        inverse="_inverse_mdl_model_name_value",
        help=(
            "מציג את שם הדגם שבפועל ללא שם הקבוצה. עריכה יוצרת שינוי "
            "לדגם הזה בלבד; איפוס מחזיר לשם המקור של הדגם."
        ),
    )
    mdl_model_sku_value = fields.Char(
        string="מק״ט הדגם",
        compute="_compute_mdl_model_sku_value",
        inverse="_inverse_mdl_model_sku_value",
        help=(
            "מציג את רכיב המק״ט של הדגם שבפועל. עריכה יוצרת שינוי לדגם "
            "הזה בלבד; איפוס מחזיר לרכיב המקור."
        ),
    )
    mdl_effective_base_name = fields.Char(
        string="שם בסיס",
        compute="_compute_mdl_effective_base_name",
        inverse="_inverse_mdl_effective_base_name",
        store=True,
        help=(
            "שם הבסיס של הפריט לפני המאפיינים. כברירת מחדל הוא מחובר "
            "משם קבוצת הפריטים. דגם מנוהל כערך מאפיין רגיל וניתן לסידור."
        ),
    )
    mdl_model_as_attribute = fields.Boolean(
        string="דגם מנוהל כמאפיין",
        default=False,
        copy=True,
        help=(
            "שדה תאימות טכני המציין שהדגם הישן הועבר לערך מאפיין רגיל."
        ),
    )
    mdl_native_name_override = fields.Char(
        string="שם תבנית Odoo מותאם",
        copy=False,
        help=(
            "שדה טכני ששומר שם תבנית שנבחר במפורש דרך פעולת Odoo, "
            "למשל בעת העתקה עם שם מותאם."
        ),
    )
    mdl_model_value_summary = fields.Char(
        string="דגמים",
        compute="_compute_mdl_model_value_summary",
        help="ערכי מאפיין הדגם המשויכים לקבוצת הפריטים.",
    )
    mdl_attribute_value_ids = fields.One2many(
        comodel_name="product.template.attribute.value",
        inverse_name="product_tmpl_id",
        string="ערכי מאפיינים בקבוצה",
    )
    mdl_exclusion_ids = fields.One2many(
        comodel_name="product.template.attribute.exclusion",
        inverse_name="product_tmpl_id",
        string="כללי שילובים",
        help=(
            "כל שורה מגדירה שילוב מותר או אסור של שני ערכים או יותר. "
            "הכלל יכול להיות תלוי בדגם ובכמה מאפיינים יחד."
        ),
    )
    mdl_active_variant_count = fields.Integer(
        string="פריטים פעילים",
        compute="_compute_mdl_variant_overview",
    )
    mdl_archived_variant_count = fields.Integer(
        string="פריטים בארכיון",
        compute="_compute_mdl_variant_overview",
    )
    mdl_blocked_variant_count = fields.Integer(
        string="שילובים חסומים",
        compute="_compute_mdl_variant_overview",
    )
    mdl_variant_preview = fields.Text(
        string="דוגמאות לפריטים",
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
    # ordered attribute rows and their single "טקסט אחרי" field.
    mdl_variant_base_name = fields.Char(
        string="שם בסיס ישן (לא בשימוש)",
        copy=True,
    )
    mdl_name_suffix = fields.Char(
        string="טקסט סופי של הפורמט (טכני)",
        copy=True,
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
    )
    def _compute_mdl_effective_base_name(self):
        for template in self:
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
        self._mdl_sync_variant_codes()

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for template, vals in zip(self, vals_list):
            if not template.mdl_catalog_managed:
                continue
            if (
                "name" in default
                and "mdl_native_name_override" not in default
            ):
                vals["mdl_native_name_override"] = clean_text(
                    default["name"]
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
        return vals_list

    def copy(self, default=None):
        default = dict(default or {})
        copied = super().copy(default=default)
        for source_template, copied_template in zip(self, copied):
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
                    raise UserError(
                        _(
                            "לא ניתן להעתיק את קבוצת הפריטים %(template)s: "
                            "ערך מאפיין לא הועתק על ידי Odoo.",
                            template=source_template.display_name,
                        )
                    )
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
                    raise UserError(
                        _(
                            "לא ניתן להעתיק כלל שילוב בקבוצה %(template)s.",
                            template=source_template.display_name,
                        )
                    )
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
            copied_template._mdl_ensure_full_model_names()
            copied_template._mdl_sync_variant_codes()
        return copied

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            category = self.env["product.category"].browse(
                vals.get("categ_id")
            ).exists()
            is_catalog_values = any(
                field_name in vals
                for field_name in (
                    "mdl_group_default_name",
                    "mdl_group_default_sku",
                    "mdl_model_sku_component",
                    "mdl_group_sku_override",
                    "mdl_model_sku_override",
                )
            )
            if is_catalog_values or (category and category.mdl_sku_component):
                vals.setdefault("mdl_catalog_managed", True)
            if category and (category.mdl_sku_component or is_catalog_values):
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
            ):
                if field_name in vals:
                    vals[field_name] = clean_text(vals[field_name])
        templates = super().create(vals_list)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        return templates

    def write(self, vals):
        vals = dict(vals)
        if "mdl_native_name_override" not in vals:
            if "name" in vals and not self.env.context.get(
                "skip_mdl_catalog_sync"
            ):
                vals["mdl_native_name_override"] = clean_text(vals["name"])
            elif "mdl_group_default_name" in vals:
                vals["mdl_native_name_override"] = False
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
        ):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        if any(
            field_name in vals
            for field_name in (
                "mdl_group_default_name",
                "mdl_group_default_sku",
                "mdl_group_name_override",
                "mdl_group_sku_override",
                "mdl_model_sku_component",
                "mdl_model_name_override",
                "mdl_model_sku_override",
            )
        ):
            vals.setdefault("mdl_catalog_managed", True)
        result = super().write(vals)
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
                "mdl_model_name_override": (
                    "—" if self.mdl_model_as_attribute else False
                ),
                "mdl_model_sku_override": (
                    "—" if self.mdl_model_as_attribute else False
                ),
            }
        )

    def action_mdl_reset_base_name(self):
        self.ensure_one()
        self.write(
            {
                "mdl_group_name_override": False,
                "mdl_model_name_override": (
                    "—" if self.mdl_model_as_attribute else False
                ),
            }
        )

    def action_mdl_reset_base_sku(self):
        self.ensure_one()
        self.write(
            {
                "mdl_group_sku_override": False,
                "mdl_model_sku_override": (
                    "—" if self.mdl_model_as_attribute else False
                ),
            }
        )

    def action_mdl_reset_base_values(self):
        self.ensure_one()
        self.write(
            {
                "mdl_group_name_override": False,
                "mdl_group_sku_override": False,
                "mdl_model_name_override": (
                    "—" if self.mdl_model_as_attribute else False
                ),
                "mdl_model_sku_override": (
                    "—" if self.mdl_model_as_attribute else False
                ),
            }
        )

    def _mdl_ensure_full_model_names(self, previous_group_names=None):
        previous_group_names = previous_group_names or {}
        for template in self.filtered("mdl_catalog_managed"):
            if template.mdl_model_as_attribute:
                full_name = clean_text(template.mdl_native_name_override)
                if not full_name:
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
            if (
                value.attribute_id.create_variant == "no_variant"
                or not value.attribute_line_id.mdl_include_in_sku
            ):
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
            if not value or line.mdl_name_mode == "hidden":
                continue
            value_name = value._mdl_get_name_component()
            if "פתיחה" in normalize_token(line.attribute_id.name):
                value_name, marker = split_direction_marker(value_name)
                if marker:
                    deferred_name_markers.append(marker)
            if line.mdl_name_mode == "attribute_value":
                value_name = clean_text(
                    f"{line.attribute_id.name} {value_name}"
                ) if value_name else ""
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
            # "טקסט אחרי" is the separator before the next row.  Deferring
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
        if not self.mdl_group_default_name:
            issues.append("לא הוגדר שם לקבוצת הפריטים.")
        if not self.categ_id:
            issues.append("לא נבחרה קטגוריית מוצר.")

        dynamic_attributes = self.attribute_line_ids.attribute_id.filtered(
            lambda attribute: attribute.create_variant == "dynamic"
        )
        if dynamic_attributes:
            issues.append(
                "המאפיינים הבאים מוגדרים ליצירת וריאנטים דינמית ולכן לא תיווצר "
                "התפוצצות מלאה: "
                + ", ".join(dynamic_attributes.mapped("name"))
                + "."
            )

        variants = self.product_variant_ids
        rendered = {
            product: self._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            for product in variants
        }
        generated_skus = [sku for sku, _name, _missing in rendered.values() if sku]
        for sku, count in Counter(generated_skus).items():
            if count > 1:
                issues.append(f"המק״ט {sku} נוצר ל-{count} פריטים בקבוצה.")

        for product, (sku, _name, missing) in rendered.items():
            if missing:
                issues.append(
                    f"בפריט {product.id} חסר רכיב מק״ט לערכים: "
                    + ", ".join(missing)
                    + "."
                )
            if include_sync_state and sku and product.default_code != sku:
                issues.append(
                    f"המק״ט של פריט {product.id} טרם עודכן ל-{sku}."
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
                    f"המק״ט {product.default_code} כבר נמצא בפריט אחר: "
                    f"{product.product_tmpl_id.name}."
                )
        return list(dict.fromkeys(issues))

    def _mdl_sync_variant_codes(self):
        if self.env.context.get("skip_mdl_catalog_sync"):
            return
        for template in self.filtered("mdl_catalog_managed"):
            template.product_variant_ids._mdl_sync_default_code()

    @api.depends(
        "product_variant_ids.active",
        "product_variant_ids.default_code",
        "product_variant_ids.mdl_generated_name",
        "product_variant_ids.mdl_catalog_allowed",
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
            examples = []
            for product in active.sorted("id")[:5]:
                name = product.mdl_generated_name or product.name
                examples.append(
                    clean_text(
                        f"[{product.default_code}] {name}"
                        if product.default_code
                        else name
                    )
                )
            template.mdl_active_variant_count = len(active)
            template.mdl_archived_variant_count = len(archived)
            template.mdl_blocked_variant_count = blocked_count
            template.mdl_variant_preview = "\n".join(examples) or "אין פריטים להצגה."

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
                    "המאפיין דגם של התוסף חייב להשתמש ביצירת וריאנטים "
                    "מיידית ובתצוגת בחירה רגילה."
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
                    "בתבנית %(template)s קיימות כמה שורות מאפיין בשם דגם. "
                    "יש להשאיר שורה אחת לפני ההמרה.",
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
                    "מאפיין הדגם בתבנית %(template)s אינו מוגדר ליצירת "
                    "וריאנטים מיידית.",
                    template=self.display_name,
                )
            )
        if model_line and len(model_line.value_ids) != 1:
            raise UserError(
                _(
                    "שורת הדגם בתבנית %(template)s חייבת להכיל ערך אחד "
                    "בזמן ההמרה.",
                    template=self.display_name,
                )
            )
        return model_line

    def _mdl_convert_models_to_attributes(self):
        """Move the legacy model component into a normal, ordered attribute.

        A single-value attribute line is deliberately used: Odoo 19 adds such
        a value to every existing variant instead of recreating the products,
        so stock moves, quotations and product IDs remain unchanged.
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

        # Validate every pre-existing model line before touching any template.
        # This produces one clear upgrade error without leaving a mixed state.
        for template in templates:
            model_line = template._mdl_model_line_for_conversion(
                default_model_attribute
            )
            derived_name = _name_without_group(
                template.mdl_group_default_name or template.categ_id.name,
                template.name,
            )
            if model_line and derived_name and (
                normalize_token(model_line.value_ids.name)
                != normalize_token(derived_name)
            ):
                raise UserError(
                    _(
                        "ערך הדגם %(value)s בתבנית %(template)s אינו תואם "
                        "לשם הדגם %(model)s.",
                        value=model_line.value_ids.name,
                        template=template.display_name,
                        model=derived_name,
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
            source_model_name = clean_text(
                model_line.value_ids.name
                if model_line
                else _name_without_group(group_name, template.name)
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
            model_value = (
                model_line.value_ids
                if model_line
                else values.filtered(
                    lambda item: (
                        normalize_token(item.name)
                        == normalize_token(source_model_name)
                    )
                )[:1]
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
                model_line.with_context(
                    skip_mdl_catalog_sync=True,
                    mdl_preserve_variant_ids=True,
                ).write(
                    {
                        "active": True,
                        "mdl_is_model_attribute": True,
                        "mdl_name_mode": (
                            "value" if effective_model_name else "hidden"
                        ),
                        "mdl_include_in_sku": bool(effective_model_sku),
                    }
                )
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
                        "mdl_name_mode": (
                            "value" if effective_model_name else "hidden"
                        ),
                        "mdl_include_in_sku": bool(effective_model_sku),
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
                "title": "המרת דגם הושלמה",
                "message": f"הדגם הועבר למאפיין רגיל ב-{len(converted)} קבוצות.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _create_variant_ids(self):
        if self.env.context.get("mdl_defer_variant_rebuild"):
            return True
        result = super()._create_variant_ids()
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
                    "לא ניתן לעדכן את הפריטים לפני תיקון השגיאות:\n%s",
                    "\n".join(f"• {issue}" for issue in issues),
                )
            )
        self._mdl_sync_variant_codes()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "החישוב הושלם",
                "message": f"עודכנו {len(self.product_variant_ids)} פריטים בקבוצה.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_mdl_preview_catalog(self):
        self.ensure_one()
        self._compute_mdl_variant_overview()
        message = (
            f"פעילים: {self.mdl_active_variant_count} | "
            f"בארכיון: {self.mdl_archived_variant_count} | "
            f"חסומים: {self.mdl_blocked_variant_count}\n"
            f"{self.mdl_variant_preview}"
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "תצוגה מקדימה של הקבוצה",
                "message": message,
                "type": "info",
                "sticky": True,
            },
        }

    def action_mdl_open_variants(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "product.product_variant_action"
        )
        normal_form = self.env.ref("product.product_normal_form_view")
        action["views"] = [
            (view_id, view_type)
            for view_id, view_type in action.get("views", [])
            if view_type != "form"
        ] + [(normal_form.id, "form")]
        action["domain"] = [("product_tmpl_id", "=", self.id)]
        action["context"] = {
            "default_product_tmpl_id": self.id,
            "search_default_product_tmpl_id": self.id,
            "form_view_ref": "product.product_normal_form_view",
        }
        return action

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
                Domain("mdl_generated_name", operator, name),
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
