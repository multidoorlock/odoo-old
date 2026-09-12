import json

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_LINE_CREATION_TOKEN = object()


class IlPayslipRunPaymentWizard(models.TransientModel):
    _name = 'il.payslip.run.payment.wizard'
    _description = 'Final Payroll Payment Review'

    run_id = fields.Many2one('hr.payslip.run', required=True, readonly=True, string='אצוות תלושים')
    company_id = fields.Many2one('res.company', required=True, readonly=True, string='חברה')
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    journal_id = fields.Many2one(
        'account.journal', required=True, string='בנק', check_company=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]")
    available_payment_method_line_ids = fields.Many2many(
        'account.payment.method.line', compute='_compute_available_payment_methods')
    payment_method_line_id = fields.Many2one(
        'account.payment.method.line', required=True, string='אמצעי תשלום', check_company=True,
        domain="[('id', 'in', available_payment_method_line_ids)]")
    date = fields.Date(required=True, string='תאריך תשלום')
    name = fields.Char(required=True, string='שם תשלום האצווה')
    memo = fields.Char(required=True, string='פתק לתשלומים')
    line_ids = fields.One2many(
        'il.payslip.run.payment.wizard.line', 'wizard_id', readonly=True, string='יתרות לתשלום')
    total_amount = fields.Monetary(compute='_compute_totals', string='סה״כ לתשלום')
    payslip_count = fields.Integer(compute='_compute_totals', string='מספר תלושים')
    snapshot = fields.Text(readonly=True)
    batch_id = fields.Many2one('account.batch.payment', readonly=True, copy=False)

    @api.depends('journal_id')
    def _compute_available_payment_methods(self):
        for wizard in self:
            wizard.available_payment_method_line_ids = (
                wizard.journal_id._get_available_payment_method_lines('outbound')
                if wizard.journal_id else self.env['account.payment.method.line'])

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        if self.payment_method_line_id not in self.available_payment_method_line_ids:
            self.payment_method_line_id = self.available_payment_method_line_ids[:1]

    @api.depends('line_ids.amount')
    def _compute_totals(self):
        for wizard in self:
            wizard.total_amount = sum(wizard.line_ids.mapped('amount'))
            wizard.payslip_count = len(wizard.line_ids)

    @api.model
    def _check_run(self, run, require_closed=True):
        run.ensure_one()
        run.check_access('read')
        run.check_access('write')
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_user'):
            raise AccessError(_('נדרשת הרשאת שכר כדי ליצור תשלום אצווה מתלושים.'))
        if run.company_id not in self.env.companies:
            raise AccessError(_('יש לבחור בחברה של אצוות התלושים לפני יצירת התשלום.'))
        if require_closed and run.state != '02_close':
            raise ValidationError(_('יש לאשר ולסגור את אצוות התלושים לפני סגירת השכר.'))

    @api.model
    def _eligible_payslips(self, run):
        self._check_run(run)
        slips = run.slip_ids
        slips.check_access('read')
        currency = run.company_id.currency_id
        if slips.filtered(lambda slip: slip.company_id != run.company_id
                          or slip.employee_id.company_id != run.company_id
                          or slip.currency_id != currency):
            raise ValidationError(_('כל התלושים באצווה חייבים להיות באותה חברה ובמטבע החברה.'))
        eligible = slips.filtered(lambda slip:
            slip.state in ('validated', 'paid') and slip.move_id.state == 'posted'
            and currency.compare_amounts(slip.il_net_amount_to_pay, 0.0) > 0)
        if not eligible:
            raise ValidationError(_('לא נמצאו באצווה תלושים מאושרים עם פקודת יומן רשומה ויתרת נטו לתשלום.'))
        missing = eligible.filtered(lambda slip: not slip.employee_id.work_contact_id)
        if missing:
            raise ValidationError(_('לעובדים הבאים אין איש קשר מקושר: %s',
                                    ', '.join(missing.employee_id.mapped('name'))))
        items = eligible.mapped(lambda slip: slip._il_salary_payable_lines())
        pending = self.env['account.payment.split.line'].search([
            ('payment_id.state', '=', 'draft'),
            ('il_pending_payslip_move_line_id', 'in', items.ids),
        ])
        if pending:
            raise ValidationError(_(
                'קיימים תשלומים בטיוטה שכבר מיועדים לתלושים אלה: %s. '
                'יש לאשר או לבטל את הקישור שלהם לפני יצירת תשלום סופי נוסף.',
                ', '.join(pending.payment_id.mapped('display_name'))))
        return eligible.sorted(lambda slip: (slip.employee_id.name or '', slip.id))

    @api.model_create_multi
    def create(self, vals_list):
        values = []
        for submitted in vals_list:
            run = self.env['hr.payslip.run'].browse(submitted.get('run_id')).exists()
            if not run:
                raise ValidationError(_('יש לפתוח את וידוא התשלום מתוך אצוות תלושים קיימת.'))
            self._eligible_payslips(run)
            journals = self.env['account.journal'].search([
                ('company_id', '=', run.company_id.id), ('type', '=', 'bank'),
                '|', ('currency_id', '=', False), ('currency_id', '=', run.company_id.currency_id.id),
            ], order='sequence, id')
            if not journals:
                raise ValidationError(_('לא נמצא יומן בנק במטבע החברה. יש להגדיר בנק לפני סגירת השכר.'))
            journal = journals.filtered(lambda candidate:
                candidate._get_available_payment_method_lines('outbound'))[:1]
            if not journal:
                raise ValidationError(_('יש להגדיר אמצעי תשלום יוצא בבנק לפני סגירת השכר.'))
            method = journal._get_available_payment_method_lines('outbound')[:1]
            if not method:
                raise ValidationError(_('יש להגדיר אמצעי תשלום יוצא בבנק לפני סגירת השכר.'))
            title = _('סגירת שכר סופי — %s', run.name)
            values.append({
                'run_id': run.id, 'company_id': run.company_id.id,
                'currency_id': run.company_id.currency_id.id,
                'journal_id': journal.id, 'payment_method_line_id': method.id,
                'date': run.date_end, 'name': title, 'memo': title,
            })
        wizards = super().create(values)
        for wizard in wizards:
            lines = [{
                'wizard_id': wizard.id, 'sequence': sequence,
                'payslip_id': slip.id, 'employee_id': slip.employee_id.id,
                'net_wage': slip.net_wage, 'amount': slip.il_net_amount_to_pay,
            } for sequence, slip in enumerate(wizard._eligible_payslips(wizard.run_id), start=1)]
            self.env['il.payslip.run.payment.wizard.line'].with_context(
                il_run_payment_line_creation=_LINE_CREATION_TOKEN).create(lines)
            super(IlPayslipRunPaymentWizard, wizard).write({'snapshot': wizard._snapshot()})
        return wizards

    def write(self, vals):
        if set(vals) - {'journal_id', 'payment_method_line_id', 'date', 'name', 'memo'}:
            raise ValidationError(_('יתרות התלושים מחושבות במערכת. יש לפתוח את חלון הווידוא מחדש כדי לרענן אותן.'))
        if self.filtered('batch_id'):
            raise UserError(_('תשלום האצווה כבר נוצר.'))
        return super().write(vals)

    def _snapshot(self):
        self.ensure_one()
        run = self.run_id
        slips = run.slip_ids.sorted('id')
        items = slips.mapped(lambda slip: slip._il_salary_payable_lines()).sorted('id')
        partials = (items.matched_debit_ids | items.matched_credit_ids).sorted('id')
        value = {
            'run': [run.id, run.name, run.state, run.company_id.id, str(run.date_start), str(run.date_end)],
            'slips': [[slip.id, slip.employee_id.id, slip.employee_id.work_contact_id.id,
                       slip.company_id.id, slip.currency_id.id, slip.state, slip.move_id.id,
                       slip.move_id.state, slip.net_wage, slip.il_net_amount_to_pay]
                      for slip in slips],
            'items': [[item.id, item.move_id.id, str(item.date), item.account_id.id,
                       item.partner_id.id, item.currency_id.id, item.balance, item.amount_currency,
                       item.amount_residual, item.amount_residual_currency] for item in items],
            'partials': [[partial.id, partial.debit_move_id.id, partial.credit_move_id.id,
                          partial.amount, partial.debit_amount_currency, partial.credit_amount_currency]
                         for partial in partials],
            'lines': [[line.id, line.sequence, line.payslip_id.id, line.employee_id.id,
                       line.net_wage, line.amount] for line in self.line_ids.sorted('id')],
        }
        return json.dumps(value, sort_keys=True, separators=(',', ':'))

    def _lock_source(self):
        self.env.flush_all()
        # The wizard lock serializes repeat clicks. The run lock serializes
        # separately opened reviews and membership changes before any payment.
        for table, ids in [('il_payslip_run_payment_wizard', self.ids),
                           ('hr_payslip_run', self.run_id.ids)]:
            self.env.cr.execute('SELECT id FROM ' + table + ' WHERE id IN %s ORDER BY id FOR UPDATE',
                                [tuple(ids)])
        self.env.invalidate_all()
        slips = self.run_id.slip_ids
        if slips:
            self.env.cr.execute('SELECT id FROM hr_payslip WHERE id IN %s ORDER BY id FOR UPDATE',
                                [tuple(slips.ids)])
            items = slips.move_id.line_ids
            if items:
                self.env.cr.execute('SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE',
                                    [tuple(items.ids)])
        self.env.invalidate_all()

    def _validate_review(self):
        eligible = self._eligible_payslips(self.run_id)
        if (self.company_id != self.run_id.company_id
                or self.currency_id != self.company_id.currency_id
                or self.snapshot != self._snapshot()):
            raise UserError(_('התלושים או יתרותיהם השתנו מאז פתיחת החלון. יש לפתוח וידוא סופי מחדש.'))
        if (len(self.line_ids) != len(eligible) or self.line_ids.payslip_id != eligible
                or self.line_ids.filtered(lambda line:
                    line.employee_id != line.payslip_id.employee_id
                    or self.currency_id.compare_amounts(line.amount, line.payslip_id.il_net_amount_to_pay)
                    or self.currency_id.compare_amounts(line.amount, 0.0) <= 0)):
            raise ValidationError(_('שורות הווידוא אינן תואמות ליתרות התלושים. יש לפתוח את החלון מחדש.'))
        journal = self.journal_id
        if (journal.type != 'bank' or journal.company_id != self.company_id
                or (journal.currency_id or journal.company_id.currency_id) != self.currency_id):
            raise ValidationError(_('יש לבחור יומן בנק של החברה ובמטבע החברה.'))
        if self.payment_method_line_id not in journal._get_available_payment_method_lines('outbound'):
            raise ValidationError(_('אמצעי התשלום אינו זמין לתשלומים יוצאים בבנק שנבחר.'))
        if not self.date or not (self.name or '').strip() or not (self.memo or '').strip():
            raise ValidationError(_('יש למלא תאריך, שם אצווה ופתק לתשלומים.'))
        eligible.move_id._il_check_reconciliation_editable()
        account = self.company_id.il_employee_payment_debit_account_id
        for slip in eligible:
            items = slip._il_salary_payable_lines().filtered(lambda item: item.amount_residual_currency < 0)
            if (len(items) != 1 or items.account_id != account
                    or items.partner_id != slip.employee_id.work_contact_id
                    or items.currency_id != self.currency_id
                    or self.currency_id.compare_amounts(-items.amount_residual_currency, slip.il_net_amount_to_pay)):
                raise ValidationError(_('שורת יתרת השכר בתלוש %s אינה תואמת לחשבון העובדים, לאיש הקשר ולמטבע.',
                                        slip.display_name))

    @api.model
    def _action_open(self, run):
        run.ensure_one()
        wizard = self.create({'run_id': run.id})
        view = self.env.ref('l10n_il_hr_payroll_account.view_il_payslip_run_payment_wizard_form')
        return {
            'type': 'ir.actions.act_window', 'name': _('וידוא סופי — סגירת שכר'),
            'res_model': self._name, 'res_id': wizard.id, 'view_mode': 'form',
            'views': [(view.id, 'form')], 'target': 'new',
            'context': {'dialog_size': 'extra-large', 'allowed_company_ids': self.env.companies.ids},
        }

    def _batch_action(self):
        self.batch_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('תשלום אצווה'),
                'res_model': 'account.batch.payment', 'res_id': self.batch_id.id,
                'view_mode': 'form', 'target': 'current'}

    def action_confirm(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_source()
            self._check_run(self.run_id, require_closed=not bool(self.batch_id))
            if self.batch_id:
                return self._batch_action()
            self._validate_review()
            # A calling action's defaults must not supply a pre-existing move,
            # a paid/sent state or a different allocation target.
            payment_context = {key: value for key, value in self.env.context.items()
                               if not key.startswith('default_') and key != 'il_origin_payslip_id'}
            payments = self.env['account.payment'].with_context(payment_context).with_company(self.company_id)
            posting = []
            for line in self.line_ids.sorted('sequence'):
                employee = line.employee_id
                bank = employee.primary_bank_account_id or employee.bank_account_ids[:1]
                payment = payments.create({
                    'company_id': self.company_id.id, 'payment_type': 'outbound',
                    'state': 'draft', 'is_sent': False,
                    'partner_type': 'supplier', 'partner_id': employee.work_contact_id.id,
                    'partner_bank_id': bank.id, 'journal_id': self.journal_id.id,
                    'date': self.date, 'amount': line.amount, 'currency_id': self.currency_id.id,
                    'payment_method_line_id': self.payment_method_line_id.id,
                    'memo': self.memo, 'il_spread_type': 'none',
                })
                payments |= payment
                posting.append((payment, line.payslip_id))
            # Native batches accept a homogeneous set of draft payments. Create
            # the batch before posting so it never sees mixed move/no-move rows.
            batch = self.env['account.batch.payment'].with_context(payment_context).with_company(self.company_id).create({
                'name': self.name, 'date': self.date, 'journal_id': self.journal_id.id,
                'batch_type': 'outbound', 'payment_method_id': self.payment_method_line_id.payment_method_id.id,
                'payment_ids': [Command.set(payments.ids)], 'il_payslip_run_id': self.run_id.id,
            })
            for payment, slip in posting:
                payment.with_context(il_origin_payslip_id=slip.id).action_post()
            super(IlPayslipRunPaymentWizard, self).write({'batch_id': batch.id})
            return self._batch_action()


class IlPayslipRunPaymentWizardLine(models.TransientModel):
    _name = 'il.payslip.run.payment.wizard.line'
    _description = 'Final Payroll Payment Review Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('il.payslip.run.payment.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(readonly=True)
    payslip_id = fields.Many2one('hr.payslip', required=True, readonly=True, string='תלוש')
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, string='עובד')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    net_wage = fields.Monetary(readonly=True, string='שכר נטו בתלוש')
    amount = fields.Monetary(required=True, readonly=True, string='יתרה לתשלום')

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('il_run_payment_line_creation') is not _LINE_CREATION_TOKEN:
            raise ValidationError(_('שורות הווידוא נוצרות רק מתוך יתרות התלושים.'))
        return super().create(vals_list)

    def write(self, vals):
        raise ValidationError(_('לא ניתן לערוך את יתרות התלושים בחלון הווידוא.'))
