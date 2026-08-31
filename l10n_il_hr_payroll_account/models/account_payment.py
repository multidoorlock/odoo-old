# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    il_spread_type = fields.Selection([
        ('planned', 'פריסה מתוכננת'),
        ('per_payslip', 'פריסה לפי תלוש'),
        ('none', 'פריסה מיידית'),
    ], string='אופן פריסת התשלום', default='none', required=True, tracking=True)
    il_split_line_ids = fields.One2many(
        'account.payment.split.line', 'payment_id', string='פריסת תשלום', copy=True)
    il_applied_amount = fields.Monetary(
        string='סכום שקוזז', compute='_compute_il_spread_amounts', store=True)
    il_remaining_amount = fields.Monetary(
        string='יתר למשיכה', compute='_compute_il_spread_amounts', store=True)
    il_planned_amount = fields.Monetary(
        string='סכום מתוכנן', compute='_compute_il_spread_amounts', store=True)
    il_is_employee_payment = fields.Boolean(
        string='תשלום לעובד', compute='_compute_il_is_employee_payment', store=True)
    il_currency_rounding = fields.Float(
        related='currency_id.rounding', readonly=True)

    @api.depends('partner_id', 'company_id')
    def _compute_il_is_employee_payment(self):
        for payment in self:
            payment.il_is_employee_payment = bool(payment._il_employee())

    @api.depends('amount', 'il_split_line_ids.amount', 'il_split_line_ids.payslip_id')
    def _compute_il_spread_amounts(self):
        for payment in self:
            payment.il_planned_amount = sum(payment.il_split_line_ids.mapped('amount'))
            payment.il_applied_amount = sum(
                payment.il_split_line_ids.filtered('payslip_id').mapped('amount'))
            payment.il_remaining_amount = payment.amount - payment.il_applied_amount

    def _il_employee(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env['hr.employee']
        return self.env['hr.employee'].with_context(active_test=False).search([
            ('work_contact_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _il_is_open_employee_payment(self):
        self.ensure_one()
        return bool(
            self._il_employee()
            and self.payment_type == 'outbound'
            and self.state not in ('draft', 'canceled')
            and self.currency_id.compare_amounts(self.il_remaining_amount, 0.0) > 0
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('il_spread_type', 'none') == 'per_payslip' and \
                    vals.get('il_split_line_ids'):
                raise ValidationError(
                    'בפריסה לפי תלוש רק התלוש רשאי ליצור שורות משיכה.')
        payments = super(AccountPayment, self.with_context(
            il_skip_spread_total_check=True,
            il_system_split_create=True)).create(vals_list)
        Split = self.env['account.payment.split.line']
        for payment in payments.filtered(
                lambda p: p._il_employee() and p.il_spread_type == 'none'
                and not p.il_split_line_ids):
            payslip_id = self.env.context.get('il_origin_payslip_id')
            Split.with_context(il_system_split_create=True).create({
                'payment_id': payment.id,
                'sequence': 1,
                'amount': payment.amount,
                'payslip_id': payslip_id,
            })
        for payment in payments.filtered(
                lambda p: p._il_employee() and p.il_spread_type == 'none'
                and p.il_split_line_ids):
            payment.il_split_line_ids[:1].with_context(
                il_sync_from_payment=True,
                il_skip_spread_total_check=True).amount = payment.amount
        payments._check_il_spread_complete()
        return payments

    def write(self, vals):
        old_types = {payment.id: payment.il_spread_type for payment in self}
        target = self.with_context(il_skip_spread_total_check=True) \
            if 'il_split_line_ids' in vals else self
        result = super(AccountPayment, target).write(vals)
        Split = self.env['account.payment.split.line']
        for payment in self.filtered(lambda p: p._il_employee()):
            if 'il_spread_type' in vals and old_types[payment.id] != payment.il_spread_type:
                if payment.il_split_line_ids.filtered('payslip_id'):
                    raise ValidationError(
                        'לא ניתן לשנות את אופן הפריסה לאחר שקוזז סכום בתלוש.')
                payment.il_split_line_ids.with_context(il_system_split_unlink=True).unlink()
                if payment.il_spread_type == 'none':
                    Split.with_context(il_system_split_create=True).create({
                        'payment_id': payment.id, 'sequence': 1, 'amount': payment.amount})
            elif ('amount' in vals and payment.il_spread_type == 'none'
                    and not self.env.context.get('il_sync_from_line')):
                line = payment.il_split_line_ids[:1]
                if line:
                    line.with_context(il_sync_from_payment=True).amount = payment.amount
                else:
                    Split.with_context(il_system_split_create=True).create({
                        'payment_id': payment.id, 'sequence': 1, 'amount': payment.amount})
        if 'il_split_line_ids' in vals:
            self._il_resequence_split_lines()
        if 'amount' in vals or 'il_split_line_ids' in vals:
            self._check_il_spread_complete()
        return result

    @api.constrains('amount', 'il_applied_amount', 'il_remaining_amount')
    def _check_il_remaining_amount(self):
        for payment in self:
            if payment.currency_id.compare_amounts(payment.il_remaining_amount, 0.0) < 0:
                raise ValidationError('אסור למשוך מתשלום סכום הגבוה מסכום התשלום.')
            if payment.currency_id.compare_amounts(
                    payment.il_remaining_amount, payment.amount) > 0:
                raise ValidationError('יתרת המשיכה אינה יכולה להיות גבוהה מסכום התשלום.')

    def _check_il_spread_complete(self):
        SplitLine = self.env['account.payment.split.line']
        for payment in self.filtered(lambda p: p._il_employee()):
            # Read the authoritative rows with a fresh search.  During an
            # editable one2many write, ``account.payment.write`` is executed on
            # a context-wrapped recordset and the original payment record may
            # still cache the pre-edit one2many value.  Validating that stale
            # cache made a visible 5 x 1,200 distribution fail against 6,000.
            lines = SplitLine.search(
                [('payment_id', '=', payment.id)], order='sequence, id')
            lines.invalidate_recordset(['amount', 'sequence', 'payment_id'])
            planned_amount = sum(lines.mapped('amount'))
            if payment.il_spread_type in ('planned', 'none') and \
                    payment.currency_id.compare_amounts(
                        planned_amount, payment.amount):
                digits = payment.currency_id.decimal_places
                raise ValidationError(
                    'בפריסה מתוכננת או בפריסה מיידית, סכום השורות חייב להיות '
                    'שווה לסכום התשלום. השרת קרא סכום תשלום של '
                    f'{payment.amount:.{digits}f} וסכום שורות של '
                    f'{planned_amount:.{digits}f} ({len(lines)} שורות).')
            if payment.il_spread_type == 'none' and len(lines) != 1:
                raise ValidationError('במצב פריסה מיידית חייבת להיות שורת פריסה אחת בדיוק.')
            if payment.il_spread_type == 'planned':
                sequences = lines.mapped('sequence')
                if sequences != list(range(1, len(sequences) + 1)):
                    raise ValidationError('מספרי הפעימות חייבים להיות רציפים ולהתחיל ב־1.')

    def action_post(self):
        self._check_il_spread_complete()
        return super().action_post()

    def _il_resequence_split_lines(self):
        SplitLine = self.env['account.payment.split.line']
        for payment in self:
            # Do not use payment.il_split_line_ids here: immediately after an
            # x2many edit it may still contain the pre-edit cached recordset.
            ordered = SplitLine.search(
                [('payment_id', '=', payment.id)], order='sequence, id')
            # Temporary values avoid unique(payment, sequence) collisions.
            for offset, line in enumerate(ordered, 1):
                line.with_context(
                    il_system_resequence=True,
                    il_skip_spread_total_check=True).sequence = 1000000 + offset
            for sequence, line in enumerate(ordered, 1):
                line.with_context(
                    il_system_resequence=True,
                    il_skip_spread_total_check=True).sequence = sequence
