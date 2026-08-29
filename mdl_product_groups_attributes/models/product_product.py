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
        string="שטח מוגן מרבי (מ״ר)",
        help="נתון טכני של הפריט; אינו יוצר וריאנטים חדשים.",
    )
    mdl_installation_type = fields.Selection(
        selection=[
            ("overhead", "עילית"),
            ("concealed", "סמויה"),
            ("other", "אחר"),
        ],
        string="סוג התקנה",
        help="נתון טכני של הפריט; אינו חלק משם המוצר.",
    )
    mdl_length_cm = fields.Float(
        string="אורך (ס״מ)",
        help="אורך הפריט בסנטימטרים.",
    )
    mdl_width_cm = fields.Float(
        string="רוחב (ס״מ)",
        help="רוחב הפריט בסנטימטרים.",
    )
    mdl_height_cm = fields.Float(
        string="גובה (ס״מ)",
        help="גובה הפריט בסנטימטרים.",
    )

    mdl_catalog_allowed = fields.Boolean(
        string="שילוב קטלוג מותר (טכני)",
        default=True,
        index=True,
        copy=False,
        help=(
            "שדה טכני לנתונים מוסבים שבהם כלל השילוב אינו ניתן לביטוי "
            "באמצעות ההחרגות הזוגיות של Odoo."
        ),
    )
    mdl_generated_name = fields.Char(
        string="שם הפריט",
        compute="_compute_mdl_catalog_values",
        store=True,
        index="trigram",
    )

    @api.depends(
        "product_tmpl_id.mdl_catalog_managed",
        "product_tmpl_id.mdl_sku_prefix",
        "product_tmpl_id.mdl_effective_base_name",
        "product_tmpl_id.mdl_name_suffix",
        "product_tmpl_id.attribute_line_ids.sequence",
        "product_tmpl_id.attribute_line_ids.mdl_name_mode",
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
        "product_tmpl_id.mdl_catalog_managed",
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
        if (
            self.env.context.get("seller_id")
            or self.env.context.get("formatted_display_name")
        ):
            return
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
        display_default_code = self.env.context.get("display_default_code", True)
        display_format = self.env["ir.config_parameter"].sudo().get_param(
            VARIANT_DISPLAY_FORMAT_PARAM,
            DEFAULT_VARIANT_DISPLAY_FORMAT,
        )
        for product in self:
            if product.product_tmpl_id.id in supplier_template_ids:
                continue
            if not (
                product.product_tmpl_id.mdl_catalog_managed
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
