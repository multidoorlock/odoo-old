from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from .catalog_utils import clean_text


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


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mdl_sku_prefix = fields.Char(
        string="קידומת מק״ט לווריאנטים",
        index=True,
        copy=False,
        help=(
            "החלק הקבוע בתחילת כל מק״ט של הדגם, לדוגמה 1001. "
            "המק״ט הסופי נשמר בשדה המקורי 'מק״ט פנימי' של הווריאנט."
        ),
    )
    mdl_variant_base_name = fields.Char(
        string="שם בסיס לפריטים הסופיים",
        copy=True,
        help=(
            "אופציונלי. אם ריק, שם הדגם הרגיל של Odoo משמש כבסיס. "
            "מיועד רק למקרה שבו שם הפריט הסופי צריך להיות שונה משם הדגם."
        ),
    )
    mdl_name_suffix = fields.Char(
        string="טקסט קבוע בסוף השם",
        copy=True,
        help="אופציונלי, לדוגמה: [+ידית] או ***כולל מנגנון***.",
    )
    mdl_first_item_example = fields.Char(
        string="דוגמת פריט ראשון",
        compute="_compute_mdl_first_item_example",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for field_name in ("mdl_sku_prefix", "mdl_variant_base_name"):
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
        for field_name in ("mdl_sku_prefix", "mdl_variant_base_name"):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in (
                "name",
                "categ_id",
                "mdl_sku_prefix",
                "mdl_variant_base_name",
                "mdl_name_suffix",
            )
        ):
            self._mdl_ensure_full_model_names(previous_group_names)
            self._mdl_sync_variant_codes()
        return result

    def _mdl_ensure_full_model_names(self, previous_group_names=None):
        previous_group_names = previous_group_names or {}
        for template in self.filtered("mdl_sku_prefix"):
            previous_group = previous_group_names.get(template.id)
            model_name = _name_without_group(previous_group, template.name)
            full_name = _name_with_group(template.categ_id.name, model_name)
            updates = {}
            if full_name and template.name != full_name:
                updates["name"] = full_name
            if previous_group and template.mdl_variant_base_name:
                previous_base = clean_text(template.mdl_variant_base_name)
                if previous_base == previous_group or previous_base.startswith(
                    f"{previous_group} "
                ):
                    updates["mdl_variant_base_name"] = _name_with_group(
                        template.categ_id.name,
                        _name_without_group(previous_group, previous_base),
                    )
            if updates:
                super(
                    ProductTemplate,
                    template.with_context(skip_mdl_catalog_sync=True),
                ).write(updates)

    @api.depends(
        "product_variant_ids.default_code",
        "product_variant_ids.mdl_generated_name",
    )
    def _compute_mdl_first_item_example(self):
        for template in self:
            variant = template.product_variant_ids.sorted(
                lambda product: (product.combination_indices or "", product.id)
            )[:1]
            if variant:
                sku = clean_text(variant.default_code)
                name = clean_text(variant.mdl_generated_name)
            else:
                sku, name, _missing = template._mdl_render_catalog_values(
                    self.env["product.template.attribute.value"]
                )
            template.mdl_first_item_example = (
                f"{sku} - {name}" if sku and name else sku or name or False
            )

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
            if component:
                sku_parts.append(component)
            else:
                missing_components.append(value.display_name)

        final_name = clean_text(self.mdl_variant_base_name or self.name)
        for line in self.attribute_line_ids.filtered("active").sorted(
            lambda item: (item.sequence, item.attribute_id.sequence, item.id)
        ):
            value = values_by_line.get(line.id)
            if not value or line.mdl_name_mode == "hidden":
                continue
            value_name = value._mdl_get_name_component()
            if line.mdl_name_mode == "attribute_value":
                value_name = clean_text(f"{line.attribute_id.name} {value_name}")
            final_name += (
                f"{line.mdl_name_prefix or ''}"
                f"{value_name}"
                f"{line.mdl_name_suffix or ''}"
            )
        final_name += self.mdl_name_suffix or ""
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
