# -*- coding: utf-8 -*-
import json

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class IlPayrollReconciliationWizard(models.TransientModel):
    _name = 'il.payroll.reconciliation.wizard'
    _description = 'Employee Payment and Payslip Allocation'

    source_payment_id = fields.Many2one('account.payment', readonly=True)
    source_payslip_id = fields.Many2one('hr.payslip', readonly=True)
    add_only = fields.Boolean(readonly=True, default=False)
    employee_id = fields.Many2one('hr.employee', compute='_compute_scope')
    company_id = fields.Many2one('res.company', compute='_compute_scope')
    currency_id = fields.Many2one('res.currency', compute='_compute_scope')
    available_payment_ids = fields.Many2many(
        'account.payment', compute='_compute_candidates')
    available_payslip_ids = fields.Many2many(
        'hr.payslip', compute='_compute_candidates')
    line_ids = fields.One2many(
        'il.payroll.reconciliation.wizard.line', 'wizard_id',
        string='תשלומים מקושרים')
    snapshot = fields.Text(readonly=True)
    original_row_pairs = fields.Json(readonly=True, default=dict)

    @api.depends('source_payment_id', 'source_payslip_id')
    def _compute_scope(self):
        for wizard in self:
            source = wizard.source_payment_id or wizard.source_payslip_id
            wizard.company_id = source.company_id
            wizard.currency_id = source.currency_id
            wizard.employee_id = (
                wizard.source_payment_id._il_employee()
                if wizard.source_payment_id
                else wizard.source_payslip_id.employee_id)

    @api.model
    def _eligible_payments(self, payslip):
        """New links use the real payable-side residual, never payment state.

        A payment linked to another payslip remains eligible while it has an
        open debit balance. Already linked payments are edited in their
        existing rows instead of being offered for another link to this slip.
        """
        payslip.ensure_one()
        payslip.check_access('read')
        employee = payslip.employee_id
        company = payslip.company_id
        if not employee or not employee.work_contact_id:
            return self.env['account.payment']
        account = company.il_employee_payment_debit_account_id
        items = self.env['account.move.line'].search([
            ('company_id', '=', company.id),
            ('partner_id', '=', employee.work_contact_id.id),
            ('account_id', '=', account.id),
            ('currency_id', '=', payslip.currency_id.id),
            ('parent_state', '=', 'posted'),
            ('payment_id', '!=', False),
            ('balance', '>', 0),
            ('amount_residual', '>', 0),
        ])
        linked = self.env['account.partial.reconcile'].search([
            ('credit_move_id.il_payslip_id', '=', payslip.id),
            ('debit_move_id.payment_id', '!=', False),
        ]).debit_move_id.payment_id
        payments = items.payment_id - linked
        return payments.filtered(lambda payment:
            payment.company_id == company
            and payment.currency_id == payslip.currency_id
            and payment._il_employee() == employee
            and payment._il_uses_employee_payment_accounting()
            and payment.move_id.state == 'posted'
            and payslip.currency_id.compare_amounts(sum(
                items.filtered(lambda line: line.payment_id == payment).mapped(
                    'amount_residual_currency')), 0.0) > 0)

    @api.depends('employee_id', 'company_id', 'currency_id', 'source_payslip_id')
    def _compute_candidates(self):
        for wizard in self:
            if wizard.source_payslip_id:
                wizard.available_payment_ids = wizard._eligible_payments(wizard.source_payslip_id)
            else:
                wizard.available_payment_ids = wizard.source_payment_id
            wizard.available_payslip_ids = self.env['hr.payslip'].search([
                ('company_id', '=', wizard.company_id.id),
                ('employee_id', '=', wizard.employee_id.id),
                ('currency_id', '=', wizard.currency_id.id),
                ('move_id.state', '=', 'posted'),
            ])

    def _check_source(self):
        self.ensure_one()
        if bool(self.source_payment_id) == bool(self.source_payslip_id):
            raise ValidationError(_('יש לפתוח את התשלומים המקושרים ממסמך מקור אחד.'))
        if self.add_only and not self.source_payslip_id:
            raise ValidationError(_('יש לפתוח הוספת תשלומים מתוך תלוש.'))
        source = self.source_payment_id or self.source_payslip_id
        source.check_access('read')
        if not self.employee_id:
            raise ValidationError(_('המסמך חייב להיות מקושר לעובד.'))
        if not source.move_id or source.move_id.state != 'posted':
            raise ValidationError(_(
                'ניתן לקשר תשלום לתלוש לאחר רישום פקודת היומן. '
                'אין צורך להחזיר את התשלום או התלוש לטיוטה.'))
        if self.source_payment_id and not source._il_uses_employee_payment_accounting():
            raise ValidationError(_('ניהול זה מיועד לתשלומים יוצאים לעובדים.'))
        if source.company_id not in self.env.companies:
            raise ValidationError(_('חברת המסמך אינה בין החברות הפעילות שלך.'))

    def _scope_partials(self):
        self.ensure_one()
        domain = [
            ('debit_move_id.payment_id', '!=', False),
            ('credit_move_id.il_payslip_id', '!=', False),
        ]
        if self.source_payment_id:
            domain.append(('debit_move_id.payment_id', '=', self.source_payment_id.id))
        else:
            domain.append(('credit_move_id.il_payslip_id', '=', self.source_payslip_id.id))
        return self.env['account.partial.reconcile'].search(domain, order='id')

    def _fingerprint(self):
        """Include schedule and financial inputs, not just visible totals."""
        self.ensure_one()
        partials = self._scope_partials()
        payments = partials.debit_move_id.payment_id | self.source_payment_id
        slips = partials.credit_move_id.il_payslip_id | self.source_payslip_id
        values = {
            'partials': [(p.id, p.amount, p.debit_amount_currency,
                          p.credit_amount_currency, p.debit_move_id.id,
                          p.credit_move_id.id) for p in partials],
            'payments': [(p.id, p.amount, p.currency_id.id, p.partner_id.id,
                          p.company_id.id, p.move_id.id, str(p.date),
                          p.il_spread_type) for p in payments.sorted('id')],
            'splits': [(s.id, s.payment_id.id, s.sequence, s.amount,
                        s.reconcile_id.id, s.il_pending_payslip_move_line_id.id)
                       for s in payments.il_split_line_ids.sorted('id')],
            'slips': [(s.id, s.employee_id.id, s.company_id.id, s.move_id.id,
                       s.currency_id.id) for s in slips.sorted('id')],
            'items': [(l.id, l.move_id.id, l.account_id.id, l.partner_id.id,
                       l.currency_id.id, l.balance, l.amount_currency,
                       l.amount_residual, l.amount_residual_currency)
                      for l in (payments.move_id.line_ids
                                | slips.move_id.line_ids.filtered(
                                    lambda item: item.il_payslip_id in slips)
                                ).sorted('id')],
        }
        return json.dumps(values, sort_keys=True, separators=(',', ':'))

    def _initial_rows(self):
        if self.add_only:
            return []
        grouped = {}
        for partial in self._scope_partials():
            payment = partial.debit_move_id.payment_id
            slip = partial.credit_move_id.il_payslip_id
            key = (payment.id, slip.id)
            values = grouped.setdefault(key, {
                'payment_id': payment.id, 'payslip_id': slip.id, 'amount': 0.0,
            })
            values['amount'] += partial.debit_amount_currency
        return [Command.create(values) for values in grouped.values()]

    @api.model_create_multi
    def create(self, vals_list):
        # The original snapshot and rows are generated on the server. A stale
        # browser cannot supply its own baseline to overwrite a newer match.
        cleaned = [{key: value for key, value in vals.items()
                    if key not in ('snapshot', 'line_ids', 'original_row_pairs')}
                   for vals in vals_list]
        wizards = super().create(cleaned)
        for wizard in wizards:
            wizard._check_source()
            super(IlPayrollReconciliationWizard, wizard).write({
                'snapshot': wizard._fingerprint(),
                'line_ids': wizard._initial_rows(),
            })
            super(IlPayrollReconciliationWizard, wizard).write({
                'original_row_pairs': {
                    str(line.id): [line.payment_id.id, line.payslip_id.id]
                    for line in wizard.line_ids},
            })
        return wizards

    def write(self, vals):
        if {'source_payment_id', 'source_payslip_id', 'snapshot',
                'original_row_pairs', 'add_only'} & vals.keys():
            raise ValidationError(_('יש לפתוח חלון חדש כדי לשנות את מסמך המקור.'))
        return super().write(vals)

    @api.model
    def _action_open(self, payment=None, payslip=None, add_only=False):
        wizard = self.create({
            'source_payment_id': payment.id if payment else False,
            'source_payslip_id': payslip.id if payslip else False,
            'add_only': add_only,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('קישור תשלום לתלוש') if add_only else _('תשלומים מקושרים'),
            'res_model': self._name, 'res_id': wizard.id,
            'view_mode': 'form', 'target': 'new',
            'views': [(self.env.ref(
                'l10n_il_hr_payroll_account.view_il_payroll_reconciliation_wizard'
            ).id, 'form')],
            'context': {'dialog_size': 'large'},
        }

    def _check_pair(self, payment, slip, check_editable=True):
        payment.check_access('read')
        slip.check_access('read')
        if self.source_payment_id and payment != self.source_payment_id:
            raise ValidationError(_('בחלון זה ניתן לקשר רק את תשלום המקור.'))
        if self.source_payslip_id and slip != self.source_payslip_id:
            raise ValidationError(_('בחלון זה ניתן לקשר רק לתלוש המקור.'))
        if (payment.company_id != self.company_id
                or slip.company_id != self.company_id
                or payment._il_employee() != self.employee_id
                or slip.employee_id != self.employee_id
                or payment.partner_id != self.employee_id.work_contact_id):
            raise ValidationError(_('ניתן לקשר רק תשלום ותלוש של אותו עובד ובאותה חברה.'))
        if (payment.currency_id != self.currency_id
                or slip.currency_id != self.currency_id):
            raise ValidationError(_('התשלום והתלוש חייבים להיות באותו מטבע.'))
        if not payment._il_uses_employee_payment_accounting():
            raise ValidationError(_('יש לבחור תשלום יוצא לעובד.'))
        moves = payment.move_id | slip.move_id
        if (not payment.move_id or not slip.move_id
                or any(move.state != 'posted' for move in moves)):
            raise ValidationError(_('שתי פקודות היומן חייבות להיות רשומות לפני הקישור.'))
        if check_editable:
            moves._il_check_reconciliation_editable()
        account = self.company_id.il_employee_payment_debit_account_id
        debit = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == account and line.balance > 0)
        credit = slip._il_salary_payable_lines().filtered(
            lambda line: line.balance < 0)
        if (len(debit) != 1 or len(credit) != 1
                or debit.account_id != credit.account_id
                or debit.partner_id != credit.partner_id
                or debit.partner_id != payment.partner_id
                or debit.currency_id != credit.currency_id
                or debit.currency_id != payment.currency_id):
            raise ValidationError(_(
                'נדרשות שורת תשלום ושורת NET באותו חשבון, איש קשר ומטבע.'))

    def _lock_records(self, payments, slips):
        # Consistent order across payment and payslip entry points. Native
        # matching also locks journal items; hold those locks through commit.
        self.env.flush_all()
        for table, records in [('account_payment', payments), ('hr_payslip', slips)]:
            if records:
                self.env.cr.execute(
                    'SELECT id FROM ' + table + ' WHERE id IN %s ORDER BY id FOR UPDATE',
                    [tuple(records.ids)],
                )
        items = payments.move_id.line_ids | slips.move_id.line_ids
        if items:
            self.env.cr.execute(
                'SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(items.ids)],
            )
        self.env.invalidate_all()

    def action_apply(self):
        self.ensure_one()
        # Unlink/recreate is a single transaction, including validation errors
        # caught by callers. No payment or salary move is reset or reposted.
        with self.env.cr.savepoint():
            return self._apply_allocations()

    def _apply_allocations(self):
        self._check_source()
        old = self._scope_partials()
        payments = old.debit_move_id.payment_id | self.line_ids.payment_id | self.source_payment_id
        slips = old.credit_move_id.il_payslip_id | self.line_ids.payslip_id | self.source_payslip_id
        self._lock_records(payments, slips)
        if self._fingerprint() != self.snapshot:
            raise UserError(_(
                'התשלומים המקושרים, היתרות או הפריסה השתנו מאז פתיחת החלון. '
                'סגור ופתח את התשלומים המקושרים מחדש.'))
        grouped = {}
        for partial in self._scope_partials():
            key = (partial.debit_move_id.payment_id.id,
                   partial.credit_move_id.il_payslip_id.id)
            grouped[key] = grouped.get(key, self.env['account.partial.reconcile']) | partial
        requested = ({key: sum(partials.mapped('debit_amount_currency'))
                      for key, partials in grouped.items()} if self.add_only else {})
        for line in self.line_ids:
            self._check_pair(line.payment_id, line.payslip_id, check_editable=False)
            if self.currency_id.compare_amounts(line.amount, 0) <= 0:
                raise ValidationError(_('הסכום המקושר חייב להיות חיובי; להסרה מחק את השורה.'))
            key = (line.payment_id.id, line.payslip_id.id)
            original_pair = (self.original_row_pairs or {}).get(str(line.id))
            if original_pair:
                if list(key) != original_pair:
                    raise ValidationError(_('להחלפת תשלום מקושר, הסר את השורה והוסף תשלום חדש.'))
            elif (key in grouped
                    or line.payment_id not in self._eligible_payments(line.payslip_id)):
                raise ValidationError(_(
                    'אפשר להוסיף רק תשלום עם יתרה פתוחה שאינו מקושר כבר לתלוש זה. '
                    'לשינוי תשלום קיים ערוך את השורה שלו.'))
            if key in requested:
                raise ValidationError(_('יש לרכז כל זוג של תשלום ותלוש בשורה אחת.'))
            requested[key] = line.amount
        changed = {key for key in set(grouped) | set(requested)
                   if self.currency_id.compare_amounts(
                       sum(grouped.get(key, self.env['account.partial.reconcile']).mapped(
                           'debit_amount_currency')), requested.get(key, 0.0))}
        if not changed:
            return {'type': 'ir.actions.act_window_close'}
        changed_payments = self.env['account.payment'].browse(sorted({key[0] for key in changed}))
        for payment_id, slip_id in changed:
            self._check_pair(self.env['account.payment'].browse(payment_id),
                             self.env['hr.payslip'].browse(slip_id))
            grouped.get((payment_id, slip_id), self.env[
                'account.partial.reconcile'])._il_check_allocation_editable()

        # A native reconciliation made outside payroll may not yet have split
        # metadata. Adopt it before releasing/changing allocations, preserving
        # the native partial as the only payment-to-payslip relationship.
        for payment in changed_payments:
            self.env['account.payment.split.line']._il_adopt_native_allocations(payment)
        to_remove = self.env['account.partial.reconcile']
        for key in changed:
            to_remove |= grouped.get(key, self.env['account.partial.reconcile'])
        to_remove.with_context(il_discard_reconciliation_target=True).unlink()

        for payment_id, slip_id in sorted(changed):
            amount = requested.get((payment_id, slip_id), 0.0)
            if self.currency_id.is_zero(amount):
                continue
            payment = self.env['account.payment'].browse(payment_id)
            slip = self.env['hr.payslip'].browse(slip_id)
            chunks = self.env['account.payment.split.line']._il_take_open_amount(
                payment, amount)
            for chunk in chunks:
                chunk._il_reconcile_with_payslip(slip)
        changed_payments._il_resequence_split_lines()
        changed_payments._check_il_spread_complete()
        changed_payments.il_split_line_ids._check_business_rules()
        slips._il_check_nonnegative_net_to_pay()
        slips._il_sync_paid_state_from_balance()
        self.env.flush_all()
        return {'type': 'ir.actions.act_window_close'}


class IlPayrollReconciliationWizardLine(models.TransientModel):
    _name = 'il.payroll.reconciliation.wizard.line'
    _description = 'Employee Payment Allocation Proposal'

    wizard_id = fields.Many2one(
        'il.payroll.reconciliation.wizard', required=True, ondelete='cascade')
    payment_id = fields.Many2one('account.payment', string='תשלום', required=True)
    payslip_id = fields.Many2one('hr.payslip', string='תלוש', required=True)
    memo = fields.Char(related='payment_id.memo', string='פתק')
    amount = fields.Monetary(string='סכום להכרה', required=True)
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    payment_amount = fields.Monetary(related='payment_id.amount', string='סכום התשלום')
    payment_available_amount = fields.Monetary(
        string='יתרה להכרה', compute='_compute_payment_available_amount')
    payslip_remaining = fields.Monetary(
        related='payslip_id.il_net_amount_to_pay', string='יתרת התלוש כעת')
    is_existing = fields.Boolean(compute='_compute_existing')

    @api.depends('payment_id.move_id.line_ids.amount_residual_currency',
                 'payment_id.move_id.state',
                 'payment_id.company_id.il_employee_payment_debit_account_id')
    def _compute_payment_available_amount(self):
        for line in self:
            payment = line.payment_id
            if not payment:
                line.payment_available_amount = 0.0
                continue
            account = payment.company_id.il_employee_payment_debit_account_id
            items = payment.move_id.line_ids.filtered(lambda item:
                item.parent_state == 'posted' and item.account_id == account
                and item.partner_id == payment.partner_id
                and item.currency_id == payment.currency_id and item.balance > 0)
            line.payment_available_amount = max(
                payment.currency_id.round(sum(items.mapped('amount_residual_currency'))), 0.0)

    @api.depends('wizard_id.original_row_pairs')
    def _compute_existing(self):
        for line in self:
            line.is_existing = str(line._origin.id) in (line.wizard_id.original_row_pairs or {})


class IlPayslipPaymentSelectionWizard(models.TransientModel):
    _name = 'il.payslip.payment.selection.wizard'
    _description = 'Selected Payslip Payments'

    source_payslip_id = fields.Many2one('hr.payslip', required=True, readonly=True, string='תלוש')
    employee_id = fields.Many2one(related='source_payslip_id.employee_id', string='עובד')
    currency_id = fields.Many2one(related='source_payslip_id.currency_id')
    operation = fields.Selection([
        ('add', 'קישור לתלוש'), ('edit', 'שינוי סכום להכרה'),
        ('remove', 'הסרת קישור מהתלוש')], required=True, readonly=True)
    selected_payment_ids = fields.Many2many('account.payment', readonly=True)
    editor_id = fields.Many2one('il.payroll.reconciliation.wizard', readonly=True, ondelete='cascade')
    line_ids = fields.One2many('il.payslip.payment.selection.wizard.line', 'wizard_id')
    original_rows = fields.Json(readonly=True)
    applied = fields.Boolean(readonly=True)
    payslip_remaining = fields.Monetary(readonly=True, string='נותר לסגירה בתלוש')
    total_amount = fields.Monetary(compute='_compute_total', string='סה״כ להכרה')

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for wizard in self:
            wizard.total_amount = sum(wizard.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        # The selected records are the only client input used to generate a
        # review. Tokens, baseline rows and the underlying editor are private.
        clean = [{key: value for key, value in vals.items()
                  if key in ('source_payslip_id', 'operation', 'selected_payment_ids')}
                 for vals in vals_list]
        wizards = super().create(clean)
        for wizard in wizards:
            wizard._prepare_selection()
        return wizards

    def write(self, vals):
        if set(vals) - {'line_ids'}:
            raise ValidationError(_('יש לפתוח חלון חדש כדי לשנות את בחירת התשלומים.'))
        return super().write(vals)

    def _prepare_selection(self):
        self.ensure_one()
        payments = self.selected_payment_ids.exists()
        if not payments or payments != self.selected_payment_ids:
            raise ValidationError(_('יש לבחור לפחות תשלום אחד מהרשימה.'))
        payments.check_access('read')
        payments.check_access('write')
        editor = self.env['il.payroll.reconciliation.wizard'].create({
            'source_payslip_id': self.source_payslip_id.id,
            'add_only': self.operation == 'add',
        })
        slip = self.source_payslip_id
        linked = editor._scope_partials().debit_move_id.payment_id
        eligible = editor._eligible_payments(slip) if self.operation == 'add' else linked
        if payments - eligible:
            raise ValidationError(_(
                'הבחירה השתנתה או אינה מתאימה לפעולה. רענן את רשימת התשלומים ובחר שוב.'))
        for payment in payments:
            editor._check_pair(payment, slip)
        remaining = max(-sum(slip._il_salary_payable_lines().mapped('amount_residual_currency')), 0.0)
        unassigned = remaining
        lines = []
        for payment in payments.sorted(lambda record: (record.date, record.id)):
            current = sum(payment._il_payslip_link_partials().filtered(
                lambda partial: partial.credit_move_id.il_payslip_id == slip
            ).mapped('debit_amount_currency'))
            available = payment.il_recognition_available_amount
            amount = current
            if self.operation == 'add':
                amount = min(available, unassigned)
                unassigned = max(unassigned - amount, 0.0)
            lines.append(Command.create({
                'payment_id': payment.id, 'payment_date': payment.date, 'memo': payment.memo,
                'payment_amount': payment.amount, 'available_amount': available,
                'current_amount': current, 'amount': amount,
            }))
        super(IlPayslipPaymentSelectionWizard, self).write({
            'editor_id': editor.id, 'line_ids': lines, 'payslip_remaining': remaining,
        })
        super(IlPayslipPaymentSelectionWizard, self).write({
            'original_rows': {str(line.id): {
                'payment_id': line.payment_id.id,
                'token': line.payment_id._il_payslip_link_token(slip),
            } for line in self.line_ids},
        })

    @api.model
    def _action_open(self, payments, operation):
        slip = payments._il_context_payslip()
        wizard = self.create({
            'source_payslip_id': slip.id, 'operation': operation,
            'selected_payment_ids': [Command.set(payments.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': dict(self._fields['operation']._description_selection(self.env))[operation],
            'res_model': self._name, 'res_id': wizard.id,
            'view_mode': 'form', 'target': 'new',
            'views': [(self.env.ref(
                'l10n_il_hr_payroll_account.view_il_payslip_payment_selection_wizard').id, 'form')],
            'context': {'dialog_size': 'large', 'allowed_company_ids': self.env.companies.ids},
        }

    def action_apply(self):
        self.ensure_one()
        with self.env.cr.savepoint():
            return self._apply_selection()

    def _apply_selection(self):
        if self.applied:
            raise UserError(_('הפעולה כבר בוצעה. יש לרענן את רשימת התשלומים.'))
        editor = self.editor_id.exists()
        if not editor:
            raise UserError(_('חלון העריכה פג תוקף. פתח אותו מחדש מרשימת התשלומים.'))
        editor.check_access('write')
        if editor.source_payslip_id != self.source_payslip_id or bool(editor.add_only) != (self.operation == 'add'):
            raise ValidationError(_('מקור הפעולה אינו תואם לחלון שנפתח.'))
        rows = self.original_rows or {}
        if set(rows) != {str(line.id) for line in self.line_ids}:
            raise ValidationError(_('יש לבחור תשלומים מהרשימה; לא ניתן להוסיף או להסיר שורות בחלון זה.'))
        proposed = []
        for line in self.line_ids:
            baseline = rows[str(line.id)]
            if line.payment_id.id != baseline['payment_id']:
                raise ValidationError(_('לא ניתן להחליף תשלום בחלון זה.'))
            if self.currency_id.compare_amounts(line.amount, 0.0) < 0 or (
                    self.operation == 'edit' and self.currency_id.is_zero(line.amount)):
                raise ValidationError(_('הסכום להכרה חייב להיות חיובי; להסרה בחר הסרת קישור מהתלוש.'))
            proposed.append((line.payment_id, line.amount, baseline['token']))
        if self.operation == 'add' and not any(
                self.currency_id.compare_amounts(amount, 0.0) > 0 for _, amount, _ in proposed):
            raise ValidationError(_('יש להזין סכום להכרה לפחות באחד מהתשלומים שנבחרו.'))
        payments = self.line_ids.payment_id
        payments.check_access('write')
        partials = editor._scope_partials()
        editor._lock_records(partials.debit_move_id.payment_id | payments,
                             partials.credit_move_id.il_payslip_id | self.source_payslip_id)
        if self.applied:
            raise UserError(_('הפעולה כבר בוצעה. יש לרענן את רשימת התשלומים.'))
        if editor._fingerprint() != editor.snapshot:
            raise UserError(_('הסכומים בתלוש השתנו מאז פתיחת החלון. רענן את הרשימה ונסה שוב.'))
        initial = {command[2]['payment_id']: command[2]['amount']
                   for command in editor._initial_rows()}
        actual = {line.payment_id.id: line.amount for line in editor.line_ids}
        if initial != actual or len(actual) != len(editor.line_ids):
            raise UserError(_('חלון העריכה השתנה. פתח מחדש את הפעולה מרשימת התשלומים.'))
        for payment, amount, token in proposed:
            editor._check_pair(payment, self.source_payslip_id)
            if token != payment._il_payslip_link_token(self.source_payslip_id):
                raise UserError(_('התשלום או יתרתו השתנו מאז פתיחת החלון. רענן את הרשימה ונסה שוב.'))
            if self.operation == 'add':
                if not self.currency_id.is_zero(amount):
                    editor.write({'line_ids': [Command.create({
                        'payment_id': payment.id, 'payslip_id': self.source_payslip_id.id,
                        'amount': amount,
                    })]})
            else:
                current = editor.line_ids.filtered(lambda line: line.payment_id == payment)
                if len(current) != 1:
                    raise UserError(_('קישור התשלום השתנה. רענן את הרשימה ונסה שוב.'))
                if self.operation == 'remove':
                    current.unlink()
                else:
                    current.amount = amount
        # Apply the entire selection together so increasing one link while
        # decreasing another is independent of the order of selected rows.
        editor.action_apply()
        super(IlPayslipPaymentSelectionWizard, self).write({'applied': True})
        return self.source_payslip_id.action_il_open_payments()


class IlPayslipPaymentSelectionWizardLine(models.TransientModel):
    _name = 'il.payslip.payment.selection.wizard.line'
    _description = 'Selected Payslip Payment Amount'

    wizard_id = fields.Many2one('il.payslip.payment.selection.wizard', required=True, ondelete='cascade')
    payment_id = fields.Many2one('account.payment', required=True, readonly=True, string='תשלום')
    payment_date = fields.Date(readonly=True, string='תאריך')
    memo = fields.Char(readonly=True, string='פתק')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    payment_amount = fields.Monetary(readonly=True, string='סכום התשלום')
    current_amount = fields.Monetary(readonly=True, string='מוכר כעת בתלוש')
    available_amount = fields.Monetary(readonly=True, string='יתרה להכרה')
    amount = fields.Monetary(string='סכום להכרה', required=True)

    def write(self, vals):
        if set(vals) - {'amount'}:
            raise ValidationError(_('בחלון זה ניתן לשנות רק את הסכום להכרה.'))
        return super().write(vals)
