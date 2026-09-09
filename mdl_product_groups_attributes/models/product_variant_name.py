from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import SQL

from .catalog_utils import clean_text


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Sparse, exact-language values on the variant itself. Native translated
    # Char storage falls back to en_US and clearing it can clear every language;
    # neither is appropriate for an optional per-language override.
    mdl_name_overrides = fields.Json(
        string="Product Name Overrides (Technical)",
        copy=False,
    )
    mdl_name_override = fields.Char(
        string="Custom Name in This Language",
        compute="_compute_mdl_name_override",
        inverse="_inverse_mdl_name_override",
        search="_search_mdl_name_override",
        translate=True,
        help=(
            "Optional name for this variant in the current language. Use the "
            "language button to edit other languages. Clear a language to use "
            "its automatic name. The SKU and other variants are unchanged."
        ),
    )
    mdl_effective_name = fields.Char(
        string="Product Name",
        compute="_compute_mdl_effective_name",
        search="_search_mdl_effective_name",
    )
    mdl_automatic_name = fields.Char(
        string="Automatic Name",
        compute="_compute_mdl_effective_name",
    )

    @api.depends("mdl_name_overrides")
    def _compute_mdl_name_override(self):
        # translate=True already gives this computed field a language cache.
        # An empty string (not False) must be cached for a missing language,
        # otherwise Odoo's translation cache marks ALL languages as empty.
        lang = self.env.lang or "en_US"
        for product in self:
            product.mdl_name_override = (product.mdl_name_overrides or {}).get(lang, "")

    def _inverse_mdl_name_override(self):
        lang = self.env.lang or "en_US"
        for product in self:
            product._mdl_update_name_overrides({lang: product.mdl_name_override})

    def write(self, vals):
        result = super().write(vals)
        if "mdl_name_override" in vals:
            # Inverses protect their field while its backing data is written.
            # Discard that protected value, especially False, for every lang.
            self.invalidate_recordset(["mdl_name_override"])
        return result

    @api.constrains("mdl_name_overrides")
    def _check_mdl_name_overrides(self):
        known_langs = set(self.env["res.lang"].with_context(active_test=False).search([]).mapped("code"))
        for product in self:
            values = product.mdl_name_overrides or {}
            if not isinstance(values, dict) or any(
                lang not in known_langs or not isinstance(value, str)
                or not value or value != clean_text(value)
                for lang, value in values.items()
            ):
                raise ValidationError(_("Product name overrides must contain valid language codes and non-empty names."))

    def _mdl_update_name_overrides(self, translations):
        self.ensure_one()
        self.check_access("write")
        self._check_field_access(self._fields["mdl_name_override"], "write")
        if not isinstance(translations, dict):
            raise ValidationError(_("Product name translations must be a language-to-name mapping."))
        installed = {code for code, _name in self.env["res.lang"].get_installed()}
        if set(translations) - installed:
            raise ValidationError(_("Activate the language before adding a product name override."))
        values = dict(self.mdl_name_overrides or {})
        for lang, value in translations.items():
            if value is not None and value is not False and not isinstance(value, str):
                raise ValidationError(_("A product name override must be text."))
            value = clean_text(value)
            if value:
                values[lang] = value
            else:
                values.pop(lang, None)
        if values != (self.mdl_name_overrides or {}):
            self.mdl_name_overrides = values or False
        return True

    def get_field_translations(self, field_name, langs=None):
        if field_name != "mdl_name_override":
            return super().get_field_translations(field_name, langs=langs)
        self.ensure_one()
        self.check_access("read")
        self._check_field_access(self._fields[field_name], "read")
        values = self.mdl_name_overrides or {}
        langs = langs or [code for code, _name in self.env["res.lang"].get_installed()]
        return [
            {"lang": lang, "source": "", "value": values.get(lang, "")}
            for lang in sorted(set(langs))
        ], {"translation_type": "char", "translation_show_source": False}

    def _update_field_translations(self, field_name, translations, digest=None, source_lang=""):
        # Adapt only this computed field to Odoo's existing language dialog.
        # Other fields retain the native translation/import behavior.
        if field_name == "mdl_name_override":
            return self._mdl_update_name_overrides(translations)
        return super()._update_field_translations(
            field_name, translations, digest=digest, source_lang=source_lang,
        )

    @api.depends(
        "mdl_name_override", "mdl_generated_name", "name",
        "product_tmpl_id.mdl_catalog_managed",
    )
    @api.depends_context("lang")
    def _compute_mdl_effective_name(self):
        for product in self:
            if not product.product_tmpl_id.mdl_catalog_managed:
                product.mdl_automatic_name = product.name
                product.mdl_effective_name = product.name
                continue
            _sku, automatic_name, _missing = product.product_tmpl_id._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            product.mdl_automatic_name = automatic_name or product.mdl_generated_name or product.name
            product.mdl_effective_name = (
                product.mdl_name_override or automatic_name
                or product.mdl_generated_name or product.name
            )

    @api.model
    def _search_mdl_name_override(self, operator, value):
        # Search the exact language in SQL without scanning variants in Python.
        # Domain.custom stays inside the normal ORM query and its access rules.
        lang = self.env.lang or "en_US"
        if operator in ("=", "!="):
            operator, value = ("in" if operator == "=" else "not in"), [value]
        if operator in ("in", "not in"):
            values = [item or "" for item in value]
            def condition(model, alias, query):
                column = model._field_to_sql(alias, "mdl_name_overrides", query)
                return SQL("COALESCE(%s->>%s, '') = ANY(%s::text[])", column, lang, values)
            domain = Domain.custom(to_sql=condition)
            return ~domain if operator == "not in" else domain
        if operator not in ("like", "ilike", "=like", "=ilike", "not like", "not ilike"):
            return NotImplemented
        negative = operator.startswith("not ")
        exact = operator.startswith("=")
        sql_operator = SQL("ILIKE") if "ilike" in operator else SQL("LIKE")
        pattern = value if exact else f"%{value}%"
        def condition(model, alias, query):
            column = model._field_to_sql(alias, "mdl_name_overrides", query)
            return SQL("COALESCE(%s->>%s, '') %s %s", column, lang, sql_operator, pattern)
        domain = Domain.custom(to_sql=condition)
        return ~domain if negative else domain

    @api.model
    def _search_mdl_effective_name(self, operator, value):
        managed = Domain("product_tmpl_id.mdl_catalog_managed", "=", True)
        custom = Domain("mdl_name_override", "!=", False)
        return (
            managed & (
                (custom & Domain("mdl_name_override", operator, value))
                | (~custom & Domain("mdl_generated_name", operator, value))
            )
        ) | (~managed & Domain("name", operator, value))

    @api.model
    def _search_display_name(self, operator, value):
        native = Domain(super()._search_display_name(operator, value))
        effective = Domain("mdl_effective_name", operator, value)
        return native & effective if operator in Domain.NEGATIVE_OPERATORS else native | effective
