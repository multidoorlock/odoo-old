# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IlPaymentCycleWizard(models.TransientModel):
    _name = 'il.payment.cycle.wizard'
    _description = 'Create Payment Cycles'

    step = fields.Selection([('details', 'פרטים'), ('employees', 'עובדים')], default='details')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    cycle_type_ids = fields.Many2many(
        'il.payment.cycle.type', string='סוגי מחזורי תשלומים', required=True)
    batch_type = fields.Selection(
        [('outbound', 'יוצא')], string='כיוון', default='outbound', required=True, readonly=True)
    journal_id = fields.Many2one(
        'account.journal', string='בנק', required=True,
        domain="[('type', '=', 'bank')]", check_company=True)
    date = fields.Date(string='תאריך', required=True, default=fields.Date.context_today)
    name = fields.Char(string='שם', required=True)
    payment_method_id = fields.Many2one(
        'account.payment.method', string='אמצעי תשלום', required=True,
        domain="[('id', 'in', available_payment_method_ids)]")
    available_payment_method_ids = fields.Many2many(
        'account.payment.method', compute='_compute_available_payment_method_ids')
    employee_line_ids = fields.One2many(
        'il.payment.cycle.wizard.line', 'wizard_id', string='עובדים רלוונטיים')
    matrix_data = fields.Json(compute='_compute_matrix_data')

    @api.depends('employee_line_ids.amount', 'employee_line_ids.partner_bank_id',
                 'employee_line_ids.applicable', 'cycle_type_ids')
    def _compute_matrix_data(self):
        for wizard in self:
            employees = []
            for employee in wizard.employee_line_ids.mapped('employee_id').sorted('name'):
                lines = wizard.employee_line_ids.filtered(
                    lambda item: item.employee_id == employee)
                amounts = []
                for cycle_type in wizard.cycle_type_ids.sorted('name'):
                    line = lines.filtered(
                        lambda item: item.cycle_type_id == cycle_type)[:1]
                    amounts.append({
                        'type_id': cycle_type.id,
                        'amount': line.amount or 0.0,
                        'applicable': bool(line.applicable),
                    })
                employees.append({
                    'id': employee.id,
                    'name': employee.name,
                    'bank_id': lines[:1].partner_bank_id.id or False,
                    'banks': [{'id': bank.id, 'name': bank.display_name}
                              for bank in employee.bank_account_ids],
                    'amounts': amounts,
                })
            wizard.matrix_data = {
                'types': [{'id': item.id, 'name': item.name}
                          for item in wizard.cycle_type_ids.sorted('name')],
                'employees': employees,
            }

    def update_matrix_value(self, employee_id, cycle_type_id=False,
                            amount=False, bank_id=False):
        self.ensure_one()
        lines = self.employee_line_ids.filtered(
            lambda line: line.employee_id.id == employee_id)
        if bank_id is not False:
            lines.write({'partner_bank_id': bank_id or False})
        if cycle_type_id:
            line = lines.filtered(
                lambda item: item.cycle_type_id.id == cycle_type_id)
            if line and line.applicable:
                line.amount = amount
        return True

    @api.depends('journal_id')
    def _compute_available_payment_method_ids(self):
        for wizard in self:
            lines = wizard.journal_id._get_available_payment_method_lines('outbound')
            wizard.available_payment_method_ids = lines.mapped('payment_method_id')

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        if self.payment_method_id not in self.available_payment_method_ids:
            self.payment_method_id = self.available_payment_method_ids[:1]

    def action_next(self):
        self.ensure_one()
        if not self.cycle_type_ids:
            raise UserError(_('יש לבחור לפחות סוג מחזור תשלום אחד.'))
        configs = self.env['hr.employee.payment.cycle.type.line'].search([
            ('cycle_type_id', 'in', self.cycle_type_ids.ids),
            ('employee_id.active', '=', True),
            ('employee_id.company_id', '=', self.env.company.id),
        ])
        employees = configs.mapped('employee_id')
        if not employees:
            raise UserError(_('לא נמצאו עובדים שמוגדר להם אחד מסוגי מחזורי התשלום שנבחרו.'))
        config_by_key = {
            (line.employee_id.id, line.cycle_type_id.id): line for line in configs
        }
        commands = [Command.clear()]
        for employee in employees.sorted('name'):
            bank = employee.primary_bank_account_id or employee.bank_account_ids[:1]
            for cycle_type in self.cycle_type_ids.sorted('name'):
                config = config_by_key.get((employee.id, cycle_type.id))
                commands.append(Command.create({
                    'employee_id': employee.id,
                    'cycle_type_id': cycle_type.id,
                    'applicable': bool(config),
                    'amount': config.amount if config else 0.0,
                    'partner_bank_id': bank.id,
                }))
        self.write({'step': 'employees', 'employee_line_ids': commands})
        return self._reopen()

    def action_previous(self):
        self.ensure_one()
        self.step = 'details'
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'יצירת מחזורי תשלומים',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_cycles(self):
        self.ensure_one()
        applicable_lines = self.employee_line_ids.filtered('applicable')
        invalid = applicable_lines.filtered(lambda line: line.amount <= 0)
        if invalid:
            raise ValidationError(_('הסכום לכל עובד וסוג רלוונטי חייב להיות גדול מאפס.'))
        missing_partner = applicable_lines.filtered(lambda line: not line.employee_id.work_contact_id)
        if missing_partner:
            raise ValidationError(_('לעובדים הבאים אין איש קשר לעבודה: %s') %
                                  ', '.join(missing_partner.mapped('employee_id.name')))
        method_line = self.journal_id._get_available_payment_method_lines('outbound').filtered(
            lambda line: line.payment_method_id == self.payment_method_id)[:1]
        if not method_line:
            raise ValidationError(_('אמצעי התשלום אינו זמין לתשלומים יוצאים בבנק שנבחר.'))

        batches = self.env['account.batch.payment']
        Payment = self.env['account.payment']
        for cycle_type in self.cycle_type_ids:
            lines = applicable_lines.filtered(lambda line: line.cycle_type_id == cycle_type)
            payments = Payment
            for line in lines:
                payment = Payment.create({
                    'payment_type': 'outbound',
                    'partner_type': 'supplier',
                    'partner_id': line.employee_id.work_contact_id.id,
                    'partner_bank_id': line.partner_bank_id.id,
                    'journal_id': self.journal_id.id,
                    'date': self.date,
                    'amount': line.amount,
                    'currency_id': self.journal_id.currency_id.id or self.env.company.currency_id.id,
                    'payment_method_line_id': method_line.id,
                    'il_spread_type': 'none',
                    'memo': '%s - %s' % (self.name, cycle_type.name),
                })
                payment.action_post()
                payments |= payment
            batch = self.env['account.batch.payment'].create({
                'name': '%s - %s' % (self.name, cycle_type.name),
                'date': self.date,
                'journal_id': self.journal_id.id,
                'batch_type': 'outbound',
                'payment_method_id': self.payment_method_id.id,
                'il_payment_cycle_type_id': cycle_type.id,
                'payment_ids': [Command.set(payments.ids)],
            })
            if cycle_type.cancel_payments:
                payments.action_cancel()
            batches |= batch
        if not batches:
            raise UserError(_('לא נוצרו תשלומים.'))
        return {
            'type': 'ir.actions.act_window',
            'name': 'מחזורי תשלומים',
            'res_model': 'account.batch.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', batches.ids)],
        }


class IlPaymentCycleWizardLine(models.TransientModel):
    _name = 'il.payment.cycle.wizard.line'
    _description = 'Payment Cycle Employee Amount'
    _order = 'employee_id, cycle_type_id'

    wizard_id = fields.Many2one('il.payment.cycle.wizard', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='עובד', required=True, readonly=True)
    employee_partner_id = fields.Many2one(
        'res.partner', related='employee_id.work_contact_id', readonly=True)
    cycle_type_id = fields.Many2one(
        'il.payment.cycle.type', string='סוג', required=True, readonly=True)
    applicable = fields.Boolean(string='רלוונטי', readonly=True)
    amount = fields.Monetary(string='סכום', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', related='wizard_id.journal_id.company_id.currency_id', readonly=True)
    partner_bank_id = fields.Many2one(
        'res.partner.bank', string='חשבון בנק',
        domain="[('partner_id', '=', employee_partner_id)]")
