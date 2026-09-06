# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    il_employee_payment_id = fields.Many2one(
        'account.payment', string='תשלום עובד', copy=False,
        check_company=True, index='btree_not_null', ondelete='restrict')
    il_employee_payment_split_line_id = fields.Many2one(
        'account.payment.split.line', string='שורת פיצול תשלום עובד',
        copy=False, check_company=True, index='btree_not_null',
        ondelete='set null')

    _unique_employee_payment_split_move = models.Constraint(
        'UNIQUE(il_employee_payment_split_line_id)',
        'ניתן ליצור פקודת יומן אחת בלבד לכל שורת פיצול תשלום עובד.')
