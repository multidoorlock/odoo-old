# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    il_hide_redundant_base = fields.Boolean(
        compute='_compute_il_hide_redundant_base', store=True)

    @api.depends('code', 'amount', 'quantity', 'rate', 'total',
                 'slip_id.gross_wage', 'currency_id')
    def _compute_il_hide_redundant_base(self):
        base_codes = {
            'IL_TAX_BASE', 'IL_NI_BASE', 'IL_PENSION_BASE',
            'IL_SEVERANCE_BASE', 'IL_STUDY_FUND_BASE',
            'IL_PAL_EQUALIZATION_BASE',
        }
        for line in self:
            currency = line.currency_id or line.slip_id.company_id.currency_id
            same_as_gross = (
                currency.compare_amounts(
                    line.total, line.slip_id.gross_wage) == 0
                if currency else line.total == line.slip_id.gross_wage
            )
            line.il_hide_redundant_base = (
                line.code in base_codes and same_as_gross)
