# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    il_batch_group = fields.Selection(
        [('payments', 'תשלומים')], string='קבוצת תשלומים',
        default='payments', required=True, readonly=True, index=True,
        copy=False)
    il_employee_id = fields.Many2one(
        'hr.employee', string='עובד', compute='_compute_il_employee_id',
        store=True, index=True)
    il_payment_cycle_type_id = fields.Many2one(
        'il.payment.cycle.type', string='סוג', readonly=True, copy=False,
        index=True)
    il_spread_type = fields.Selection([
        ('planned', 'פריסה מתוכננת'),
        ('none', 'פריסה מיידית'),
    ], string='אופן פריסת התשלום', default='none', required=True, tracking=True)
    il_split_line_ids = fields.One2many(
        'account.payment.split.line', 'payment_id', string='פריסת תשלום', copy=True)
    il_applied_amount = fields.Monetary(
        string='סכום שנסגר בתלושים', compute='_compute_il_spread_amounts', store=True)
    il_remaining_amount = fields.Monetary(
        string='יתרה לסגירה', compute='_compute_il_spread_amounts', store=True)
    il_planned_amount = fields.Monetary(
        string='סכום מתוכנן', compute='_compute_il_spread_amounts', store=True)
    il_currency_rounding = fields.Float(
        related='currency_id.rounding', readonly=True)
    il_is_employee_payment = fields.Boolean(
        string='תשלום לעובד', compute='_compute_il_is_employee_payment', store=True)
    il_payment_type_display = fields.Char(
        string='סוג תשלום', compute='_compute_il_payment_type_display')
    il_relevant_installment_number = fields.Integer(
        string='פעימה', compute='_compute_il_relevant_installment')
    il_relevant_installment_amount = fields.Monetary(
        string='סכום בפעימה', compute='_compute_il_relevant_installment',
        currency_field='currency_id')

    il_masav_file = fields.Binary(
        string='קובץ מס״ב', readonly=True, copy=False, attachment=True)
    il_masav_filename = fields.Char(
        string='שם קובץ מס״ב', readonly=True, copy=False)
    il_masav_generated_on = fields.Datetime(
        string='תאריך יצירת קובץ מס״ב', readonly=True, copy=False)

    @api.depends('payment_type')
    def _compute_il_payment_type_display(self):
        for payment in self:
            payment.il_payment_type_display = (
                'שלח' if payment.payment_type == 'outbound' else 'קבל')

    @api.depends_context('il_payslip_id')
    @api.depends(
        'il_split_line_ids.sequence', 'il_split_line_ids.amount',
        'il_split_line_ids.reconcile_id',
        'il_split_line_ids.il_pending_payslip_move_line_id',
    )
    def _compute_il_relevant_installment(self):
        payslip_id = self.env.context.get('il_payslip_id')
        for payment in self:
            payment.il_relevant_installment_number = 0
            payment.il_relevant_installment_amount = 0.0
            if not payslip_id:
                continue
            relevant_line = payment.il_split_line_ids.filtered(
                lambda line: (
                    line._il_target_payslip_move_line().il_payslip_id.id
                    == payslip_id
                )
            ).sorted(lambda line: (line.sequence, line.id))[:1]
            if relevant_line:
                payment.il_relevant_installment_number = relevant_line.sequence
                payment.il_relevant_installment_amount = relevant_line.amount

    def _il_employee(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env['hr.employee']
        return self.env['hr.employee'].with_context(active_test=False).search([
            ('work_contact_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _il_uses_employee_payment_accounting(self):
        self.ensure_one()
        return bool(
            self._il_employee()
            and self.payment_type == 'outbound'
            and self.partner_type == 'supplier'
        )

    @api.depends('partner_id', 'company_id')
    def _compute_il_employee_id(self):
        for payment in self:
            payment.il_employee_id = payment._il_employee()

    @api.depends('il_employee_id')
    def _compute_il_is_employee_payment(self):
        for payment in self:
            payment.il_is_employee_payment = bool(payment.il_employee_id)

    @api.depends(
        'amount', 'il_split_line_ids.amount',
        'il_split_line_ids.reconcile_id',
    )
    def _compute_il_spread_amounts(self):
        for payment in self:
            payment.il_planned_amount = sum(
                payment.il_split_line_ids.mapped('amount'))
            payment.il_applied_amount = sum(
                payment.il_split_line_ids.filtered('is_applied').mapped('amount'))
            payment.il_remaining_amount = (
                payment.amount - payment.il_applied_amount)

    @api.depends(
        'payment_method_line_id', 'partner_id', 'company_id',
        'company_id.il_employee_payment_credit_account_id',
    )
    def _compute_outstanding_account_id(self):
        super()._compute_outstanding_account_id()
        for payment in self.filtered(
                lambda item: item._il_uses_employee_payment_accounting()):
            payment.outstanding_account_id = (
                payment.company_id.il_employee_payment_credit_account_id)

    @api.depends(
        'journal_id', 'partner_id', 'partner_type', 'payment_type',
        'company_id.il_employee_payment_debit_account_id',
    )
    def _compute_destination_account_id(self):
        super()._compute_destination_account_id()
        for payment in self.filtered(
                lambda item: item._il_uses_employee_payment_accounting()):
            payment.destination_account_id = (
                payment.company_id.il_employee_payment_debit_account_id)

    def _il_check_employee_payment_accounts(self):
        for payment in self.filtered(
                lambda item: item._il_uses_employee_payment_accounting()):
            debit = payment.company_id.il_employee_payment_debit_account_id
            credit = payment.company_id.il_employee_payment_credit_account_id
            if not debit or not credit:
                raise UserError(_(
                    'יש להגדיר בהגדרות השכר חשבון חובה וחשבון זכות '
                    'לתשלומי עובדים לפני יצירת התשלום.'
                ))
            if debit == credit:
                raise ValidationError(_(
                    'חשבון החובה וחשבון הזכות לתשלומי עובדים חייבים להיות שונים.'
                ))
            accounts = debit | credit
            if any(payment.company_id not in account.company_ids for account in accounts):
                raise ValidationError(_(
                    'חשבונות תשלום העובד חייבים להיות זמינים בחברת התשלום.'
                ))
            accounts.filtered(lambda account: not account.reconcile).write({
                'reconcile': True,
            })

    def _prepare_move_liquidity_lines(self, default_values):
        values = super()._prepare_move_liquidity_lines(default_values)
        if self._il_uses_employee_payment_accounting():
            self._il_check_employee_payment_accounts()
            for line_values in values:
                line_values['account_id'] = (
                    self.company_id.il_employee_payment_credit_account_id.id)
                line_values['partner_id'] = self.partner_id.id
        return values

    def _prepare_move_counterpart_lines(self, default_values):
        values = super()._prepare_move_counterpart_lines(default_values)
        if self._il_uses_employee_payment_accounting():
            self._il_check_employee_payment_accounts()
            for line_values in values:
                line_values['account_id'] = (
                    self.company_id.il_employee_payment_debit_account_id.id)
                line_values['partner_id'] = self.partner_id.id
        return values

    def _prepare_move_withholding_lines(self, default_values):
        if self._il_uses_employee_payment_accounting():
            return []
        return super()._prepare_move_withholding_lines(default_values)

    @api.readonly
    def get_formview_id(self, access_uid=None):
        self.ensure_one()
        if self._il_employee():
            return self.env.ref(
                'l10n_il_hr_payroll_account.view_account_payment_form_employee'
            ).id
        return super().get_formview_id(access_uid=access_uid)

    @api.model_create_multi
    def create(self, vals_list):
        payments = super(AccountPayment, self.with_context(
            il_skip_spread_total_check=True,
            il_system_split_create=True,
        )).create(vals_list)
        Split = self.env['account.payment.split.line']
        for payment in payments.filtered(
                lambda item: item._il_uses_employee_payment_accounting()
                and item.il_spread_type == 'none'
                and not item.il_split_line_ids):
            Split.with_context(il_system_split_create=True).create({
                'payment_id': payment.id,
                'amount': payment.amount,
            })
        employee_payments = payments.filtered(
            lambda item: item._il_uses_employee_payment_accounting())
        employee_payments._il_check_employee_payment_accounts()
        payments._check_il_spread_complete()
        return payments

    def write(self, vals):
        old_types = {payment.id: payment.il_spread_type for payment in self}
        target = self.with_context(il_skip_spread_total_check=True) \
            if 'il_split_line_ids' in vals else self
        result = super(AccountPayment, target).write(vals)
        Split = self.env['account.payment.split.line']
        for payment in self.filtered(
                lambda item: item._il_uses_employee_payment_accounting()):
            if ('il_spread_type' in vals
                    and old_types[payment.id] != payment.il_spread_type):
                if payment.il_split_line_ids.filtered('reconcile_id'):
                    raise ValidationError(_(
                        'לא ניתן לשנות את אופן הפריסה לאחר שנוצרה התאמה.'))
                keep_submitted_planned_lines = (
                    payment.il_spread_type == 'planned'
                    and 'il_split_line_ids' in vals
                )
                if not keep_submitted_planned_lines:
                    payment.il_split_line_ids.with_context(
                        il_system_split_unlink=True).unlink()
                if payment.il_spread_type == 'none':
                    Split.with_context(il_system_split_create=True).create({
                        'payment_id': payment.id,
                        'amount': payment.amount,
                    })
            elif ('amount' in vals and payment.il_spread_type == 'none'
                    and not self.env.context.get('il_sync_from_line')):
                line = payment.il_split_line_ids[:1]
                if line:
                    line.with_context(
                        il_sync_from_payment=True,
                        il_skip_spread_total_check=True,
                    ).amount = payment.amount
                else:
                    Split.with_context(il_system_split_create=True).create({
                        'payment_id': payment.id,
                        'amount': payment.amount,
                    })
        if 'il_split_line_ids' in vals:
            self._il_resequence_split_lines()
        if 'amount' in vals or 'il_split_line_ids' in vals:
            self._check_il_spread_complete()
            self._il_check_draft_reconciliation_amounts()
        return result

    def _il_check_draft_reconciliation_amounts(self):
        """Keep edited draft allocations within each payslip's open NET."""
        for payment in self.filtered(
                lambda item: item.state == 'draft'
                and item._il_uses_employee_payment_accounting()):
            company_currency = payment.company_id.currency_id
            allocations = {}
            for split in payment.il_split_line_ids:
                target_line = split._il_target_payslip_move_line()
                payslip = target_line.il_payslip_id
                if not payslip:
                    continue
                values = allocations.setdefault(payslip, {
                    'proposed': 0.0,
                    'currently_applied': 0.0,
                })
                values['proposed'] += payment.currency_id._convert(
                    split.amount,
                    company_currency,
                    payment.company_id,
                    max(payment.date, target_line.date),
                )
                if split.reconcile_id:
                    values['currently_applied'] += split.reconcile_id.amount

            for payslip, values in allocations.items():
                available = (
                    payslip.il_net_amount_to_pay
                    + values['currently_applied']
                )
                if company_currency.compare_amounts(
                        values['proposed'], available) > 0:
                    raise ValidationError(_(
                        'לא ניתן לשמור את התשלום: סכום ההתאמות החדש לתלוש '
                        '%(payslip)s (%(proposed)s) גדול מיתרת הנטו הזמינה '
                        'בו (%(available)s).',
                        payslip=payslip.display_name,
                        proposed=company_currency.format(values['proposed']),
                        available=company_currency.format(available),
                    ))

    @api.constrains('amount', 'il_applied_amount', 'il_remaining_amount')
    def _check_il_remaining_amount(self):
        for payment in self.filtered(lambda item: item.state != 'draft'):
            currency = payment.currency_id
            if currency.compare_amounts(payment.il_remaining_amount, 0.0) < 0:
                raise ValidationError(_(
                    'סכום ההתאמות אינו יכול להיות גבוה מסכום התשלום.'))

    def _check_il_spread_complete(self):
        Split = self.env['account.payment.split.line']
        for payment in self.filtered(
                lambda item: item._il_uses_employee_payment_accounting()):
            lines = Split.search(
                [('payment_id', '=', payment.id)], order='sequence, id')
            planned_amount = sum(lines.mapped('amount'))
            if payment.il_spread_type in ('planned', 'none') and \
                    payment.currency_id.compare_amounts(
                        planned_amount, payment.amount):
                raise ValidationError(_(
                    'בפריסה מתוכננת או מיידית סכום השורות חייב להיות שווה '
                    'לסכום התשלום.'))

    def _il_resequence_split_lines(self):
        Split = self.env['account.payment.split.line']
        for payment in self:
            ordered = Split.search(
                [('payment_id', '=', payment.id)], order='sequence, id')
            for offset, line in enumerate(ordered, 1):
                line.with_context(
                    il_system_resequence=True,
                    il_skip_spread_total_check=True,
                ).sequence = 1000000 + offset
            for sequence, line in enumerate(ordered, 1):
                line.with_context(
                    il_system_resequence=True,
                    il_skip_spread_total_check=True,
                ).sequence = sequence

    def _il_is_open_employee_payment(self):
        self.ensure_one()
        return bool(
            self._il_uses_employee_payment_accounting()
            and self.state in ('in_process', 'paid')
            and self.currency_id.compare_amounts(
                self.il_remaining_amount, 0.0) > 0
        )

    def _il_sync_immediate_split_before_post(self):
        """Repair an immediate draft's free remainder without editing allocations.

        Older payments can have no split after cancellation/reset to draft.
        Their immediate split is system managed, so confirmation must restore it
        before checking completeness. Existing reconciled or pending allocations
        are never resized or deleted by this repair.
        """
        Split = self.env['account.payment.split.line'].with_context(
            il_system_split_create=True,
            il_system_split_unlink=True,
            il_sync_from_payment=True,
            il_skip_spread_total_check=True,
        )
        for payment in self.filtered(
                lambda item: item.state == 'draft'
                and item.il_spread_type == 'none'
                and item._il_uses_employee_payment_accounting()):
            lines = payment.il_split_line_ids.sorted(
                lambda line: (line.sequence, line.id))
            currency = payment.currency_id
            if not currency.compare_amounts(
                    sum(lines.mapped('amount')), payment.amount):
                continue
            protected = lines.filtered(
                lambda line: line.reconcile_id
                or line.il_pending_payslip_move_line_id)
            remaining = currency.round(
                payment.amount - sum(protected.mapped('amount')))
            if currency.compare_amounts(remaining, 0.0) < 0:
                raise ValidationError(_(
                    'סכום ההתאמות הקיימות גבוה מסכום התשלום. '
                    'יש לתקן את ההתאמות לפני אישור התשלום.'))
            free = lines - protected
            if currency.is_zero(remaining):
                Split.browse(free.ids).unlink()
            elif free:
                # Delete excess free rows first to avoid a transient total
                # greater than the payment during the amount update.
                Split.browse(free[1:].ids).unlink()
                Split.browse(free[:1].ids).write({'amount': remaining})
            else:
                Split.create({'payment_id': payment.id, 'amount': remaining})

    def action_post(self):
        self._il_sync_immediate_split_before_post()
        self._check_il_spread_complete()
        self._il_check_employee_payment_accounts()
        draft_employee_payments = self.filtered(
            lambda payment: payment.state == 'draft'
            and payment._il_uses_employee_payment_accounting())
        draft_employee_payments._il_check_draft_reconciliation_amounts()
        reconciliation_targets = {
            split.id: split._il_target_payslip_move_line().id
            for payment in draft_employee_payments
            for split in payment.il_split_line_ids
            if split._il_target_payslip_move_line()
        }
        employee_payments = self.filtered(
            lambda payment: payment._il_uses_employee_payment_accounting())
        result = super().action_post()
        # Odoo considers payments posted directly to an asset_cash account paid.
        # Employee payments have an explicit Confirm -> Pay workflow, so posting
        # must always stop at In Process; action_validate() is the only step that
        # marks them Paid.
        employee_payments.filtered(
            lambda payment: payment.state == 'paid').state = 'in_process'
        impacted_payslips = self.env['hr.payslip']
        for split_id, target_line_id in reconciliation_targets.items():
            split = self.env['account.payment.split.line'].browse(
                split_id).exists()
            target_line = self.env['account.move.line'].browse(
                target_line_id).exists()
            if not split or not target_line or not target_line.il_payslip_id:
                raise ValidationError(_(
                    'לא ניתן לחדש את ההתאמה: שורת היומן של התלוש אינה קיימת.'))
            if split.reconcile_id:
                split.reconcile_id.with_context(
                    il_discard_reconciliation_target=True,
                ).unlink()
            payslip = target_line.il_payslip_id
            split._il_reconcile_with_payslip(payslip)
            split.with_context(
                il_reconciliation_sync=True,
                il_skip_draft_reconciliation_check=True,
            ).il_pending_payslip_move_line_id = False
            impacted_payslips |= payslip

        origin_payslip_id = self.env.context.get('il_origin_payslip_id')
        if origin_payslip_id:
            payslip = self.env['hr.payslip'].browse(
                origin_payslip_id).exists()
            if not payslip:
                raise ValidationError(_('התלוש שממנו נפתח התשלום אינו קיים.'))
            if payslip.state not in ('validated', 'paid'):
                raise ValidationError(_(
                    'ניתן להתאים תשלום שנוצר מכפתור שלם רק לתלוש מאושר.'))
            if not payslip.move_id or payslip.move_id.state != 'posted':
                raise ValidationError(_(
                    'פקודת היומן של התלוש חייבת להיות רשומה לפני יצירת '
                    'התשלום.'))
            for payment in employee_payments:
                for split in payment.il_split_line_ids.filtered(
                        lambda line: not line.reconcile_id).sorted(
                            key=lambda line: (line.sequence, line.id)):
                    split._il_reconcile_with_payslip(payslip)
            payslip._il_check_nonnegative_net_to_pay()
            payslip._il_sync_paid_state_from_balance()
        impacted_payslips._il_check_nonnegative_net_to_pay()
        impacted_payslips._il_sync_paid_state_from_balance()
        return result
