from odoo import api, fields, models

from .catalog_utils import changed_name_language_records, snapshot_other_name_languages


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    mdl_name_prefix = fields.Char(
        string="Legacy Prefix (Unused)",
        help="Compatibility field; row order and Text After are used now.",
    )
    mdl_name_suffix = fields.Char(
        string="Text After",
        translate=True,
        help=(
            "Separator between this attribute value and the next attribute. "
            "A normal space is added automatically; / and + remain attached."
        ),
    )
    mdl_variant_creation_mode = fields.Selection(
        related="attribute_id.create_variant",
        string="Variant Creation",
        readonly=True,
    )
    mdl_is_model_attribute = fields.Boolean(
        string="Converted Model Row",
        default=False,
        copy=True,
        help=(
            "Technical compatibility marker. The row behaves like any other attribute."
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            lines.product_tmpl_id._mdl_ensure_full_model_names()
            lines.product_tmpl_id._mdl_sync_variant_codes()
        return lines

    def write(self, vals):
        templates_before = self.product_tmpl_id
        previous_names = snapshot_other_name_languages(
            self, ("mdl_name_suffix",) if "mdl_name_suffix" in vals else (),
        )
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates = templates_before | self.product_tmpl_id
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        for lines in changed_name_language_records(self, previous_names):
            templates = lines.product_tmpl_id
            if "product_tmpl_id" in vals:
                templates |= templates_before.with_context(lang=lines.env.lang)
            templates._mdl_sync_variant_codes()
        return result

    def _update_field_translations(self, field_name, translations, digest=None, source_lang=""):
        if field_name != "mdl_name_suffix" or self.env.context.get("skip_mdl_catalog_sync"):
            return super()._update_field_translations(
                field_name, translations, digest=digest, source_lang=source_lang,
            )
        self.ensure_one()
        previous = self._fields[field_name]._get_stored_translations(self) or {}
        result = super(
            ProductTemplateAttributeLine,
            self.with_context(skip_mdl_catalog_sync=True),
        )._update_field_translations(
            field_name, dict(translations), digest=digest, source_lang=source_lang,
        )
        if result:
            # Translation dialogs write only in their UI language. Refresh each
            # changed language, including native fallbacks changed by English.
            languages = {code for code, _name in self.env["res.lang"].get_installed()} | {"en_US"}
            for lang in languages:
                line = self.with_context(lang=lang)
                old_text = previous.get(lang, previous.get("en_US", "")) or ""
                if (line.mdl_name_suffix or "") != old_text:
                    line.product_tmpl_id._mdl_sync_variant_codes()
        return result

    def unlink(self):
        templates = self.product_tmpl_id
        result = super().unlink()
        if not self.env.context.get("skip_mdl_catalog_sync"):
            templates._mdl_ensure_full_model_names()
            templates._mdl_sync_variant_codes()
        return result
