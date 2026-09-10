# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError


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
    payment_state = fields.Selection([
        ('draft', 'טיוטה'),
        ('canceled', 'בוטל'),
        ('paid', 'שולם'),
        ('in_process', 'בביצוע'),
    ], string='סטטוס תשלום ביצירה', required=True, default='in_process')
    batch_payment_ids = fields.Many2many(
        'account.batch.payment', 'il_batch_payment_cycle_type_rel',
        'cycle_type_id', 'batch_payment_id', string='מחזורי תשלומים')
    batch_payment_count = fields.Integer(compute='_compute_batch_payment_count')

    @api.depends('batch_payment_ids')
    def _compute_batch_payment_count(self):
        for record in self:
            record.batch_payment_count = len(record.batch_payment_ids)

    def action_open_batches(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.action_il_payment_cycles')
        action['domain'] = [('il_payment_cycle_type_ids', 'in', self.id)]
        action['context'] = {'search_default_il_payment_cycle_type_ids': self.id}
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

    il_grouped_payment_view_id = fields.Integer(
        compute='_compute_il_grouped_payment_view_id')

    def _compute_il_grouped_payment_view_id(self):
        view_id = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_il_batch_grouped_list'
        ).id
        for batch in self:
            batch.il_grouped_payment_view_id = view_id

    il_payment_cycle_type_ids = fields.Many2many(
        'il.payment.cycle.type', 'il_batch_payment_cycle_type_rel',
        'batch_payment_id', 'cycle_type_id', string='סוגי מחזור תשלום',
        copy=False)

    def action_il_open_grouped_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('תשלומים'),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'views': [(
                self.env.ref(
                    'l10n_il_hr_payroll_account.view_account_payment_il_batch_grouped_list'
                ).id,
                'list',
            ), (False, 'form')],
            'domain': [('batch_payment_id', '=', self.id)],
            'context': {
                'create': False,
                'delete': False,
                'form_view_initial_mode': 'edit',
            },
        }

    def action_il_create_masav_file(self):
        self.ensure_one()
        payments = self.payment_ids.filtered(
            lambda payment: payment.state in ('in_process', 'paid'))
        if not payments:
            raise UserError(_(
                'אין במחזור תשלומים בסטטוס לביצוע או שולם ליצירת קובץ מס״ב.'
            ))
        wizard = self.env['il.masav.export.wizard'].create({
            'batch_payment_id': self.id,
            'line_ids': [
                Command.create({'payment_id': payment.id, 'selected': True})
                for payment in payments
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('יצירת קובץ מס״ב'),
            'res_model': 'il.masav.export.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
