from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from .catalog_utils import clean_text, normalize_token, split_direction_marker


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
            "מחושב מרכיב המק״ט של קבוצת הפריטים ומרכיב המק״ט של הדגם. "
            "המק״ט הסופי נשמר בשדה המקורי 'מק״ט פנימי' של הווריאנט."
        ),
    )
    mdl_group_default_name = fields.Char(
        related="categ_id.name",
        string="טקסט ברירת מחדל לקבוצה",
        readonly=False,
        help="שם קבוצת הפריטים. שינוי כאן משנה את הקבוצה ואת כל הדגמים שבה.",
    )
    mdl_group_default_sku = fields.Char(
        related="categ_id.mdl_sku_component",
        string="מק״ט ברירת מחדל לקבוצה",
        readonly=False,
        help="רכיב המק״ט של קבוצת הפריטים לכל הדגמים בקבוצה.",
    )
    mdl_group_name_override = fields.Char(
        string="שינוי טקסט לקבוצה",
        help="אופציונלי לדגם זה בלבד. הזן — כדי לא להציג את הקבוצה בשם.",
    )
    mdl_group_sku_override = fields.Char(
        string="שינוי מק״ט לקבוצה",
        help="אופציונלי לדגם זה בלבד. הזן — כדי לא להוסיף את רכיב הקבוצה.",
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
        help="אופציונלי. הזן — כדי לא להציג את הדגם בשם הפריט הסופי.",
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
            "לדגם הזה בלבד; איפוס מחזיר לשם הקטגוריה."
        ),
    )
    mdl_group_sku_value = fields.Char(
        string="מק״ט קבוצת פריטים",
        compute="_compute_mdl_group_sku_value",
        inverse="_inverse_mdl_group_sku_value",
        help=(
            "מציג את רכיב המק״ט הקבוצתי שבפועל. עריכה יוצרת שינוי לדגם "
            "הזה בלבד; איפוס מחזיר למק״ט שבקטגוריה."
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
            "משם קבוצת הפריטים ושם הדגם; עריכה משנה רק את הדגם הנוכחי."
        ),
    )
    mdl_attribute_value_ids = fields.One2many(
        comodel_name="product.template.attribute.value",
        inverse_name="product_tmpl_id",
        string="ערכי מאפיינים בדגם",
    )

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
        "categ_id.mdl_sku_component",
        "mdl_group_sku_override",
        "mdl_model_sku_component",
        "mdl_model_sku_override",
    )
    def _compute_mdl_sku_prefix(self):
        for template in self:
            group_sku = _resolved_component(
                template.categ_id.mdl_sku_component,
                template.mdl_group_sku_override,
            )
            model_sku = _resolved_component(
                template.mdl_model_sku_component,
                template.mdl_model_sku_override,
            )
            template.mdl_sku_prefix = f"{group_sku}{model_sku}" or False

    def _inverse_mdl_sku_prefix(self):
        for template in self:
            effective_value = clean_text(template.mdl_sku_prefix)
            source_value = clean_text(
                f"{template.categ_id.mdl_sku_component or ''}"
                f"{template.mdl_model_sku_component or ''}"
            )
            if effective_value == source_value:
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

    @api.depends("name", "categ_id.name")
    def _compute_mdl_model_default_name(self):
        for template in self:
            template.mdl_model_default_name = _name_without_group(
                template.categ_id.name,
                template.name,
            )

    def _inverse_mdl_model_default_name(self):
        for template in self:
            full_name = _name_with_group(
                template.categ_id.name,
                template.mdl_model_default_name,
            )
            if full_name and template.name != full_name:
                template.with_context(skip_mdl_catalog_sync=True).name = full_name

    @api.depends("categ_id.name", "mdl_group_name_override")
    def _compute_mdl_group_name_value(self):
        for template in self:
            template.mdl_group_name_value = _resolved_component(
                template.categ_id.name,
                template.mdl_group_name_override,
            )

    def _inverse_mdl_group_name_value(self):
        for template in self:
            override = _override_from_effective_value(
                template.categ_id.name,
                template.mdl_group_name_value,
            )
            if template.mdl_group_name_override != override:
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_group_name_override": override}
                )

    @api.depends("categ_id.mdl_sku_component", "mdl_group_sku_override")
    def _compute_mdl_group_sku_value(self):
        for template in self:
            template.mdl_group_sku_value = _resolved_component(
                template.categ_id.mdl_sku_component,
                template.mdl_group_sku_override,
            )

    def _inverse_mdl_group_sku_value(self):
        for template in self:
            override = _override_from_effective_value(
                template.categ_id.mdl_sku_component,
                template.mdl_group_sku_value,
            )
            if template.mdl_group_sku_override != override:
                template.with_context(skip_mdl_catalog_sync=True).write(
                    {"mdl_group_sku_override": override}
                )

    @api.depends("name", "categ_id.name", "mdl_model_name_override")
    def _compute_mdl_model_name_value(self):
        for template in self:
            template.mdl_model_name_value = _resolved_component(
                _name_without_group(template.categ_id.name, template.name),
                template.mdl_model_name_override,
            )

    def _inverse_mdl_model_name_value(self):
        for template in self:
            override = _override_from_effective_value(
                _name_without_group(template.categ_id.name, template.name),
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
        "categ_id.name",
        "mdl_group_name_override",
        "mdl_model_name_override",
    )
    def _compute_mdl_effective_base_name(self):
        for template in self:
            group_name = _resolved_component(
                template.categ_id.name,
                template.mdl_group_name_override,
            )
            model_name = _resolved_component(
                _name_without_group(template.categ_id.name, template.name),
                template.mdl_model_name_override,
            )
            template.mdl_effective_base_name = clean_text(
                " ".join(part for part in (group_name, model_name) if part)
            )

    def _inverse_mdl_effective_base_name(self):
        for template in self:
            effective_value = clean_text(template.mdl_effective_base_name)
            source_value = _name_with_group(
                template.categ_id.name,
                _name_without_group(template.categ_id.name, template.name),
            )
            if effective_value == source_value:
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for field_name in (
                "mdl_group_name_override",
                "mdl_group_sku_override",
                "mdl_model_sku_component",
                "mdl_model_name_override",
                "mdl_model_sku_override",
            ):
                if field_name in vals:
                    vals[field_name] = clean_text(vals[field_name])
        templates = super().create(vals_list)
        templates._mdl_ensure_full_model_names()
        templates._mdl_sync_variant_codes()
        return templates

    def write(self, vals):
        previous_group_names = (
            {template.id: clean_text(template.categ_id.name) for template in self}
            if "categ_id" in vals
            else {}
        )
        for field_name in (
            "mdl_group_name_override",
            "mdl_group_sku_override",
            "mdl_model_sku_component",
            "mdl_model_name_override",
            "mdl_model_sku_override",
        ):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in (
                "name",
                "categ_id",
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
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_mdl_reset_model_values(self):
        self.ensure_one()
        self.write(
            {
                "mdl_model_name_override": False,
                "mdl_model_sku_override": False,
            }
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_mdl_reset_base_values(self):
        self.ensure_one()
        self.write(
            {
                "mdl_group_name_override": False,
                "mdl_group_sku_override": False,
                "mdl_model_name_override": False,
                "mdl_model_sku_override": False,
            }
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def _mdl_ensure_full_model_names(self, previous_group_names=None):
        previous_group_names = previous_group_names or {}
        for template in self.filtered("mdl_sku_prefix"):
            previous_group = previous_group_names.get(template.id)
            model_name = _name_without_group(previous_group, template.name)
            full_name = _name_with_group(template.categ_id.name, model_name)
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
            previous_line_suffix = line.mdl_name_suffix or ""
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
        if not self.mdl_sku_prefix:
            return []

        issues = []
        if not self.categ_id:
            issues.append("לא נבחרה קבוצת פריטים (קטגוריית מוצר).")

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
                issues.append(f"המק״ט {sku} נוצר ל-{count} וריאנטים בדגם.")

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
        for template in self.filtered("mdl_sku_prefix"):
            template.product_variant_ids._mdl_sync_default_code()

    def _create_variant_ids(self):
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
                "message": f"עודכנו {len(self.product_variant_ids)} פריטים בדגם.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_mdl_open_variants(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "product.product_variant_action"
        )
        action["domain"] = [("product_tmpl_id", "=", self.id)]
        action["context"] = {
            "default_product_tmpl_id": self.id,
            "search_default_product_tmpl_id": self.id,
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

    @api.depends("name", "default_code", "mdl_sku_prefix")
    @api.depends_context("formatted_display_name", "display_default_code")
    def _compute_display_name(self):
        super()._compute_display_name()
        for template in self:
            if template.mdl_sku_prefix:
                template.display_name = (
                    f"{template.mdl_sku_prefix} - {template.name}"
                )
