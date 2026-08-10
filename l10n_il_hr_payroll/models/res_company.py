from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_il_deduction_file_no = fields.Char(
        string="תיק ניכויים",
        help="מספר תיק הניכויים של המעסיק ברשות המסים. משמש בטופס 101 ובדיווחי 102/126.",
    )
