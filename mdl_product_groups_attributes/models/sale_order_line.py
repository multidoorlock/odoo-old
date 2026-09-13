from odoo import api, models

from .catalog_utils import clean_text


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.depends(
        "product_id",
        "product_id.mdl_generated_name",
        "product_id.default_code",
        "linked_line_id",
        "linked_line_ids",
    )
    def _compute_name(self):
        super()._compute_name()
        for line in self:
            if not clean_text(line.product_id.mdl_generated_name):
                continue

            # The standard sale-line widget hides the first description line
            # only when it exactly matches the product label shown above it.
            # Keep that exact label (including the configured SKU format), so
            # only a real sales description remains visible below the product.
            product_label = clean_text(
                line.product_id.with_context(
                    display_default_code=True,
                    lang=line.order_id._get_lang(),
                ).display_name
            )
            description_lines = (line.name or "").splitlines()
            if description_lines:
                description_lines[0] = product_label
            else:
                description_lines = [product_label]
            line.name = "\n".join(description_lines)
