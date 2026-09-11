# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IlPaymentCycleWizard(models.TransientModel):
    _name = 'il.payment.cycle.wizard'
    _description = 'Create Payment Cycle'

    step = fields.Selection(
        [
            ('details', 'פרטים'),
            ('selection', 'בחירת עובדים'),
            ('amounts', 'סכומים'),
        ], default='details')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    cycle_type_ids = fields.Many2many(
        'il.payment.cycle.type', string='סוגי מחזורי תשלומים', required=True)
    batch_type = fields.Selection(
        [('outbound', 'יוצא')], string='כיוון', default='outbound',
        required=True, readonly=True)
    journal_id = fields.Many2one(
        'account.journal', string='בנק', required=True,
        domain="[('type', '=', 'bank')]", check_company=True)
    date = fields.Date(
        string='תאריך', required=True, default=fields.Date.context_today)
    name = fields.Char(string='שם', required=True)
    payment_method_id = fields.Many2one(
        'account.payment.method', string='אמצעי תשלום', required=True,
        domain="[('id', 'in', available_payment_method_ids)]")
    available_payment_method_ids = fields.Many2many(
        'account.payment.method', compute='_compute_available_payment_method_ids')
    employee_line_ids = fields.One2many(
        'il.payment.cycle.wizard.line', 'wizard_id', string='עובדים רלוונטיים')
    employee_selection_line_ids = fields.One2many(
        'il.payment.cycle.wizard.employee.line', 'wizard_id',
        string='בחירת עובדים')

    @api.depends('journal_id')
    def _compute_available_payment_method_ids(self):
        for wizard in self:
            lines = wizard.journal_id._get_available_payment_method_lines(
                'outbound')
            wizard.available_payment_method_ids = lines.mapped(
                'payment_method_id')

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        if self.payment_method_id not in self.available_payment_method_ids:
            self.payment_method_id = self.available_payment_method_ids[:1]

    def action_next(self):
        self.ensure_one()
        if self.step == 'selection':
            return self._action_prepare_amounts()

        cycle_types = self.cycle_type_ids.sorted('name')
        if not cycle_types:
            raise UserError(_('יש לבחור לפחות סוג מחזור תשלום אחד.'))
        configs = self.env['hr.employee.payment.cycle.type.line'].search([
            ('cycle_type_id', 'in', cycle_types.ids),
            ('employee_id.active', '=', True),
            ('employee_id.company_id', '=', self.company_id.id),
        ])
        if not configs:
            raise UserError(_(
                'לא נמצאו עובדים שמוגדר להם אחד מסוגי מחזורי התשלום שנבחרו.'
            ))
        values = {
            'step': 'selection',
            'employee_selection_line_ids': [Command.clear()],
            'employee_line_ids': [Command.clear()],
        }
        employees = configs.mapped('employee_id').sorted(
            key=lambda employee: (employee.name or '', employee.id))
        for sequence, employee in enumerate(employees, start=1):
            employee_types = configs.filtered(
                lambda config: config.employee_id == employee
            ).mapped('cycle_type_id').sorted('name')
            values['employee_selection_line_ids'].append(Command.create({
                'sequence': sequence,
                'selected': True,
                'employee_id': employee.id,
                'cycle_type_ids': [Command.set(employee_types.ids)],
            }))
        self.write(values)
        return self._reopen()

    def _action_prepare_amounts(self):
        self.ensure_one()
        selected_employees = self.employee_selection_line_ids.filtered(
            'selected').mapped('employee_id')
        if not selected_employees:
            raise ValidationError(_('יש לבחור לפחות עובד אחד.'))
        configs = self.env['hr.employee.payment.cycle.type.line'].search([
            ('employee_id', 'in', selected_employees.ids),
            ('cycle_type_id', 'in', self.cycle_type_ids.ids),
            ('employee_id.active', '=', True),
            ('employee_id.company_id', '=', self.company_id.id),
        ])
        commands = [Command.clear()]
        ordered_configs = configs.sorted(
            key=lambda line: (
                line.employee_id.name or '', line.cycle_type_id.name or '',
                line.id,
            )
        )
        for sequence, config in enumerate(ordered_configs, start=1):
            employee = config.employee_id
            bank = employee.primary_bank_account_id or employee.bank_account_ids[:1]
            commands.append(Command.create({
                'sequence': sequence,
                'selected': True,
                'employee_id': employee.id,
                'cycle_type_id': config.cycle_type_id.id,
                'amount': config.amount,
                'partner_bank_id': bank.id,
            }))
        self.write({
            'step': 'amounts',
            'employee_line_ids': commands,
        })
        return self._reopen()

    def action_previous(self):
        self.ensure_one()
        self.step = 'selection' if self.step == 'amounts' else 'details'
        return self._reopen()

    def _reopen(self):
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_il_payment_cycle_wizard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': 'יצירת תשלום אצווה',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view.id,
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'dialog_size': 'extra-large',
                'il_payment_cycle_wizard_id': self.id,
                'active_model': self._name,
                'active_id': self.id,
            },
        }

    def action_create_cycles(self):
        self.ensure_one()
        selected_lines = self.employee_line_ids.filtered('selected')
        if not selected_lines:
            raise ValidationError(_('יש לבחור לפחות עובד אחד.'))
        missing_partner = selected_lines.filtered(
            lambda line: not line.employee_id.work_contact_id)
        if missing_partner:
            raise ValidationError(_(
                'לעובדים הבאים אין איש קשר לעבודה: %s',
                ', '.join(missing_partner.mapped('employee_id.name')),
            ))
        method_line = self.journal_id._get_available_payment_method_lines(
            'outbound').filtered(
                lambda line: line.payment_method_id == self.payment_method_id
            )[:1]
        if not method_line:
            raise ValidationError(_(
                'אמצעי התשלום אינו זמין לתשלומים יוצאים בבנק שנבחר.'
            ))

        payments = self.env['account.payment']
        payments_by_state = {
            state: self.env['account.payment']
            for state in ('draft', 'canceled', 'paid', 'in_process')
        }
        selected_types = self.env['il.payment.cycle.type']
        for line in selected_lines.sorted('sequence'):
            cycle_type = line.cycle_type_id
            selected_types |= cycle_type
            if line.amount <= 0:
                raise ValidationError(_(
                    'הסכום לעובד %s בסוג %s חייב להיות גדול מאפס.',
                    line.employee_id.name, cycle_type.name,
                ))
            payment = self.env['account.payment'].create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': line.employee_id.work_contact_id.id,
                'partner_bank_id': line.partner_bank_id.id,
                'journal_id': self.journal_id.id,
                'date': self.date,
                'amount': line.amount,
                'currency_id': (
                    self.journal_id.currency_id.id
                    or self.company_id.currency_id.id
                ),
                'payment_method_line_id': method_line.id,
                'il_payment_cycle_type_id': cycle_type.id,
                'memo': '%s - %s' % (self.name, cycle_type.name),
            })
            payments |= payment
            payments_by_state[cycle_type.payment_state] |= payment
        if not payments:
            raise UserError(_('לא נוצרו תשלומים.'))

        batch = self.env['account.batch.payment'].create({
            'name': self.name,
            'date': self.date,
            'journal_id': self.journal_id.id,
            'batch_type': 'outbound',
            'payment_method_id': self.payment_method_id.id,
            'il_payment_cycle_type_ids': [Command.set(selected_types.ids)],
            'payment_ids': [Command.set(payments.ids)],
        })
        payments_to_post = (
            payments_by_state['in_process'] | payments_by_state['paid'])
        if payments_to_post:
            payments_to_post.action_post()
        if payments_by_state['paid']:
            payments_by_state['paid'].action_validate()
        if payments_by_state['canceled']:
            payments_by_state['canceled'].action_cancel()
        return {
            'type': 'ir.actions.act_window',
            'name': 'תשלום אצווה',
            'res_model': 'account.batch.payment',
            'res_id': batch.id,
            'view_mode': 'form',
        }


class IlPaymentCycleWizardLine(models.TransientModel):
    _name = 'il.payment.cycle.wizard.line'
    _description = 'Payment Cycle Employee Amounts'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'il.payment.cycle.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=1, readonly=True)
    selected = fields.Boolean(string='נבחר', default=True)
    employee_id = fields.Many2one(
        'hr.employee', string='עובד', required=True, readonly=True)
    cycle_type_id = fields.Many2one(
        'il.payment.cycle.type', string='סוג', required=True, readonly=True)
    employee_partner_id = fields.Many2one(
        'res.partner', related='employee_id.work_contact_id', readonly=True)
    currency_id = fields.Many2one(
        'res.currency', related='wizard_id.company_id.currency_id', readonly=True)
    partner_bank_id = fields.Many2one(
        'res.partner.bank', string='חשבון בנק',
        domain="[('partner_id', '=', employee_partner_id)]")
    amount = fields.Monetary(
        string='סכום', required=True, currency_field='currency_id')


class IlPaymentCycleWizardEmployeeLine(models.TransientModel):
    _name = 'il.payment.cycle.wizard.employee.line'
    _description = 'Payment Cycle Employee Selection'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'il.payment.cycle.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=1, readonly=True)
    selected = fields.Boolean(string='נבחר', default=True)
    employee_id = fields.Many2one(
        'hr.employee', string='עובד', required=True, readonly=True)
    cycle_type_ids = fields.Many2many(
        'il.payment.cycle.type', 'il_cycle_wizard_employee_type_rel',
        'line_id', 'cycle_type_id', string='סוגים', readonly=True)
