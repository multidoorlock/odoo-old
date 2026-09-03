# -*- coding: utf-8 -*-
from odoo import api, fields, models


class IlPaymentCycleType(models.Model):
    _name = 'il.payment.cycle.type'
    _description = 'Payment Cycle Type'
    _order = 'name'

    name = fields.Char(string='שם', required=True, translate=True)
    recurrence = fields.Selection([
        ('week', 'שבוע'),
        ('two_weeks', 'שבועיים'),
        ('three_weeks', 'שלושה שבועות'),
        ('month', 'חודש'),
        ('two_months', 'חודשיים'),
        ('three_months', 'שלושה חודשים'),
        ('half_year', 'חצי שנה'),
        ('year', 'שנה'),
    ], string='חזרה', required=True, default='month')
    cancel_payments = fields.Boolean(string='ביטול תשלומים')
    batch_payment_ids = fields.One2many(
        'account.batch.payment', 'il_payment_cycle_type_id', string='מחזורי תשלומים')
    batch_payment_count = fields.Integer(compute='_compute_batch_payment_count')

    @api.depends('batch_payment_ids')
    def _compute_batch_payment_count(self):
        for record in self:
            record.batch_payment_count = len(record.batch_payment_ids)

    def action_open_batches(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.action_il_payment_cycles')
        action['domain'] = [('il_payment_cycle_type_id', '=', self.id)]
        action['context'] = {'search_default_il_payment_cycle_type_id': self.id}
        return action


class HrEmployeePaymentCycleTypeLine(models.Model):
    _name = 'hr.employee.payment.cycle.type.line'
    _description = 'Employee Payment Cycle Type'
    _order = 'cycle_type_id'

    employee_id = fields.Many2one(
        'hr.employee', required=True, ondelete='cascade', index=True)
    cycle_type_id = fields.Many2one(
        'il.payment.cycle.type', string='סוג', required=True, ondelete='cascade', index=True)
    amount = fields.Monetary(string='סכום', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', related='employee_id.company_id.currency_id', readonly=True)

    _employee_cycle_type_unique = models.Constraint(
        'UNIQUE(employee_id, cycle_type_id)',
        'לא ניתן להגדיר את אותו סוג מחזור תשלום פעמיים לאותו עובד.')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    il_payment_cycle_type_line_ids = fields.One2many(
        'hr.employee.payment.cycle.type.line', 'employee_id',
        string='סוגי מחזורי תשלום')


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    il_payment_cycle_type_id = fields.Many2one(
        'il.payment.cycle.type', string='סוג מחזור תשלום',
        ondelete='restrict', index=True, copy=False)
