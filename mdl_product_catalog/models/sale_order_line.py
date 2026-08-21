from odoo import api, models

from .catalog_utils import clean_text


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.depends(
        "product_id",
        "product_id.mdl_generated_name",
        "linked_line_id",
        "linked_line_ids",
    )
    def _compute_name(self):
        super()._compute_name()
        for line in self:
            final_name = clean_text(line.product_id.mdl_generated_name)
            if not final_name:
                continue
            description_lines = (line.name or "").splitlines()
            if description_lines:
                description_lines[0] = final_name
            else:
                description_lines = [final_name]
            line.name = "\n".join(description_lines)
