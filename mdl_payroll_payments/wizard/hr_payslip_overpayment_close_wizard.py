# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

# מצבי Payment שנחשבים "בוצע" — Draft ו-Canceled אינם משתתפים.
IL_EFFECTIVE_PAYMENT_STATES = ('in_process', 'paid')


class HrPayslipOverpaymentCloseWizard(models.TransientModel):
    """סגירת תשלום יתר ממחזורים קודמים לתשלוש שזקוק לתשלום (סעיפים 37–51)."""
    _name = 'hr.payslip.overpayment.close.wizard'
    _description = 'סגירת תשלום יתר'

    target_payslip_id = fields.Many2one(
        'hr.payslip', string='תלוש יעד', required=True, readonly=True)
    employee_id = fields.Many2one(
        related='target_payslip_id.employee_id', readonly=True)
    company_id = fields.Many2one(
        related='target_payslip_id.company_id', readonly=True)
    currency_id = fields.Many2one(
        related='target_payslip_id.currency_id', readonly=True)
    target_amount_due = fields.Monetary(
        string='נטו לתשלום ביעד', related='target_payslip_id.il_net_amount_to_pay',
        readonly=True)
    available_overpayment = fields.Monetary(
        string='סה"כ תשלום יתר זמין', compute='_compute_available_overpayment')
    selected_available_amount = fields.Monetary(
        string='סכום זמין נבחר', compute='_compute_selected_amounts')
    amount_to_close = fields.Monetary(
        string='סכום לסגירה', compute='_compute_selected_amounts')
    amount_allocated = fields.Monetary(
        string='סכום שהוקצה', compute='_compute_selected_amounts')
    difference = fields.Monetary(
        string='הפרש', compute='_compute_selected_amounts')
    state = fields.Selection([
        ('select', 'בחירה'),
        ('split', 'חלוקה'),
    ], default='select', required=True)
    partial_close_warning = fields.Char(compute='_compute_selected_amounts')
    line_ids = fields.One2many(
        'hr.payslip.overpayment.close.wizard.line', 'wizard_id', string='שורות')

    @api.depends('line_ids.available_amount')
    def _compute_available_overpayment(self):
        for wizard in self:
            wizard.available_overpayment = sum(wizard.line_ids.mapped('available_amount'))

    @api.depends('line_ids.selected', 'line_ids.available_amount',
                 'line_ids.amount_to_use', 'target_amount_due')
    def _compute_selected_amounts(self):
        for wizard in self:
            selected = wizard.line_ids.filtered('selected')
            selected_available = sum(selected.mapped('available_amount'))
            amount_to_close = min(wizard.target_amount_due, selected_available)
            wizard.selected_available_amount = selected_available
            wizard.amount_to_close = amount_to_close
            wizard.amount_allocated = sum(selected.mapped('amount_to_use'))
            wizard.difference = amount_to_close - wizard.amount_allocated
            if selected_available and selected_available < wizard.target_amount_due:
                wizard.partial_close_warning = (
                    'התשלומים שנבחרו אינם מספיקים לסגירת מלוא היתרה לתשלום. '
                    'ייסגרו %.2f ₪ ותיוותר יתרה של %.2f ₪ לתשלום.' % (
                        selected_available, wizard.target_amount_due - selected_available))
            else:
                wizard.partial_close_warning = False

    def _populate_lines(self):
        self.ensure_one()
        target = self.target_payslip_id
        candidate_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', target.employee_id.id),
            ('company_id', '=', target.company_id.id),
            ('id', '!=', target.id),
            ('state', 'in', ('validated', 'paid')),
        ]).filtered(lambda s: s.il_overpayment_balance > 0 and s.currency_id == target.currency_id)
        lines = []
        for source in candidate_payslips:
            payments = self.env['account.payment'].search([
                ('payslip_id', '=', source.id),
                ('state', 'in', IL_EFFECTIVE_PAYMENT_STATES),
                ('company_id', '=', target.company_id.id),
                ('currency_id', '=', target.currency_id.id),
            ])
            for payment in payments:
                available = payment.amount - sum(payment.payslip_allocation_ids.mapped('amount'))
                if target.currency_id.compare_amounts(available, 0.0) <= 0:
                    continue
                lines.append((0, 0, {
                    'payment_id': payment.id,
                    'source_payslip_id': source.id,
                }))
        self.line_ids = [(5, 0, 0)] + lines

    def action_next(self):
        self.ensure_one()
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise UserError('יש לבחור לפחות תשלום אחד.')
        rounding = self.currency_id.rounding or 0.01
        if self.amount_to_close <= 0:
            raise UserError('אין סכום זמין לסגירה מהתשלומים שנבחרו.')
        if self.selected_available_amount <= self.amount_to_close + rounding / 2:
            # סגירה מלאה או חלקית — כל תשלום נבחר נצרך במלואו אוטומטית.
            for line in selected:
                line.amount_to_use = line.available_amount
            (self.line_ids - selected).write({'amount_to_use': 0.0})
            return self._action_confirm()
        # הסכום הזמין עולה על הנדרש — נדרשת חלוקה ידנית של המשתמש.
        selected.write({'amount_to_use': 0.0})
        (self.line_ids - selected).write({'selected': False, 'amount_to_use': 0.0})
        self.state = 'split'
        return self._reopen()

    def action_back_to_select(self):
        self.ensure_one()
        self.state = 'select'
        self.line_ids.write({'amount_to_use': 0.0})
        return self._reopen()

    def action_confirm_split(self):
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        selected = self.line_ids.filtered('selected')
        if abs(self.difference) > rounding / 2:
            raise UserError(
                'סכום החלוקה (%.2f ₪) חייב להיות שווה בדיוק לסכום לסגירה (%.2f ₪).'
                % (self.amount_allocated, self.amount_to_close))
        for line in selected:
            if line.amount_to_use and self.currency_id.compare_amounts(
                    line.amount_to_use, 0.0) < 0:
                raise UserError('סכום שלילי אינו קביל בשורת חלוקה.')
        return self._action_confirm()

    def _action_confirm(self):
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        selected = self.line_ids.filtered(
            lambda l: l.selected and self.currency_id.compare_amounts(l.amount_to_use, 0.0) > 0)
        if not selected:
            raise UserError('אין סכום לשיוך.')
        # אכיפה: לא לעבור את יתרת התשלום יתר של אף Source Payslip, ולא
        # את סכום התשלום הזמין של אף Payment.
        per_source = {}
        for line in selected:
            if self.currency_id.compare_amounts(line.amount_to_use, line.available_amount) > 0:
                raise UserError('לא ניתן להשתמש בסכום גדול מהזמין בתשלום %s.' % line.payment_id.name)
            per_source[line.source_payslip_id] = per_source.get(line.source_payslip_id, 0.0) + line.amount_to_use
        for source_payslip, amount in per_source.items():
            if amount - source_payslip.il_overpayment_balance > rounding / 2:
                raise UserError(
                    'לא ניתן לסגור מתלוש %s סכום גדול מיתרת התשלום ביתר שלו.'
                    % source_payslip.display_name)
        Allocation = self.env['account.payment.payslip.allocation']
        for line in selected:
            Allocation.create({
                'payment_id': line.payment_id.id,
                'payslip_id': self.target_payslip_id.id,
                'amount': line.amount_to_use,
            })
        return {'type': 'ir.actions.act_window_close'}

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'סגירת תשלום יתר',
            'res_model': 'hr.payslip.overpayment.close.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class HrPayslipOverpaymentCloseWizardLine(models.TransientModel):
    _name = 'hr.payslip.overpayment.close.wizard.line'
    _description = 'שורת סגירת תשלום יתר'

    wizard_id = fields.Many2one(
        'hr.payslip.overpayment.close.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(string='נבחר')
    payment_id = fields.Many2one('account.payment', string='תשלום', readonly=True)
    source_payslip_id = fields.Many2one('hr.payslip', string='תלוש מקור', readonly=True)
    payment_date = fields.Date(related='payment_id.date', readonly=True)
    payment_amount = fields.Monetary(related='payment_id.amount', readonly=True)
    currency_id = fields.Many2one(related='payment_id.currency_id', readonly=True)
    available_amount = fields.Monetary(
        string='סכום זמין', compute='_compute_available_amount')
    amount_to_use = fields.Monetary(string='סכום לשימוש')

    @api.depends('payment_id.amount', 'payment_id.payslip_allocation_ids.amount')
    def _compute_available_amount(self):
        for line in self:
            payment = line.payment_id
            line.available_amount = payment.amount - sum(
                payment.payslip_allocation_ids.mapped('amount')) if payment else 0.0
