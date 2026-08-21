from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from .catalog_utils import clean_text, extract_tokens, normalize_token, render_format


BASE_TOKEN_ALIASES = {
    normalize_token("שם קבוצת פריטים"): "group_name",
    normalize_token("קבוצת פריטים"): "group_name",
    normalize_token("דגם"): "model_name",
    normalize_token("שם דגם"): "model_name",
}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mdl_model_code = fields.Char(
        string="קוד דגם",
        index=True,
        copy=False,
        help="החלק במק״ט שמגיע מיד אחרי קוד קבוצת הפריטים.",
    )
    mdl_name_format = fields.Char(
        string="פורמט שם הפריט",
        copy=True,
        help=(
            "השתמשו ב-[שם קבוצת פריטים], [דגם] ובשם כל מאפיין בסוגריים מרובעים. "
            "כל טקסט קבוע, כגון /, -, או +ידית, נכתב ישירות בפורמט."
        ),
    )
    mdl_sku_prefix = fields.Char(
        string="קידומת מק״ט",
        compute="_compute_mdl_model_identity",
        store=True,
    )
    mdl_model_lookup = fields.Char(
        string="Lookup דגם מלא",
        compute="_compute_mdl_model_identity",
        store=True,
    )
    mdl_first_item_example = fields.Char(
        string="דוגמת פריט ראשון",
        compute="_compute_mdl_first_item_example",
    )
    mdl_catalog_status = fields.Selection(
        selection=[("ok", "תקין"), ("error", "נדרשת בדיקה")],
        string="תקינות",
        compute="_compute_mdl_catalog_status",
    )
    mdl_catalog_error_count = fields.Integer(
        string="מספר שגיאות",
        compute="_compute_mdl_catalog_status",
    )
    mdl_catalog_errors = fields.Text(
        string="שגיאות וקונפליקטים",
        compute="_compute_mdl_catalog_status",
    )
    mdl_template_value_ids = fields.One2many(
        comodel_name="product.template.attribute.value",
        inverse_name="product_tmpl_id",
        string="שיוך ערכי מאפיינים",
    )
    mdl_exclusion_ids = fields.One2many(
        comodel_name="product.template.attribute.exclusion",
        inverse_name="product_tmpl_id",
        string="שילובים לא מורשים",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for field_name in ("mdl_model_code", "mdl_name_format"):
                if field_name in vals:
                    vals[field_name] = clean_text(vals[field_name])
        templates = super().create(vals_list)
        templates._mdl_sync_variant_codes()
        return templates

    def write(self, vals):
        for field_name in ("mdl_model_code", "mdl_name_format"):
            if field_name in vals:
                vals[field_name] = clean_text(vals[field_name])
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and any(
            field_name in vals
            for field_name in (
                "name",
                "categ_id",
                "mdl_model_code",
                "mdl_name_format",
            )
        ):
            self._mdl_sync_variant_codes()
        return result

    @api.depends("name", "categ_id.name", "categ_id.mdl_group_code", "mdl_model_code")
    def _compute_mdl_model_identity(self):
        for template in self:
            group_code = clean_text(template.categ_id.mdl_group_code)
            model_code = clean_text(template.mdl_model_code)
            prefix = f"{group_code}{model_code}" if group_code and model_code else ""
            names = clean_text(
                " ".join(part for part in (template.categ_id.name, template.name) if part)
            )
            template.mdl_sku_prefix = prefix or False
            template.mdl_model_lookup = (
                f"{prefix} - {names}" if prefix and names else names or prefix or False
            )

    @api.depends(
        "product_variant_ids.mdl_generated_sku",
        "product_variant_ids.mdl_generated_name",
    )
    def _compute_mdl_first_item_example(self):
        for template in self:
            variant = template.product_variant_ids.sorted(
                lambda product: (product.combination_indices or "", product.id)
            )[:1]
            if variant:
                sku = clean_text(variant.mdl_generated_sku)
                name = clean_text(variant.mdl_generated_name)
            else:
                sku, name, _missing = template._mdl_render_catalog_values(
                    self.env["product.template.attribute.value"]
                )
            template.mdl_first_item_example = (
                f"{sku} - {name}" if sku and name else sku or name or False
            )

    @api.depends(
        "name",
        "categ_id.name",
        "categ_id.mdl_group_code",
        "mdl_model_code",
        "mdl_name_format",
        "attribute_line_ids.attribute_id.name",
        "attribute_line_ids.attribute_id.create_variant",
        "mdl_template_value_ids.mdl_effective_sku_component",
        "mdl_template_value_ids.mdl_effective_name_component",
        "product_variant_ids.default_code",
        "product_variant_ids.mdl_generated_sku",
        "product_variant_ids.mdl_generated_name",
    )
    def _compute_mdl_catalog_status(self):
        for template in self:
            issues = template._mdl_get_catalog_issues(include_sync_state=True)
            template.mdl_catalog_status = "error" if issues else "ok"
            template.mdl_catalog_error_count = len(issues)
            template.mdl_catalog_errors = "\n".join(
                f"• {issue}" for issue in issues
            ) or False

    def _mdl_catalog_replacements(self, combination):
        self.ensure_one()
        replacements = {
            "שם קבוצת פריטים": self.categ_id.name,
            "קבוצת פריטים": self.categ_id.name,
            "דגם": self.name,
            "שם דגם": self.name,
        }
        for value in combination.sorted(
            lambda item: (
                item.attribute_line_id.sequence,
                item.attribute_id.sequence,
                item.attribute_id.id,
                item.id,
            )
        ):
            replacements[value.attribute_id.name] = value.mdl_effective_name_component
        return replacements

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
        sku_parts.extend(
            clean_text(value.mdl_effective_sku_component)
            for value in ordered_values
            if value.attribute_id.create_variant != "no_variant"
        )
        sku = "".join(part for part in sku_parts if part)
        name, missing_tokens = render_format(
            self.mdl_name_format,
            self._mdl_catalog_replacements(ordered_values),
        )
        return sku, name, missing_tokens

    def _mdl_get_catalog_issues(self, include_sync_state=False):
        self.ensure_one()
        if not self.mdl_name_format and not self.mdl_model_code:
            return []

        issues = []
        if not self.categ_id:
            issues.append("לא נבחרה קבוצת פריטים (קטגוריית מוצר).")
        elif not clean_text(self.categ_id.mdl_group_code):
            issues.append("לקבוצת הפריטים חסר קוד.")
        if not clean_text(self.mdl_model_code):
            issues.append("לדגם חסר קוד דגם.")
        if not clean_text(self.mdl_name_format):
            issues.append("לדגם חסר פורמט שם.")

        normalized_attributes = {
            normalize_token(line.attribute_id.name): line.attribute_id.name
            for line in self.attribute_line_ids
        }
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
        for token in extract_tokens(self.mdl_name_format):
            normalized = normalize_token(token)
            if normalized not in BASE_TOKEN_ALIASES and normalized not in normalized_attributes:
                issues.append(f"המציין [{token}] אינו מאפיין המשויך לדגם.")

        variant_values = self.mdl_template_value_ids.filtered(
            lambda value: value.ptav_active
            and value.attribute_id.create_variant != "no_variant"
        )
        for value in variant_values:
            if not clean_text(value.mdl_effective_sku_component):
                issues.append(
                    "חסר רכיב מק״ט עבור "
                    f"{value.attribute_id.name}: {value.product_attribute_value_id.name}."
                )

        other_model = self.with_context(active_test=False).search(
            [
                ("id", "!=", self.id),
                ("categ_id", "=", self.categ_id.id),
                ("mdl_model_code", "=", self.mdl_model_code),
            ],
            limit=1,
        ) if self.categ_id and self.mdl_model_code else self.env["product.template"]
        if other_model:
            issues.append(
                "קוד הדגם כבר משויך לדגם נוסף באותה קבוצת פריטים: "
                f"{other_model.name}."
            )

        variants = self.with_context(active_test=False).product_variant_ids
        generated_skus = [
            clean_text(product.mdl_generated_sku)
            for product in variants
            if clean_text(product.mdl_generated_sku)
        ]
        for sku, count in Counter(generated_skus).items():
            if count > 1:
                issues.append(f"המק״ט {sku} נוצר ל-{count} וריאנטים בדגם.")

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

        for product in variants:
            _sku, _name, missing = self._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            for token in missing:
                issues.append(
                    f"בפריט {product.id} אין ערך עבור המציין [{token}] שבפורמט."
                )
            if include_sync_state and product.mdl_generated_sku and (
                product.default_code != product.mdl_generated_sku
            ):
                issues.append(
                    f"המק״ט של פריט {product.id} טרם עודכן ל-{product.mdl_generated_sku}."
                )

        return list(dict.fromkeys(issues))

    def _mdl_sync_variant_codes(self):
        if self.env.context.get("skip_mdl_catalog_sync"):
            return
        for template in self.filtered("mdl_name_format"):
            variants = template.with_context(active_test=False).product_variant_ids
            variants._mdl_sync_default_code()

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
        extra_domain = Domain(domain or Domain.TRUE)
        extra_domain &= Domain("mdl_model_lookup", operator, name)
        if existing_ids:
            extra_domain &= Domain("id", "not in", existing_ids)
        extra_templates = self.search(extra_domain, limit=remaining)
        return results + [
            (template.id, template.display_name) for template in extra_templates
        ]

    @api.depends("name", "default_code", "mdl_model_lookup", "mdl_name_format")
    @api.depends_context("formatted_display_name", "display_default_code")
    def _compute_display_name(self):
        super()._compute_display_name()
        for template in self:
            if template.mdl_name_format and template.mdl_model_lookup:
                template.display_name = template.mdl_model_lookup
