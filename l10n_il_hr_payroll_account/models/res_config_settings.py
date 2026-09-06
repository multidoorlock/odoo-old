# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    il_employee_payment_debit_account_id = fields.Many2one(
        related='company_id.il_employee_payment_debit_account_id',
        readonly=False)
    il_employee_payment_credit_account_id = fields.Many2one(
        related='company_id.il_employee_payment_credit_account_id',
        readonly=False)
