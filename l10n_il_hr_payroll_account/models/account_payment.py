# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    il_is_employee_payment = fields.Boolean(
        string='תשלום לעובד', compute='_compute_il_is_employee_payment', store=True)
    il_payment_type_display = fields.Char(
        string='סוג תשלום', compute='_compute_il_payment_type_display')

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
    def _compute_il_is_employee_payment(self):
        for payment in self:
            payment.il_is_employee_payment = bool(payment._il_employee())

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

    @api.model
    def _il_validate_origin_payslip(self, values):
        payslip_id = self.env.context.get('il_origin_payslip_id')
        if not payslip_id:
            return self.env['hr.payslip']
        payslip = self.env['hr.payslip'].browse(payslip_id).exists()
        if not payslip or payslip.state not in ('validated', 'paid'):
            raise ValidationError(_('ניתן לשלם רק תלוש מאושר.'))
        self.env.cr.execute(
            'SELECT id FROM hr_payslip WHERE id = %s FOR UPDATE', (payslip.id,))
        amount = values.get('amount', 0.0)
        currency = payslip.currency_id or payslip.company_id.currency_id
        if currency.compare_amounts(amount, payslip.il_net_amount_to_pay) > 0:
            raise ValidationError(_('לא ניתן לשלם יותר מהיתרה לתשלום בתלוש.'))
        partner_id = values.get('partner_id')
        if partner_id and partner_id != payslip.employee_id.work_contact_id.id:
            raise ValidationError(_('התשלום חייב להיות משויך לעובד של התלוש.'))
        return payslip

    def _il_reconcile_origin_payslip(self, payslip):
        self.ensure_one()
        if not payslip:
            return
        if (
            self.company_id != payslip.company_id
            or self.partner_id != payslip.employee_id.work_contact_id
        ):
            raise ValidationError(_(
                'התשלום והתלוש חייבים להשתייך לאותו עובד ולאותה חברה.'
            ))
        if not payslip.move_id:
            raise ValidationError(_('לתלוש אין פקודת יומן שניתן להתאים.'))
        if payslip.move_id.state == 'draft':
            payslip.move_id.action_post()
        payable_lines = payslip._il_salary_payable_lines().filtered(
            lambda line: line.parent_state == 'posted' and not line.reconciled)
        payment_lines = self.move_id.line_ids.filtered(
            lambda line: (
                line.account_id == self.company_id.il_employee_payment_debit_account_id
                and line.parent_state == 'posted'
                and not line.reconciled
            )
        )
        if not payable_lines or not payment_lines:
            raise ValidationError(_(
                'לא נמצאו שורות פתוחות בחשבון שכר עובדים לשלם לצורך התאמה.'
            ))
        (payable_lines | payment_lines).reconcile()

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            self._il_validate_origin_payslip(values)
        payments = super().create(vals_list)
        employee_payments = payments.filtered(
            lambda item: item._il_uses_employee_payment_accounting())
        employee_payments._il_check_employee_payment_accounts()
        return payments

    def action_post(self):
        self._il_check_employee_payment_accounts()
        employee_payments = self.filtered(
            lambda payment: payment._il_uses_employee_payment_accounting())
        origin_payslip = self.env['hr.payslip']
        if len(self) == 1 and self.env.context.get('il_origin_payslip_id'):
            origin_payslip = self._il_validate_origin_payslip({
                'amount': self.amount,
                'partner_id': self.partner_id.id,
            })
        result = super().action_post()
        # Odoo considers payments posted directly to an asset_cash account paid.
        # Employee payments have an explicit Confirm -> Pay workflow, so posting
        # must always stop at In Process; action_validate() is the only step that
        # marks them Paid.
        employee_payments.filtered(
            lambda payment: payment.state == 'paid').state = 'in_process'
        if origin_payslip:
            self._il_reconcile_origin_payslip(origin_payslip)
        return result
