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
    il_masav_institution_number = fields.Char(
        related='company_id.il_masav_institution_number', readonly=False)
    il_masav_sender_number = fields.Char(
        related='company_id.il_masav_sender_number', readonly=False)
    il_masav_hebrew_code = fields.Selection(
        related='company_id.il_masav_hebrew_code', readonly=False)
