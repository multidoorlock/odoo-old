# -*- coding: utf-8 -*-
from decimal import Decimal, ROUND_HALF_UP

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

# מצבי Payment שבהם התשלום נחשב "בוצע" ומשתתף בחישוב הסכום ששולם.
IL_EFFECTIVE_PAYMENT_STATES = ('in_process', 'paid')

IL_LEGACY_NET_COMPONENT_CODES = ('IL_NET_WEEKEND', 'IL_NET_ADDITIONAL_DAY')

IL_INPUT_SNAPSHOT_FIELDS = [
    'il_adjustment_direction', 'il_net_adjustment_treatment',
    'il_income_taxable', 'il_national_insurance_applicable',
    'il_pensionable', 'il_severance_applicable',
    'il_study_fund_applicable', 'il_equalization_levy_applicable',
    'il_ni_payment_treatment',
]


def _decimal(value):
    """Convert an Odoo numeric value without performing binary-float math."""
    return Decimal(str(value or 0))


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    state_display = fields.Selection(
        selection_add=[('overpayment', 'תשלום יתר')],
        ondelete={'overpayment': 'set null'},
    )

    @api.depends('version_id', 'version_id.il_salary_structure_id')
    def _compute_struct_id(self):
        super()._compute_struct_id()
        for slip in self.filtered(lambda item: item.version_id.il_salary_structure_id):
            slip.struct_id = slip.version_id.il_salary_structure_id

    def _il_worker_profile(self):
        self.ensure_one()
        code = self.struct_id.code or ''
        if code.startswith('IL_PAL_'):
            return 'palestinian'
        if code.startswith('IL_ISR_'):
            return 'israeli'
        return False

    # ------------------------------------------------------------------
    # שדות תשלום (סעיף 20 באפיון). הקידומת il_ נדרשת כי paid_amount הוא
    # property קיים של hr.payslip (סכום ימי העבודה) — התנגשות שמות.
    # ------------------------------------------------------------------
    il_paid_amount = fields.Monetary(
        string='סכום ששולם', compute='_compute_il_payment_amounts')
    il_net_amount_to_pay = fields.Monetary(
        string='יתרת נטו לתשלום', compute='_compute_il_payment_amounts')
    il_payment_count = fields.Integer(
        string='מספר תשלומים', compute='_compute_il_payment_amounts')

    # Reverse relation to the unified split table, used by computed totals.
    il_split_line_ids = fields.One2many(
        'account.payment.split.line', 'payslip_id', string='שורות תשלום')

    il_visible_line_ids = fields.One2many(
        'hr.payslip.line', 'slip_id', string='חישוב שכר',
        domain=[('il_hide_redundant_base', '=', False)])

    def unlink(self):
        """Release payment instalments through the ORM before deleting slips.

        The split-to-payslip foreign key uses ``ON DELETE SET NULL``. A raw
        database cascade does not notify Odoo's stored computed fields, which
        used to leave ``is_applied`` and payment remaining amounts stale after
        a payslip was deleted. Clearing the relation explicitly makes the
        normal dependency graph run before the payslip disappears.
        """
        split_lines = self.il_split_line_ids
        if split_lines:
            split_lines.write({'payslip_id': False})
        return super().unlink()

    # ------------------------------------------------------------------
    # Applied amount is exactly the sum of split lines linked to this payslip.
    # ------------------------------------------------------------------
    @api.depends('net_wage', 'line_ids.total', 'line_ids.code',
                 'il_split_line_ids.amount', 'il_split_line_ids.payment_id')
    def _compute_il_payment_amounts(self):
        for slip in self:
            paid = sum(slip.il_split_line_ids.mapped('amount'))
            payments = slip.il_split_line_ids.mapped('payment_id')
            slip.il_paid_amount = paid
            # Payment links change independently of salary-rule computation.
            # Always derive the live balance from NET and the current links;
            # a stored IL_NET_TO_PAY line may reflect an older link state.
            slip.il_net_amount_to_pay = slip.net_wage - paid
            slip.il_payment_count = len(payments)

    @api.depends('error_count', 'warning_count', 'state', 'il_net_amount_to_pay', 'currency_id')
    def _compute_state_display(self):
        super()._compute_state_display()
        for slip in self:
            # On a new payslip the web client may request state_display before
            # employee/company onchange has populated currency_id.
            currency = (
                slip.currency_id
                or slip.company_id.currency_id
                or self.env.company.currency_id
            )
            is_negative = (
                currency.compare_amounts(slip.il_net_amount_to_pay, 0.0) < 0
                if currency else slip.il_net_amount_to_pay < 0.0
            )
            if is_negative:
                slip.state_display = 'overpayment'

    def _il_affecting_payments(self):
        """Direct payments linked to this payslip, including their history."""
        self.ensure_one()
        return self.il_split_line_ids.mapped('payment_id')

    def _il_applied_payment_amount(self):
        self.ensure_one()
        return sum(self.il_split_line_ids.mapped('amount'))

    def _il_sync_payment_summary_lines(self):
        """Keep post-validation payment rows aligned with live payment links."""
        for slip in self:
            paid = sum(self.env['account.payment.split.line'].search([
                ('payslip_id', '=', slip.id),
            ]).mapped('amount'))
            values_by_code = {
                'IL_PAYMENTS': -paid,
                'IL_NET_TO_PAY': slip.net_wage - paid,
            }
            lines = self.env['hr.payslip.line'].search([
                ('slip_id', '=', slip.id),
                ('code', 'in', list(values_by_code)),
            ])
            for line in lines:
                value = values_by_code[line.code]
                line.write({'amount': value, 'total': value})

    def _il_attach_automatic_split_lines(self):
        """Link existing planned/no-spread instalments before Compute Sheet."""
        Split = self.env['account.payment.split.line']
        for slip in self:
            partner = slip.employee_id.work_contact_id
            if not partner:
                continue
            available = max(
                slip._il_compute_net_total() - slip._il_applied_payment_amount(), 0.0)
            payments = self.env['account.payment'].search([
                ('partner_id', '=', partner.id),
                ('company_id', '=', slip.company_id.id),
                ('payment_type', '=', 'outbound'),
                ('state', 'not in', ('draft', 'canceled')),
                ('date', '<=', slip.date_to),
                ('il_spread_type', 'in', ('planned', 'none')),
                ('il_remaining_amount', '>', 0),
            ], order='date, id')
            for payment in payments:
                if payment.il_split_line_ids.filtered(
                        lambda existing: existing.payslip_id == slip):
                    continue
                line = Split.search([
                    ('payment_id', '=', payment.id),
                    ('payslip_id', '=', False),
                ], order='sequence, id', limit=1)
                if not line:
                    continue
                currency = (
                    slip.currency_id
                    or slip.company_id.currency_id
                    or self.env.company.currency_id
                )
                exceeds_available = (
                    currency.compare_amounts(line.amount, available) > 0
                    if currency else line.amount > available
                )
                amount_to_draw = min(line.amount, available)
                if currency.compare_amounts(amount_to_draw, 0.0) <= 0:
                    break
                if exceeds_available:
                    remainder = line.amount - amount_to_draw
                    payment.with_context(
                        il_skip_spread_total_check=True,
                        il_system_split_create=True,
                    ).write({
                        'il_spread_type': 'planned',
                        'il_split_line_ids': [
                            Command.update(line.id, {'amount': amount_to_draw}),
                            Command.create({'amount': remainder}),
                        ],
                    })
                line.payslip_id = slip
                available -= amount_to_draw

    # ------------------------------------------------------------------
    # כפתור "שלם" (סעיפים 18–19 באפיון)
    # ------------------------------------------------------------------
    def action_il_register_payment(self):
        self.ensure_one()
        partner = self.employee_id.work_contact_id
        if not partner:
            raise UserError('לעובד אין איש קשר (Partner) מקושר — לא ניתן ליצור תשלום.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'תשלום לעובד',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'target': 'new',
            'views': [(self.env.ref(
                'l10n_il_hr_payroll_account.view_account_payment_form_employee').id,
                'form')],
            'context': {
                'default_partner_id': partner.id,
                'default_payment_type': 'outbound',
                'default_partner_type': 'supplier',
                'default_amount': self.il_net_amount_to_pay,
                'default_il_spread_type': 'none',
                'il_employee_payment': True,
                'il_origin_payslip_id': self.id,
                'il_max_payment_amount': self.il_net_amount_to_pay,
                'il_lock_immediate_spread': True,
                'dialog_size': 'large',
            },
        }

    def action_il_open_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'תשלומים',
            'res_model': 'account.payment.split.line',
            'view_mode': 'list',
            'views': [(self.env.ref(
                'l10n_il_hr_payroll_account.il_payslip_payment_split_line_list').id,
                'list')],
            'domain': [('payslip_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def action_il_draw_open_payments(self):
        self.ensure_one()
        payments = self.env['account.payment'].search([
            ('partner_id', '=', self.employee_id.work_contact_id.id),
            ('company_id', '=', self.company_id.id),
            ('payment_type', '=', 'outbound'),
            ('state', 'not in', ('draft', 'canceled')),
            ('il_spread_type', '=', 'per_payslip'),
            ('il_remaining_amount', '>', 0),
        ], order='date, id')
        payments = payments.filtered(
            lambda payment: not payment.il_split_line_ids.filtered(
                lambda line: line.payslip_id == self))
        wizard = self.env['hr.payslip.payment.draw.wizard'].create({
            'payslip_id': self.id,
            'line_ids': [Command.create({'payment_id': payment.id}) for payment in payments],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'משיכת תשלומים פתוחים',
            'res_model': 'hr.payslip.payment.draw.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # שורת קלט נפרדת לכל התאמת שכר. רכיבי שכר נטו נכתבים ב-Worked Days.
    # ------------------------------------------------------------------
    def _il_adjustment_input_types(self):
        return self.env['hr.payslip.input.type'].search([
            ('available_in_attachments', '=', True)])

    @api.depends(
        'employee_id', 'version_id', 'struct_id', 'date_from', 'date_to',
        'worked_days_line_ids.number_of_hours',
        'worked_days_line_ids.work_entry_type_id',
    )
    def _compute_input_line_ids(self):
        super()._compute_input_line_ids()
        adjustment_type_ids = self._il_adjustment_input_types().ids
        for slip in self:
            commands = []
            # פירוק שורות הקלט המאוחדות שנוצרו על ידי המנגנון הסטנדרטי
            # לשורה נפרדת לכל התאמה (נדרש לגילום נטו פרטני ולתיעוד).
            aggregated = slip.input_line_ids.filtered(
                lambda line: line.input_type_id.id in adjustment_type_ids
                or line.code in IL_LEGACY_NET_COMPONENT_CODES)
            commands += [Command.unlink(line.id) for line in aggregated]
            if slip.employee_id and slip.date_to and slip.struct_id:
                valid_attachments = slip.employee_id.salary_attachment_ids.filtered(
                    lambda a: a.state == 'open'
                    and a.date_start <= slip.date_to
                    and (not a.date_end or a.date_end >= slip.date_from)
                    and (not a.other_input_type_id.struct_ids
                         or slip.struct_id in a.other_input_type_id.struct_ids))
                for attachment in valid_attachments:
                    amount = attachment.active_amount
                    if slip.credit_note:
                        amount = -amount
                    vals = {
                        'name': attachment.description or attachment.other_input_type_id.name,
                        'input_type_id': attachment.other_input_type_id.id,
                        'amount': amount,
                        'il_original_amount': amount,
                        'il_salary_attachment_id': attachment.id,
                        'il_effect_type': attachment.il_effect_type,
                    }
                    for field_name in IL_INPUT_SNAPSHOT_FIELDS:
                        vals[field_name] = attachment[field_name]
                    commands.append(Command.create(vals))
            slip.update({'input_line_ids': commands})
        if not self.env.context.get('il_skip_automatic_gross_up'):
            self.filtered(lambda slip: slip.state == 'draft').with_context(
                il_skip_automatic_gross_up=True)._il_run_gross_up_engine()

    # ------------------------------------------------------------------
    # רישום תשלומי התאמות: המנגנון הסטנדרטי מזהה שורות תלוש לפי קוד סוג
    # הקלט ולא ימצא אותן במבנה שלנו — הרישום מבוצע כאן לפי שורות הקלט,
    # בסכום המקורי (בגילום נטו — הנטו המקורי ולא שווי הברוטו).
    # ------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'draft':
            split_lines = self.mapped('il_split_line_ids')
            if split_lines:
                split_lines.write({'payslip_id': False})
        if 'state' in vals and vals['state'] == 'paid':
            for slip in self:
                sign = -1 if slip.credit_note else 1
                for line in slip.input_line_ids.filtered('il_salary_attachment_id'):
                    amount = abs(line.il_original_amount or line.amount)
                    if amount:
                        line.il_salary_attachment_id.record_payment(sign * amount)
        return res

    # ==================================================================
    # מנוע Gross-Up (סעיפים "מנגנון Gross-Up" באפיון + הבהרות)
    # ==================================================================
    def _il_gross_up_lines(self):
        """Gross-up queue: net wage components first, then net adjustments in
        deterministic order (attachment start date, then id)."""
        self.ensure_one()
        lines = self.input_line_ids.filtered(
            lambda l: l.il_effect_type == 'net')
        component_lines = lines.filtered(
            lambda l: not l.il_salary_attachment_id).sorted(
                key=lambda l: l.id)
        adjustment_lines = (lines - component_lines).sorted(
            key=lambda l: (l.il_salary_attachment_id.date_start or fields.Date.today(),
                           l.il_salary_attachment_id.id))
        return list(component_lines) + list(adjustment_lines)

    def _il_compute_net_total(self):
        """Compute the NET total for the current in-memory inputs without
        writing payslip lines."""
        self.ensure_one()
        line_vals = self._get_payslip_lines()
        return sum(vals['total'] for vals in line_vals if vals['code'] == 'NET')

    def _il_set_worked_days_amount(self, code, gross_amount):
        """Put a solved gross total on matching Odoo Worked Days rows.

        There is normally one aggregated row per type.  If Odoo produces
        more than one, distribute the total by hours and put the currency
        rounding remainder on the last row so the sum stays exact.
        """
        self.ensure_one()
        worked_day_lines = self.worked_days_line_ids.filtered(
            lambda line: line.code == code)
        if not worked_day_lines:
            return
        gross_amount = float(self._il_currency_round_decimal(_decimal(gross_amount)))
        total_hours = sum(abs(line.number_of_hours) for line in worked_day_lines)
        if not total_hours:
            worked_day_lines.amount = 0.0
            return
        remaining = gross_amount
        for line in worked_day_lines[:-1]:
            share = gross_amount * abs(line.number_of_hours) / total_hours
            share = float(self._il_currency_round_decimal(_decimal(share)))
            line.amount = share
            remaining -= share
        worked_day_lines[-1].amount = float(
            self._il_currency_round_decimal(_decimal(remaining)))

    def _il_set_regular_attendance_amount(self, gross_amount):
        self.ensure_one()
        self._il_set_worked_days_amount('WORK100', gross_amount)

    def _il_gross_up_regular_attendance(self):
        """Gross up the standard Odoo attendance amount for a net daily rate.

        The employee keeps the same daily/hourly fields in both modes.  In net
        mode their exact hourly value is the requested net value.  The solved
        gross is stored directly on the WORK100 row and is therefore consumed
        by the ordinary BASIC salary rule just like any Odoo worked-day amount.
        """
        self.ensure_one()
        if self._il_uses_gross_base_wage():
            return
        attendance_lines = self.worked_days_line_ids.filtered(
            lambda line: line.code == 'WORK100')
        # The visible rounding rule contributes exact - displayed at gross
        # level. Its tax/contribution effect is not necessarily identical to
        # that gross amount, so solve for the exact requested net total.
        target_delta = self._il_net_attendance_target()
        if not attendance_lines or not target_delta:
            return

        rounding = self._il_currency_rounding()
        sign = -1.0 if target_delta < 0 else 1.0
        target_delta = abs(target_delta)
        evaluation_slip = self.with_context(il_solving_net_base_wage=True)
        self._il_set_regular_attendance_amount(0.0)
        base_net = evaluation_slip.with_context(
            il_skip_wage_rounding=True)._il_compute_net_total()
        target_net = base_net + sign * target_delta

        def net_at(gross):
            self._il_set_regular_attendance_amount(sign * gross)
            return evaluation_slip._il_compute_net_total()

        low, high = 0.0, max(target_delta, rounding)
        iterations = 0
        while sign * (net_at(high) - target_net) < 0 and iterations < 40:
            high *= 2
            iterations += 1
        if sign * (net_at(high) - target_net) < 0:
            self._il_set_regular_attendance_amount(0.0)
            raise ValidationError(
                'לא ניתן לגלם את שכר הנוכחות ליעד הנטו המבוקש. '
                'יש לבדוק את חוקי השכר והפרמטרים הפעילים.')
        best = high
        for _unused in range(100):
            mid = (low + high) / 2
            net = net_at(mid)
            if abs(net - target_net) <= rounding / 2:
                best = mid
                break
            if sign * (net - target_net) < 0:
                low = mid
            else:
                high = mid
            best = mid
        evaluation_slip._il_refine_gross_at_currency_precision(
            lambda amount: self._il_set_regular_attendance_amount(sign * amount),
            best,
            target_net,
        )

    def _il_gross_up_additional_day(self):
        """Gross up a net additional-day rate directly on its Worked Days row."""
        self.ensure_one()
        version = self.version_id
        additional_lines = self.worked_days_line_ids.filtered(
            lambda line: line.code == 'ADDITIONAL_DAY')
        if (not additional_lines or not version.mdl_additional_day_wage
                or version.mdl_wage_rate_type != 'net'
                or version.mdl_wage_type != 'mdl_monthly'):
            return
        target_delta = (
            self._il_worked_days_units('ADDITIONAL_DAY')
            * version.mdl_additional_day_wage
        )
        if not target_delta:
            return

        rounding = self._il_currency_rounding()
        sign = -1.0 if target_delta < 0 else 1.0
        target_delta = abs(target_delta)
        self._il_set_worked_days_amount('ADDITIONAL_DAY', 0.0)
        base_net = self._il_compute_net_total()
        target_net = base_net + sign * target_delta

        def net_at(gross):
            self._il_set_worked_days_amount('ADDITIONAL_DAY', sign * gross)
            return self._il_compute_net_total()

        low, high = 0.0, max(target_delta, rounding)
        iterations = 0
        while sign * (net_at(high) - target_net) < 0 and iterations < 40:
            high *= 2
            iterations += 1
        if sign * (net_at(high) - target_net) < 0:
            self._il_set_worked_days_amount('ADDITIONAL_DAY', 0.0)
            raise ValidationError(
                'לא ניתן לגלם את גמול היום הנוסף ליעד הנטו המבוקש. '
                'יש לבדוק את חוקי השכר והפרמטרים הפעילים.')
        best = high
        for _unused in range(100):
            mid = (low + high) / 2
            net = net_at(mid)
            if abs(net - target_net) <= rounding / 2:
                best = mid
                break
            if sign * (net - target_net) < 0:
                low = mid
            else:
                high = mid
            best = mid
        self._il_refine_gross_at_currency_precision(
            lambda amount: self._il_set_worked_days_amount(
                'ADDITIONAL_DAY', sign * amount),
            best,
            target_net,
        )

    def _il_run_gross_up_engine(self):
        for slip in self:
            gross_up_lines = slip._il_gross_up_lines()
            rounding = slip._il_currency_rounding()
            # Zero independent net components first.  The attendance target is
            # solved before them so each later component is added on top.
            for line in gross_up_lines:
                line.amount = 0.0
            if (slip.version_id.mdl_wage_rate_type == 'net'
                    and slip.version_id.mdl_additional_day_wage):
                slip._il_set_worked_days_amount('ADDITIONAL_DAY', 0.0)
            slip._il_gross_up_regular_attendance()
            slip._il_gross_up_additional_day()
            if not gross_up_lines:
                continue
            base_net = slip._il_compute_net_total()
            for line in gross_up_lines:
                target_delta = line.il_original_amount
                if not target_delta:
                    continue
                sign = -1 if line.il_adjustment_direction == 'negative' else 1
                target_net = base_net + sign * target_delta

                def net_at(gross):
                    line.amount = gross
                    return slip._il_compute_net_total()

                # הרחבת גבול עליון עד שהשפעת הנטו מכסה את היעד.
                low, high = 0.0, max(target_delta, rounding)
                iterations = 0
                while sign * (net_at(high) - target_net) < 0 and iterations < 40:
                    high *= 2
                    iterations += 1
                if sign * (net_at(high) - target_net) < 0:
                    line.amount = 0.0
                    raise ValidationError(
                        'לא ניתן לגלם את רכיב השכר ליעד הנטו המבוקש. '
                        'יש לבדוק את חוקי השכר והפרמטרים הפעילים.')
                # חיפוש בינארי דטרמיניסטי עד דיוק עיגול המטבע.
                best = high
                for _unused in range(100):
                    mid = (low + high) / 2
                    net = net_at(mid)
                    if abs(net - target_net) <= rounding / 2:
                        best = mid
                        break
                    if sign * (net - target_net) < 0:
                        low = mid
                    else:
                        high = mid
                    best = mid
                slip._il_refine_gross_at_currency_precision(
                    lambda amount: setattr(line, 'amount', amount),
                    best,
                    target_net,
                )
                base_net = slip._il_compute_net_total()

    def compute_sheet(self):
        draft_slips = self.filtered(lambda s: s.state == 'draft')
        draft_slips._il_run_gross_up_engine()
        return super().compute_sheet()

    def action_payslip_done(self):
        result = super().action_payslip_done()
        validated_slips = self.filtered(lambda slip: slip.state == 'validated')
        validated_slips._il_attach_automatic_split_lines()
        validated_slips._il_check_nonnegative_net_to_pay()
        return result

    def _il_check_nonnegative_net_to_pay(self):
        for slip in self:
            currency = slip.currency_id or slip.company_id.currency_id
            if currency.compare_amounts(slip.il_net_amount_to_pay, 0.0) < 0:
                raise ValidationError(
                    'הסכום הכולל של התשלומים המקושרים לתלוש אינו יכול '
                    'להיות גבוה מהנטו של התלוש.')
        return True

    # ==================================================================
    # עזרי חוקי שכר — נקראים מקוד ה-Python של ה-Salary Rules
    # ==================================================================
    def _il_worked_days_hours(self, code):
        self.ensure_one()
        return sum(self.worked_days_line_ids.filtered(
            lambda wd: wd.code == code).mapped('number_of_hours'))

    def _il_worked_days_units(self, code):
        """Day units of a worked-days code (hours / unit-day hours)."""
        self.ensure_one()
        hours_per_day = (
            self.company_id.mdl_shift_morning_hours
            if self.version_id.resource_calendar_id.mdl_schedule_type == 'shifts'
            else self.version_id.mdl_standard_day_hours
        )
        if not hours_per_day:
            return 0.0
        return self._il_worked_days_hours(code) / hours_per_day

    def _il_currency_round_decimal(self, amount):
        """Round a Decimal using the payslip currency increment and HALF-UP."""
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id or self.env.company.currency_id
        increment = _decimal(currency.rounding if currency else 0.01)
        if not increment:
            increment = Decimal('0.01')
        return (
            (amount / increment).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            * increment
        )

    def _il_currency_rounding(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id or self.env.company.currency_id
        return (currency.rounding if currency else 0.01) or 0.01

    def _il_payslip_rounding_amount(self, net_amount):
        """Return the adjustment required to round the final NET to a shekel."""
        self.ensure_one()
        if self.env.context.get('il_skip_wage_rounding'):
            return 0.0
        amount = self._il_currency_round_decimal(_decimal(net_amount))
        rounded = amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return float(rounded - amount)

    def _il_has_payslip_rounding(self, net_amount):
        """Show the final rounding line only when it changes an agora amount."""
        self.ensure_one()
        adjustment = _decimal(self._il_payslip_rounding_amount(net_amount))
        return self._il_currency_round_decimal(adjustment) != Decimal('0')

    def _il_refine_gross_at_currency_precision(self, set_amount, approximate, target_net):
        """Choose the payable currency amount whose rounded NET is closest.

        The binary gross-up search works with unrounded Python results.  A
        result such as 6,000.005056 is inside its half-agora tolerance, but
        Odoo then displays it as 6,000.01.  Gross amounts themselves can only
        be paid at currency precision, so evaluate the neighbouring payable
        amounts against the currency-rounded target and prefer an exact match.
        """
        self.ensure_one()
        increment = _decimal(self._il_currency_rounding())
        centre = self._il_currency_round_decimal(_decimal(approximate))
        rounded_target = self._il_currency_round_decimal(_decimal(target_net))
        best_amount = centre
        best_score = None

        # Search nearest amounts first.  The broad safety window also covers
        # stepped tax/contribution rules where several gross cents can map to
        # the same net cent.
        offsets = [0]
        for step in range(1, 501):
            offsets.extend((-step, step))
        for offset in offsets:
            candidate = centre + increment * offset
            if candidate < 0:
                continue
            set_amount(float(candidate))
            raw_net = _decimal(self._il_compute_net_total())
            rounded_net = self._il_currency_round_decimal(raw_net)
            score = (
                abs(rounded_net - rounded_target),
                abs(raw_net - _decimal(target_net)),
                abs(offset),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_amount = candidate
            if score[0] == 0:
                break

        set_amount(float(best_amount))
        return float(best_amount)

    def _il_exact_hourly_rate(self):
        """Return the daily rate's exact hourly value from its source fields.

        Recalculate instead of trusting only the stored helper field.  This
        also repairs calculations created between the 1.0.6 SQL migration and
        the follow-up recomputation of existing versions.
        """
        self.ensure_one()
        version = self.version_id
        if version.mdl_wage_type == 'mdl_daily' and version.mdl_daily_wage:
            standard_hours = (
                version.company_id.mdl_shift_morning_hours
                if version.resource_calendar_id.mdl_schedule_type == 'shifts'
                else version.resource_calendar_id.hours_per_day
            )
            if standard_hours:
                return (
                    _decimal(version.mdl_daily_wage) / _decimal(standard_hours)
                ).quantize(Decimal('0.0000000001'), rounding=ROUND_HALF_UP)
        return _decimal(
            version.mdl_hourly_wage_exact or version.hourly_wage)

    def _il_daily_hourly_amounts(self):
        """Return exact/display regular-hour totals for a daily employee.

        The calculation intentionally uses WORK100 hours only.  Day units are
        reporting data and never participate in the wage-rounding correction.
        """
        self.ensure_one()
        if self.version_id.mdl_wage_type != 'mdl_daily':
            return Decimal('0'), Decimal('0')
        hours = _decimal(self._il_worked_days_hours('WORK100'))
        exact_rate = self._il_exact_hourly_rate()
        display_rate = self._il_currency_round_decimal(exact_rate)
        return hours * exact_rate, hours * display_rate

    def _il_net_attendance_target(self):
        """Requested net base wage for the employee's wage mode.

        A daily employee targets WORK100 hours multiplied by the exact hourly
        rate.  A monthly employee targets the fixed monthly wage; attendance
        reporting must not reduce that target merely because a clocking is
        missing.
        """
        self.ensure_one()
        version = self.version_id
        if version.mdl_wage_rate_type != 'net':
            return 0.0
        if version.mdl_wage_type == 'mdl_monthly':
            return float(self._il_currency_round_decimal(
                _decimal(version.wage)))
        hours = _decimal(self._il_worked_days_hours('WORK100'))
        exact_rate = self._il_exact_hourly_rate()
        return float(self._il_currency_round_decimal(hours * exact_rate))

    def _il_net_attendance_display_target(self):
        """Displayed-rate target used with the visible wage-rounding rule."""
        self.ensure_one()
        if self._il_uses_gross_base_wage():
            return 0.0
        _exact_total, display_total = self._il_daily_hourly_amounts()
        return float(self._il_currency_round_decimal(display_total))

    def _il_uses_gross_base_wage(self):
        self.ensure_one()
        return self.version_id.mdl_wage_rate_type != 'net'

    def _il_basic_line_name(self):
        self.ensure_one()
        return 'שכר בסיס'

    def _il_basic_amount(self):
        """BASIC uses the fixed gross wage or a gross-up solved WORK100 amount.

        A gross monthly worker uses the fixed monthly wage.  A net monthly
        worker, like a net daily worker, consumes the gross amount solved on
        WORK100 so all ordinary salary rules continue to operate on gross.
        A gross daily worker uses regular hours at the displayed hourly rate.

        The separate IL_WAGE_ROUNDING rule reconciles this displayed result to
        the exact ten-decimal hourly-rate result for daily wages only.
        """
        self.ensure_one()
        version = self.version_id
        if not self._il_uses_gross_base_wage():
            attendance_lines = self.worked_days_line_ids.filtered(
                lambda line: line.code == 'WORK100')
            return sum(attendance_lines.mapped('amount'))
        if version.mdl_wage_type == 'mdl_daily':
            _exact_total, display_total = self._il_daily_hourly_amounts()
            return float(self._il_currency_round_decimal(display_total))
        if version.wage_type == 'hourly':
            return self._il_worked_days_hours('WORK100') * version.hourly_wage
        # Missing an attendance is not, by itself, an unpaid leave. Explicit
        # leave deductions remain Odoo's responsibility and must not be
        # inferred from the attendance table for a monthly employee.
        return max(version.wage, 0.0)

    def _il_wage_rounding_amount(self):
        """Rounded exact result minus the rounded displayed-rate result.

        Both operands are final payslip amounts at currency precision.  Their
        subtraction therefore always closes the two visible lines exactly and
        cannot land on a binary-float half-cent boundary inside Odoo's salary
        rule engine.
        """
        self.ensure_one()
        exact_total, display_total = self._il_daily_hourly_amounts()
        exact_total = self._il_currency_round_decimal(exact_total)
        display_total = self._il_currency_round_decimal(display_total)
        return float(exact_total - display_total)

    def _il_has_wage_rounding(self):
        """Avoid a visible zero line when the difference rounds to no agorot."""
        self.ensure_one()
        if self.env.context.get('il_skip_wage_rounding'):
            return False
        amount = _decimal(self._il_wage_rounding_amount())
        return self._il_currency_round_decimal(amount) != Decimal('0')

    def _il_net_base_gross_hourly_rate(self):
        """Gross hourly rate solved on this payslip for a net base wage."""
        self.ensure_one()
        if self._il_uses_gross_base_wage():
            return 0.0
        regular_hours = self._il_worked_days_hours('WORK100')
        if not regular_hours:
            return 0.0
        attendance_amount = sum(self.worked_days_line_ids.filtered(
            lambda line: line.code == 'WORK100').mapped('amount'))
        return attendance_amount / regular_hours

    def _il_overtime_amount(self):
        self.ensure_one()
        overtime_worked_days = self.worked_days_line_ids.filtered(
            lambda worked_day: worked_day.code == 'OVERTIME')
        net_base_wage = not self._il_uses_gross_base_wage()
        if net_base_wage and self.env.context.get('il_solving_net_base_wage'):
            return 0.0
        if net_base_wage:
            hourly_rate = self._il_net_base_gross_hourly_rate()
            normal_odoo_amount = sum(
                worked_day.number_of_hours
                * hourly_rate
                * worked_day.work_entry_type_id.amount_rate
                for worked_day in overtime_worked_days
                if worked_day.is_paid
            )
        else:
            normal_odoo_amount = sum(overtime_worked_days.mapped('amount'))

        fixed_overtime_lines = self.env['hr.attendance.overtime.line'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('status', '=', 'approved'),
            ('manual_duration', '>', 0),
            ('mdl_fixed_hourly_amount', '>', 0),
        ])
        represented_overtime_ids = self.env['hr.work.entry'].search([
            ('employee_id', '=', self.employee_id.id),
            ('version_id', '=', self.version_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('state', '!=', 'cancelled'),
            ('overtime_id', '!=', False),
        ]).mapped('overtime_id').ids
        fixed_overtime_lines = fixed_overtime_lines.filtered(
            lambda overtime: overtime.id in represented_overtime_ids)
        if not fixed_overtime_lines:
            return normal_odoo_amount

        version = self.version_id
        if net_base_wage:
            hourly_rate = self._il_net_base_gross_hourly_rate()
        elif self.wage_type == 'hourly':
            hourly_rate = version.hourly_wage
        else:
            attendance_hours = sum(
                worked_day.number_of_hours
                for worked_day in self.worked_days_line_ids
                if not worked_day.work_entry_type_id.is_extra_hours
            ) or 1.0
            hourly_rate = version.contract_wage / attendance_hours

        fixed_adjustment = 0.0
        for overtime in fixed_overtime_lines:
            native_rate = overtime.work_entry_type_overtime_id.amount_rate
            native_amount = overtime.manual_duration * hourly_rate * native_rate
            rule_amount = overtime.manual_duration * (
                overtime.mdl_fixed_hourly_amount
                + hourly_rate * overtime.amount_rate
            )
            fixed_adjustment += rule_amount - native_amount
        return normal_odoo_amount + fixed_adjustment

    def _il_additional_day_amount(self):
        self.ensure_one()
        version = self.version_id
        if (not version.mdl_additional_day_wage
                or version.mdl_wage_type != 'mdl_monthly'):
            return 0.0
        if version.mdl_wage_rate_type == 'net':
            return sum(self.worked_days_line_ids.filtered(
                lambda line: line.code == 'ADDITIONAL_DAY').mapped('amount'))
        return self._il_worked_days_units('ADDITIONAL_DAY') * version.mdl_additional_day_wage

    def _il_inputs_base(self, flag_field):
        """Sum of signed adjustment-input amounts participating in a base.
        Net wage-component lines (no linked attachment) are counted through
        their own salary rule, so only attachment lines are summed here."""
        self.ensure_one()
        total = 0.0
        for line in self.input_line_ids.filtered('il_salary_attachment_id'):
            if not line[flag_field]:
                continue
            total += line._il_signed_amount()
        return total

    def _il_adjustment_total(self, effect_type, treatment=None, attachments_only=True):
        self.ensure_one()
        if effect_type == 'net':
            treatment = None
        total = 0.0
        for line in self.input_line_ids:
            if attachments_only and not line.il_salary_attachment_id:
                continue
            if line.il_effect_type != effect_type:
                continue
            if treatment and line.il_net_adjustment_treatment != treatment:
                continue
            total += line._il_signed_amount()
        return total

    def _il_capped_input_amount(self, code, ceiling_code):
        """Sum of a plain (non-attachment) Payslip Input by code, capped by
        a rule parameter — used for manually-entered foreign-employee
        deductions (private health / housing / housing expenses)."""
        self.ensure_one()
        lines = self.input_line_ids.filtered(lambda l: l.code == code)
        if not lines:
            return 0.0
        ceiling = self._rule_parameter(ceiling_code)
        return min(sum(lines.mapped('amount')), ceiling)

    def _il_pal_organization_tax_amount(self, base):
        self.ensure_one()
        if not self.version_id.il_pal_organization_tax:
            return 0.0
        ceiling = self._rule_parameter('IL_PAL_ORGANIZATION_TAX_CEILING')
        rate = self._rule_parameter('IL_PAL_ORGANIZATION_TAX_RATE')
        return min(base, ceiling) * rate / 100.0

    # ------------------------------------------------------------------
    # מס הכנסה — חישוב מצטבר שנתי (זהה לשלושת סוגי העובדים; ההבדל בקוד
    # החוק שממנו נלקח המס שנוכה עד כה)
    # ------------------------------------------------------------------
    def _il_tax_year_start(self):
        self.ensure_one()
        return self.date_from.replace(month=1, day=1)

    def _il_income_tax(self, current_base, rule_code):
        self.ensure_one()
        version = self.version_id
        year_start = self._il_tax_year_start()
        months = self.date_to.month

        max_rate = self._rule_parameter('IL_TAX_MAX_WITHHOLDING_RATE')

        coordination_valid = (
            version.il_tax_coordination
            and (not version.il_tax_coordination_valid_from
                 or version.il_tax_coordination_valid_from <= self.date_from)
            and (not version.il_tax_coordination_valid_until
                 or version.il_tax_coordination_valid_until >= self.date_to))

        # מעסיק משני ללא תיאום מס בתוקף — ניכוי בשיעור המרבי, ללא זיכויים.
        if not version.il_primary_employer and not coordination_valid:
            return current_base * max_rate / 100.0

        cumulative_base = self._sum('IL_TAX_BASE', year_start, self.date_to) + current_base

        # מדרגות המס מוגדרות כערכים חודשיים; במצטבר מוכפלות במספר החודשים.
        brackets = [
            (self._rule_parameter('IL_TAX_BRACKET_1_LIMIT'), self._rule_parameter('IL_TAX_BRACKET_1_RATE')),
            (self._rule_parameter('IL_TAX_BRACKET_2_LIMIT'), self._rule_parameter('IL_TAX_BRACKET_2_RATE')),
            (self._rule_parameter('IL_TAX_BRACKET_3_LIMIT'), self._rule_parameter('IL_TAX_BRACKET_3_RATE')),
            (self._rule_parameter('IL_TAX_BRACKET_4_LIMIT'), self._rule_parameter('IL_TAX_BRACKET_4_RATE')),
            (self._rule_parameter('IL_TAX_BRACKET_5_LIMIT'), self._rule_parameter('IL_TAX_BRACKET_5_RATE')),
            (self._rule_parameter('IL_TAX_BRACKET_6_LIMIT'), self._rule_parameter('IL_TAX_BRACKET_6_RATE')),
            (None, self._rule_parameter('IL_TAX_BRACKET_7_RATE')),
        ]
        tax = 0.0
        previous_limit = 0.0
        for limit, rate in brackets:
            if limit is None:
                tax += max(cumulative_base - previous_limit * months, 0.0) * rate / 100.0
                break
            monthly_limit = limit
            portion = min(cumulative_base, monthly_limit * months) - previous_limit * months
            if portion > 0:
                tax += portion * rate / 100.0
            previous_limit = monthly_limit

        credit_value = self._rule_parameter('IL_TAX_CREDIT_POINT_VALUE')
        credits_total = (version.il_tax_credit_points or 0.0) * credit_value * months
        tax = max(tax - credits_total, 0.0)

        surtax_threshold = self._rule_parameter('IL_TAX_SURTAX_THRESHOLD')
        surtax_rate = self._rule_parameter('IL_TAX_SURTAX_RATE')
        surtax_base = max(cumulative_base - surtax_threshold * months, 0.0)
        tax += surtax_base * surtax_rate / 100.0

        withheld = -self._sum(rule_code, year_start, self.date_to)
        current_tax = tax - withheld
        # תקרת ניכוי מרבי על התלוש הנוכחי.
        if current_base > 0:
            current_tax = min(current_tax, current_base * max_rate / 100.0)
        return current_tax

    # ------------------------------------------------------------------
    # ביטוח לאומי / בריאות — מדרגה מופחתת ומלאה עד תקרה
    # ------------------------------------------------------------------
    def _il_ni_amount(self, base, prefix, reduced_rate_code, full_rate_code):
        self.ensure_one()
        reduced_limit = self._rule_parameter('IL_%s_NI_REDUCED_LIMIT' % prefix)
        max_base = self._rule_parameter('IL_%s_NI_MAX_BASE' % prefix)
        capped = min(base, max_base)
        reduced_portion = min(capped, reduced_limit)
        full_portion = max(capped - reduced_limit, 0.0)
        reduced_rate = self._rule_parameter(reduced_rate_code)
        full_rate = self._rule_parameter(full_rate_code)
        return reduced_portion * reduced_rate / 100.0 + full_portion * full_rate / 100.0

    # ------------------------------------------------------------------
    # פנסיה / פיצויים / קרן השתלמות
    # ------------------------------------------------------------------
    def _il_pension_active(self):
        self.ensure_one()
        version = self.version_id
        if not version.il_pension_enabled:
            return False
        start = version.il_pension_start_date
        if start and start > self.date_to:
            return False
        return True

    def _il_capped_base(self, base, ceiling_code):
        self.ensure_one()
        ceiling = self.env['hr.rule.parameter']._get_parameter_from_code(
            ceiling_code, self.date_to, raise_if_not_found=False)
        if ceiling:
            return min(base, ceiling)
        return base

    def _il_deposit_active(self):
        """פיקדון עובד זר פעיל — מתאריך תחילת ההסדר, כאשר לא מופרשת פנסיה."""
        self.ensure_one()
        version = self.version_id
        return False

    def _il_sector_parameter(self, template, fallback_code=None):
        """Parameter resolved by employment sector, e.g. template
        'IL_FOR_DEPOSIT_%s_RATE' → IL_FOR_DEPOSIT_CONSTRUCTION_RATE."""
        self.ensure_one()
        sector = self.version_id.il_employment_sector
        if sector:
            value = self.env['hr.rule.parameter']._get_parameter_from_code(
                template % sector.upper(), self.date_to, raise_if_not_found=False)
            if value is not None:
                return value
        if fallback_code:
            return self.env['hr.rule.parameter']._get_parameter_from_code(
                fallback_code, self.date_to, raise_if_not_found=False) or 0.0
        return 0.0
