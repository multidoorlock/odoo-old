from odoo import api, fields, models
from odoo.fields import Domain

from .catalog_utils import (
    DEFAULT_VARIANT_DISPLAY_FORMAT,
    VARIANT_DISPLAY_FORMAT_PARAM,
    clean_text,
    ltr_isolate,
    render_format,
)


class ProductProduct(models.Model):
    _inherit = "product.product"

    mdl_generated_name = fields.Char(
        string="שם פריט סופי",
        compute="_compute_mdl_catalog_values",
        store=True,
        index="trigram",
    )

    @api.depends(
        "product_tmpl_id.mdl_sku_prefix",
        "product_tmpl_id.mdl_effective_base_name",
        "product_tmpl_id.attribute_line_ids.sequence",
        "product_tmpl_id.attribute_line_ids.mdl_name_mode",
        "product_tmpl_id.attribute_line_ids.mdl_name_suffix",
        "product_template_attribute_value_ids",
        "product_template_attribute_value_ids.product_attribute_value_id.name",
        "product_template_attribute_value_ids.mdl_name_component_override",
    )
    def _compute_mdl_catalog_values(self):
        for product in self:
            template = product.product_tmpl_id
            if not template.mdl_sku_prefix:
                product.mdl_generated_name = False
                continue
            _sku, name, _missing = template._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            product.mdl_generated_name = name or False

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        if not self.env.context.get("skip_mdl_catalog_sync"):
            products._mdl_sync_default_code()
        return products

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("skip_mdl_catalog_sync") and (
            "product_template_attribute_value_ids" in vals
        ):
            self._mdl_sync_default_code()
        return result

    def _mdl_sync_default_code(self):
        for product in self:
            template = product.product_tmpl_id
            if not template.mdl_sku_prefix:
                continue
            generated_sku, _name, missing = template._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            if generated_sku and not missing and product.default_code != generated_sku:
                product.with_context(skip_mdl_catalog_sync=True).write(
                    {"default_code": generated_sku}
                )

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
        extra_domain &= Domain("mdl_generated_name", operator, name)
        if existing_ids:
            extra_domain &= Domain("id", "not in", existing_ids)
        extra_products = self.search(extra_domain, limit=remaining)
        return results + [
            (product.id, product.display_name) for product in extra_products
        ]

    @api.depends(
        "name",
        "default_code",
        "product_tmpl_id",
        "mdl_generated_name",
        "product_tmpl_id.mdl_sku_prefix",
    )
    @api.depends_context(
        "display_default_code",
        "seller_id",
        "company_id",
        "partner_id",
        "formatted_display_name",
        "lang",
    )
    def _compute_display_name(self):
        super()._compute_display_name()
        if self.env.context.get("seller_id"):
            return
        display_default_code = self.env.context.get("display_default_code", True)
        display_format = self.env["ir.config_parameter"].sudo().get_param(
            VARIANT_DISPLAY_FORMAT_PARAM,
            DEFAULT_VARIANT_DISPLAY_FORMAT,
        )
        for product in self:
            if not (
                product.product_tmpl_id.mdl_sku_prefix
                and product.mdl_generated_name
            ):
                continue
            if display_default_code and product.default_code:
                display_name, missing = render_format(
                    display_format or DEFAULT_VARIANT_DISPLAY_FORMAT,
                    {
                        "שם הפריט": product.mdl_generated_name,
                        "מק״ט": ltr_isolate(f"[{product.default_code}]"),
                    },
                )
                product.display_name = (
                    display_name
                    if display_name and not missing
                    else f"{ltr_isolate(f'[{product.default_code}]')} "
                    f"{product.mdl_generated_name}"
                )
            else:
                product.display_name = product.mdl_generated_name
