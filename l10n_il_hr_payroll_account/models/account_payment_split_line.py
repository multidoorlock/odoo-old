# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountPaymentSplitLine(models.Model):
    _name = 'account.payment.split.line'
    _description = 'Employee Payment Reconciliation Split Line'
    _order = 'payment_id, sequence, id'

    payment_id = fields.Many2one(
        'account.payment', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string="פעימה מס'", required=True, default=1)
    amount = fields.Monetary(string='סכום השורה', required=True)
    currency_id = fields.Many2one(
        related='payment_id.currency_id', store=True, readonly=True)
    reconcile_id = fields.Many2one(
        'account.partial.reconcile', string='התאמה', copy=False,
        readonly=True, ondelete='set null', index='btree_not_null')
    il_pending_payslip_move_line_id = fields.Many2one(
        'account.move.line', copy=False, readonly=True, ondelete='set null',
        help='Temporary accounting target retained while a payment is edited in draft.')
    is_applied = fields.Boolean(
        string='קוזז', compute='_compute_is_applied', store=True)
    company_id = fields.Many2one(
        related='payment_id.company_id', store=True, readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', compute='_compute_employee', store=True)

    _positive_amount = models.Constraint(
        'CHECK(amount > 0)', 'סכום פעימה חייב להיות גדול מאפס.')
    _positive_sequence = models.Constraint(
        'CHECK(sequence > 0)', 'מספר פעימה חייב להיות גדול מאפס.')
    _unique_reconcile = models.Constraint(
        'UNIQUE(reconcile_id)',
        'רשומת התאמה יכולה להשתייך לשורת פיצול אחת בלבד.')

    @api.depends('reconcile_id')
    def _compute_is_applied(self):
        for line in self:
            line.is_applied = bool(line.reconcile_id)

    @api.depends('payment_id.partner_id', 'payment_id.company_id')
    def _compute_employee(self):
        for line in self:
            line.employee_id = line.payment_id._il_employee()

    def action_open_payment(self):
        self.ensure_one()
        return self.payment_id.get_formview_action()

    def _il_target_payslip_move_line(self):
        self.ensure_one()
        if self.il_pending_payslip_move_line_id:
            return self.il_pending_payslip_move_line_id
        if not self.reconcile_id:
            return self.env['account.move.line']
        return (
            self.reconcile_id.debit_move_id
            | self.reconcile_id.credit_move_id
        ).filtered('il_payslip_id')[:1]

    @api.model_create_multi
    def create(self, vals_list):
        next_sequences = {}
        for vals in vals_list:
            payment_id = vals.get('payment_id')
            if not payment_id:
                continue
            if payment_id not in next_sequences:
                last_line = self.search(
                    [('payment_id', '=', payment_id)],
                    order='sequence desc, id desc', limit=1)
                next_sequences[payment_id] = (last_line.sequence or 0) + 1
            vals['sequence'] = vals.get('sequence') or next_sequences[payment_id]
            next_sequences[payment_id] = vals['sequence'] + 1
        if not self.env.context.get('il_system_split_create'):
            payments = self.env['account.payment'].browse({
                vals.get('payment_id') for vals in vals_list
                if vals.get('payment_id')
            })
            if payments.filtered(lambda payment: payment.il_spread_type != 'planned'):
                raise ValidationError(_(
                    'יצירה ידנית של פעימות מותרת רק בפריסה מתוכננת.'))
        lines = super().create(vals_list)
        lines._check_business_rules()
        lines._check_complete_spread_outside_draft()
        return lines

    def write(self, vals):
        if 'amount' in vals and self.filtered(
                lambda line: line.reconcile_id
                and line.payment_id.state != 'draft'):
            raise ValidationError(_(
                'ניתן לשנות סכום של פעימה מותאמת רק לאחר החזרת התשלום לטיוטה.'))
        if 'payment_id' in vals and self.filtered('reconcile_id'):
            raise ValidationError(_(
                'לא ניתן להעביר פעימה לתשלום אחר לאחר שנוצרה התאמה.'))
        if (
            'reconcile_id' in vals
            and not vals['reconcile_id']
            and not self.env.context.get('il_reconciliation_sync')
        ):
            reconciliations = self.filtered('reconcile_id').mapped('reconcile_id')
            if self.filtered(lambda line: line.payment_id.state != 'draft'):
                raise ValidationError(_(
                    'ניתן להסיר התאמה רק לאחר החזרת התשלום לטיוטה.'))
            reconciliations.with_context(
                il_discard_reconciliation_target=True,
            ).unlink()
            vals = dict(vals, il_pending_payslip_move_line_id=False)
        payments = self.mapped('payment_id') \
            if 'sequence' in vals else self.env['account.payment']
        result = super().write(vals)
        if payments and not self.env.context.get('il_system_resequence'):
            payments._il_resequence_split_lines()
        if not self.env.context.get('il_reconciliation_sync'):
            self._check_business_rules()
        if ('amount' in vals
                and not self.env.context.get('il_sync_from_payment')):
            for line in self.filtered(
                    lambda item: item.payment_id.il_spread_type == 'none'):
                line.payment_id.with_context(
                    il_sync_from_line=True).amount = line.amount
        self._check_complete_spread_outside_draft()
        if not self.env.context.get('il_skip_draft_reconciliation_check'):
            self.mapped('payment_id')._il_check_draft_reconciliation_amounts()
        return result

    def unlink(self):
        reconciled = self.filtered('reconcile_id')
        if reconciled.filtered(lambda line: line.payment_id.state != 'draft'):
            raise ValidationError(_(
                'ניתן למחוק פעימה מותאמת רק לאחר החזרת התשלום לטיוטה.'))
        if reconciled:
            reconciled.mapped('reconcile_id').with_context(
                il_discard_reconciliation_target=True,
            ).unlink()
        if not self.env.context.get('il_system_split_unlink') and self.filtered(
                lambda line: line.payment_id.state != 'draft'
                and line.payment_id.il_spread_type != 'planned'):
            raise ValidationError(_(
                'מחיקת פעימות מותרת רק בפריסה מתוכננת.'))
        payments = self.mapped('payment_id')
        result = super().unlink()
        payments._il_resequence_split_lines()
        if not self.env.context.get('il_system_split_unlink'):
            payments.filtered(
                lambda payment: payment.state != 'draft'
            )._check_il_spread_complete()
        return result

    def _il_reconcile_with_payslip(self, payslip):
        """Reconcile this payment split with one posted payslip JE."""
        self.ensure_one()
        if self.reconcile_id:
            raise ValidationError(_('פעימה זו כבר קוזזה.'))
        payment = self.payment_id
        if not payment.move_id or payment.move_id.state != 'posted':
            raise ValidationError(_('יש לרשום את פקודת היומן של התשלום לפני ההתאמה.'))
        if not payslip.move_id or payslip.move_id.state != 'posted':
            raise ValidationError(_(
                'ניתן לטפל בתשלומים רק לאחר רישום פקודת היומן של התלוש.'))
        if payment.company_id != payslip.company_id:
            raise ValidationError(_('התשלום והתלוש חייבים להשתייך לאותה חברה.'))
        if payment._il_employee() != payslip.employee_id:
            raise ValidationError(_('התשלום והתלוש חייבים להשתייך לאותו עובד.'))
        (payment.move_id | payslip.move_id)._il_check_reconciliation_editable()

        self.env.cr.execute(
            'SELECT id FROM account_payment_split_line WHERE id = %s FOR UPDATE',
            (self.id,),
        )
        self.invalidate_recordset(['reconcile_id', 'amount', 'payment_id'])
        if self.reconcile_id:
            raise ValidationError(_('פעימה זו כבר קוזזה על ידי משתמש אחר.'))

        account = payment.company_id.il_employee_payment_debit_account_id
        payment_line = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == account
            and line.parent_state == 'posted'
            and line.amount_residual > 0.0
        )
        payslip_line = payslip._il_salary_payable_lines().filtered(
            lambda line: line.parent_state == 'posted'
            and line.amount_residual < 0.0
        )
        if len(payment_line) != 1 or len(payslip_line) != 1:
            raise ValidationError(_(
                'נדרשות שורת תשלום פתוחה אחת ושורת NET פתוחה אחת לצורך ההתאמה.'))
        if (payment_line.account_id != payslip_line.account_id
                or payment_line.partner_id != payslip_line.partner_id
                or payment_line.partner_id != payment.partner_id
                or payment_line.currency_id != payslip_line.currency_id
                or payment.currency_id != payslip.currency_id):
            raise ValidationError(_(
                'שורות התשלום והתלוש חייבות להיות באותו חשבון, איש קשר ומטבע.'))

        self.env.cr.execute(
            'SELECT id FROM account_move_line WHERE id IN %s FOR UPDATE',
            [tuple((payment_line | payslip_line).ids)],
        )
        (payment_line | payslip_line).invalidate_recordset([
            'amount_residual', 'amount_residual_currency', 'reconciled',
        ])
        company_currency = payment.company_id.currency_id
        payment_currency = payment.currency_id
        reconcile_date = max(payment.date, payslip_line.date)
        company_amount = payment_currency._convert(
            self.amount, company_currency, payment.company_id, reconcile_date)
        payment_available = payment_line.amount_residual
        payslip_available = -payslip_line.amount_residual
        if company_currency.compare_amounts(
                company_amount, payment_available) > 0:
            raise ValidationError(_(
                'סכום הפעימה גבוה מהיתרה הפתוחה בפקודת התשלום.'))
        if company_currency.compare_amounts(
                company_amount, payslip_available) > 0:
            raise ValidationError(_(
                'סכום הפעימה גבוה מהנטו שנותר לתשלום בתלוש.'))

        closes_payment = company_currency.is_zero(
            payment_available - company_amount)
        closes_payslip = company_currency.is_zero(
            payslip_available - company_amount)
        if closes_payment and closes_payslip:
            before_ids = payment_line.matched_credit_ids.ids
            (payment_line | payslip_line).reconcile()
            reconciliation = payment_line.matched_credit_ids.filtered(
                lambda partial: partial.id not in before_ids
                and partial.credit_move_id == payslip_line)
        else:
            debit_currency_amount = (
                self.amount
                if payment_line.currency_id == payment_currency
                else company_amount
            )
            credit_currency_amount = (
                company_amount
                if payslip_line.currency_id == company_currency
                else company_currency._convert(
                    company_amount, payslip_line.currency_id,
                    payment.company_id, reconcile_date)
            )
            reconciliation = self.env['account.partial.reconcile'].create({
                'amount': company_amount,
                'debit_amount_currency': debit_currency_amount,
                'credit_amount_currency': credit_currency_amount,
                'debit_move_id': payment_line.id,
                'credit_move_id': payslip_line.id,
            })
        if len(reconciliation) != 1:
            raise ValidationError(_(
                'פעימה אחת חייבת ליצור רשומת התאמה אחת בדיוק.'))
        self.with_context(
            il_reconciliation_sync=True,
            il_skip_spread_total_check=True,
        ).reconcile_id = reconciliation.id
        return reconciliation

    @api.model
    def _il_take_open_amount(self, payment, amount):
        """Take an allocation from open installments without changing payment.

        A partial installment leaves its unallocated remainder immediately
        after it. Existing applied installments and later scheduled amounts
        retain their identity and order.
        """
        payment.ensure_one()
        currency = payment.currency_id
        if currency.compare_amounts(amount, 0) <= 0:
            raise ValidationError(_('סכום התאמה חייב להיות גדול מאפס.'))
        opened = payment.il_split_line_ids.filtered(
            lambda line: not line.reconcile_id
            and not line.il_pending_payslip_move_line_id).sorted(
                lambda line: (line.sequence, line.id))
        if currency.compare_amounts(amount, sum(opened.mapped('amount'))) > 0:
            raise ValidationError(_('סכום ההתאמה גבוה מיתרת הפריסה הפנויה של התשלום.'))
        chunks = self.browse()
        remaining = currency.round(amount)
        for line in opened:
            if currency.is_zero(remaining):
                break
            allocated = min(line.amount, remaining)
            if currency.compare_amounts(allocated, line.amount) < 0:
                remainder = currency.round(line.amount - allocated)
                line.with_context(
                    il_sync_from_payment=True,
                    il_skip_spread_total_check=True,
                ).write({'amount': allocated})
                self.with_context(
                    il_system_split_create=True,
                    il_skip_spread_total_check=True,
                ).create({
                    'payment_id': payment.id, 'amount': remainder,
                    'sequence': line.sequence,
                })
            chunks |= line
            remaining = currency.round(remaining - allocated)
        return chunks

    @api.model
    def _il_adopt_native_allocations(self, payment):
        """Attach schedule metadata to matches made by native Accounting."""
        payment.ensure_one()
        account = payment.company_id.il_employee_payment_debit_account_id
        partials = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == account
        ).matched_credit_ids.filtered(lambda partial: partial.credit_move_id.il_payslip_id)
        linked = payment.il_split_line_ids.reconcile_id
        for partial in (partials - linked).sorted('id'):
            debit, credit = partial.debit_move_id, partial.credit_move_id
            if (debit.payment_id != payment
                    or debit.account_id != credit.account_id
                    or debit.partner_id != credit.partner_id
                    or debit.partner_id != payment.partner_id
                    or debit.currency_id != credit.currency_id
                    or debit.currency_id != payment.currency_id
                    or credit.il_payslip_id.employee_id != payment._il_employee()
                    or credit.company_id != payment.company_id):
                raise ValidationError(_(
                    'נמצאה התאמה קיימת שאינה תואמת לעובד, לחשבון או למטבע התשלום.'))
            chunks = self._il_take_open_amount(payment, partial.debit_amount_currency)
            first = chunks[:1]
            if len(chunks) > 1:
                (chunks - first).with_context(
                    il_system_split_unlink=True,
                    il_skip_spread_total_check=True,
                ).unlink()
                first.with_context(
                    il_sync_from_payment=True,
                    il_skip_spread_total_check=True,
                ).write({'amount': partial.debit_amount_currency})
            first.with_context(
                il_reconciliation_sync=True,
                il_skip_spread_total_check=True,
            ).write({'reconcile_id': partial.id})
        payment._check_il_spread_complete()

    def _check_complete_spread_outside_draft(self):
        if self.env.context.get('il_skip_spread_total_check'):
            return
        self.mapped('payment_id').filtered(
            lambda payment: payment.state != 'draft'
        )._check_il_spread_complete()

    def _check_business_rules(self):
        for line in self:
            payment = line.payment_id
            if line.reconcile_id:
                reconciliation = line.reconcile_id
                payslip = (
                    reconciliation.credit_move_id.il_payslip_id
                    or reconciliation.debit_move_id.il_payslip_id
                )
                if not payslip:
                    raise ValidationError(_(
                        'ההתאמה המקושרת אינה כוללת פקודת יומן של תלוש.'))
                expected = payment.currency_id._convert(
                    line.amount, payment.company_id.currency_id,
                    payment.company_id,
                    max(payment.date, reconciliation.credit_move_id.date))
                if reconciliation.debit_move_id.payment_id != payment:
                    raise ValidationError(_(
                        'ההתאמה המקושרת חייבת להשתייך לפקודת היומן של התשלום.'))
                if (
                    payment.state != 'draft'
                    and payment.company_id.currency_id.compare_amounts(
                        reconciliation.amount, expected)
                ):
                    raise ValidationError(_(
                        'ההתאמה המקושרת חייבת להתאים לתשלום ולסכום הפעימה.'))
            planned = sum(payment.il_split_line_ids.mapped('amount'))
            if payment.il_spread_type in ('planned', 'none') and \
                    payment.currency_id.compare_amounts(
                        planned, payment.amount) > 0:
                raise ValidationError(_(
                    'סכום הפעימות אינו יכול לעבור את סכום התשלום.'))
