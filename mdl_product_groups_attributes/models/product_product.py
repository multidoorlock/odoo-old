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

    mdl_max_protected_area_m2 = fields.Float(
        string="Maximum Protected Area (m²)",
        help="Technical product data; it does not create variants.",
    )
    mdl_installation_type = fields.Selection(
        selection=[
            ("overhead", "Overhead"),
            ("concealed", "Concealed"),
            ("other", "Other"),
        ],
        string="Installation Type",
        help="Technical product data; it is not part of the product name.",
    )
    mdl_length_cm = fields.Float(
        string="Length (cm)",
        help="Product length in centimetres.",
    )
    mdl_width_cm = fields.Float(
        string="Width (cm)",
        help="Product width in centimetres.",
    )
    mdl_height_cm = fields.Float(
        string="Height (cm)",
        help="Product height in centimetres.",
    )

    mdl_catalog_allowed = fields.Boolean(
        string="Catalog Combination Allowed (Technical)",
        default=True,
        index=True,
        copy=False,
        help=(
            "Technical compatibility field for migrated data whose rule "
            "cannot be represented by Odoo's native pair exclusions."
        ),
    )
    mdl_generated_name = fields.Char(
        string="Generated Product Name (Technical)",
        compute="_compute_mdl_catalog_values",
        store=True,
        translate=True,
        index="trigram",
    )
    mdl_variant_list_name = fields.Char(
        string="Product List Name (Technical)",
        compute="_compute_mdl_variant_list_name",
        help=(
            "Odoo's display name without the Internal Reference, used where "
            "the variant list already shows the SKU in a separate column."
        ),
    )

    @api.depends("display_name")
    @api.depends_context("lang")
    def _compute_mdl_variant_list_name(self):
        for product in self:
            product.mdl_variant_list_name = product.with_context(
                display_default_code=False,
                mdl_hide_default_code=True,
            ).display_name

    @api.depends(
        "product_tmpl_id.mdl_catalog_managed",
        "product_tmpl_id.mdl_sku_prefix",
        "product_tmpl_id.mdl_group_default_name",
        "product_tmpl_id.mdl_name_suffix",
        "product_tmpl_id.attribute_line_ids.sequence",
        "product_tmpl_id.attribute_line_ids.mdl_name_suffix",
        "product_template_attribute_value_ids",
        "product_template_attribute_value_ids.attribute_id.name",
        "product_template_attribute_value_ids.product_attribute_value_id.name",
        "product_template_attribute_value_ids.mdl_name_component_override",
    )
    def _compute_mdl_catalog_values(self):
        for product in self:
            template = product.product_tmpl_id
            if not template.mdl_catalog_managed:
                product.mdl_generated_name = False
                continue
            _sku, name, _missing = template._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            # False on a translated Char clears every language. A managed
            # product may deliberately have no configured name in this one.
            product.mdl_generated_name = name or ""

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
            or vals.get("active") is True
        ):
            # ``product_variant_ids`` normally hides archived products.  A
            # variant can therefore retain an obsolete generated reference
            # while archived.  Re-check it when Odoo reactivates the record;
            # source changes are also propagated to archived variants by the
            # template-level synchronizer.
            self._mdl_sync_default_code()
        return result

    def _unlink_or_archive(self, check_access=True):
        if self.env.context.get("mdl_preserve_variant_ids"):
            # Keep Odoo 19's security contract even though this migration
            # context deliberately archives instead of attempting deletion.
            # The explicit checks run as the caller; only the final archive
            # uses sudo to avoid cross-company recompute/access failures, just
            # like Odoo's native ``_unlink_or_archive`` implementation.
            if check_access:
                self.check_access("unlink")
                self.check_access("write")
            self.sudo().with_context(skip_mdl_catalog_sync=True).write(
                {"active": False}
            )
            return
        return super()._unlink_or_archive(check_access=check_access)

    def _mdl_sync_default_code(self):
        for product in self:
            template = product.product_tmpl_id
            if not template.mdl_catalog_managed:
                continue
            if template.mdl_copy_requires_new_sku:
                # A native Duplicate keeps the catalog structure but must not
                # reuse internal references.  This guard also applies when an
                # archived copied variant is reactivated directly.
                if product.default_code:
                    product.with_context(skip_mdl_catalog_sync=True).write(
                        {"default_code": False}
                    )
                continue
            generated_sku, _name, missing = template._mdl_render_catalog_values(
                product.product_template_attribute_value_ids
            )
            desired_sku = generated_sku or False
            if not missing and product.default_code != desired_sku:
                product.with_context(skip_mdl_catalog_sync=True).write(
                    {"default_code": desired_sku}
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
        extra_domain &= Domain("mdl_effective_name", operator, name)
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
        "mdl_name_overrides",
        "product_tmpl_id.mdl_group_default_name",
        "product_tmpl_id.mdl_catalog_managed",
        "product_tmpl_id.mdl_sku_prefix",
    )
    @api.depends_context(
        "display_default_code",
        "mdl_hide_default_code",
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
        formatted_display_name = self.env.context.get(
            "formatted_display_name"
        )
        supplier_template_ids = set()
        partner_id = self.env.context.get("partner_id")
        if partner_id:
            partner = self.env["res.partner"].browse(partner_id).exists()
            partner_ids = (partner | partner.commercial_partner_id).ids
            supplier_domain = [
                ("product_tmpl_id", "in", self.product_tmpl_id.ids),
                ("partner_id", "in", partner_ids),
            ]
            if company_id := self.env.context.get("company_id"):
                supplier_domain.append(
                    ("company_id", "in", (company_id, False))
                )
            supplier_template_ids = set(
                self.env["product.supplierinfo"]
                .sudo()
                .search(supplier_domain)
                .product_tmpl_id.ids
            )
        # Odoo intentionally hides the internal reference in several product
        # selectors (notably sales lines).  For managed catalog products the
        # reference is part of the user-facing final label and must remain
        # visible while searching and selecting a product.  The dedicated
        # variant list opts out explicitly because it already has a separate
        # internal-reference column.
        display_default_code = (
            self.env.context.get("display_default_code", True)
            or not self.env.context.get("mdl_hide_default_code")
        )
        display_format = self.env["ir.config_parameter"].sudo().get_param(
            VARIANT_DISPLAY_FORMAT_PARAM,
            DEFAULT_VARIANT_DISPLAY_FORMAT,
        )
        for product in self:
            if product.product_tmpl_id.id in supplier_template_ids:
                continue
            template = product.product_tmpl_id
            if not template.mdl_catalog_managed:
                continue

            # Render from the current template values instead of trusting the
            # stored helper fields.  This keeps selectors correct immediately
            # after an upgrade and while a batch recomputation is still being
            # flushed to the database.
            generated_sku, generated_name, missing = (
                template._mdl_render_catalog_values(
                    product.product_template_attribute_value_ids
                )
            )
            # Keep an intentionally empty configured name empty. Falling back
            # to the native label would reintroduce the unrelated group title.
            final_name = product.mdl_name_override or generated_name or ""
            final_sku = (
                generated_sku
                if generated_sku and not missing
                else product.default_code
            )
            # ``formatted_display_name`` is an Odoo web-client protocol, not
            # a request to fall back to the native template/attribute label.
            # The sales many2one widget splits this exact tab/marker format
            # into a readable name and reference.
            if formatted_display_name:
                product.display_name = (
                    f"{final_name}\t--{final_sku}--"
                    if display_default_code and final_sku
                    else final_name
                )
            elif display_default_code and final_sku:
                display_name, missing = render_format(
                    display_format or DEFAULT_VARIANT_DISPLAY_FORMAT,
                    {
                        "שם הפריט": final_name,
                        "Product Name": final_name,
                        "מק״ט": ltr_isolate(f"[{final_sku}]"),
                        "SKU": ltr_isolate(f"[{final_sku}]"),
                    },
                )
                product.display_name = (
                    display_name
                    if display_name and not missing
                    else clean_text(f"{ltr_isolate(f'[{final_sku}]')} {final_name}")
                )
            else:
                product.display_name = final_name
