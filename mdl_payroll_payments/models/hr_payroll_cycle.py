# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

CYCLE_KINDS = [
    ('payment', 'תשלומים'),
    ('instruction', 'הוראות'),
    ('salary_adjustment', 'התאמות שכר'),
]
CYCLE_TYPES = [
    ('advance', 'מפרעות'),
    ('food', 'אוכל'),
    ('loan', 'הלוואות'),
]


class HrPayrollCycle(models.Model):
    """מחזור אחד המשותף לשלושת הסוגים (סעיפים 61–117 באפיון): תשלומים,
    הוראות (Payment + Salary Adjustment לכל עובד, ללא קשר ביניהם) והתאמות
    שכר בלבד."""
    _name = 'hr.payroll.cycle'
    _description = 'מחזור תשלומים / הוראות / התאמות שכר'
    _order = 'id desc'

    name = fields.Char(
        string='מספר', required=True, readonly=True, copy=False,
        default=lambda self: self.env._('New'))
    cycle_kind = fields.Selection(
        CYCLE_KINDS, string='סוג מחזור', required=True, readonly=True)
    cycle_type = fields.Selection(
        CYCLE_TYPES, string='קטגוריה', required=False)
    company_id = fields.Many2one(
        'res.company', string='חברה', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    state = fields.Selection([
        ('draft', 'טיוטה'),
        ('generated', 'הופק'),
    ], default='draft', required=True, copy=False)
    note = fields.Text(string='הערה')
    line_ids = fields.One2many(
        'hr.payroll.cycle.line', 'cycle_id', string='שורות')
    equal_amount = fields.Monetary(string='סכום אחיד')

    # ------------------------------------------------------------------
    # פרטי תשלום (Payment / Instruction בלבד — סעיף 76)
    # ------------------------------------------------------------------
    payment_date = fields.Date(string='תאריך תשלום', default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string='יומן',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    payment_method_line_id = fields.Many2one(
        'account.payment.method.line', string='אמצעי תשלום',
        domain="[('id', 'in', available_payment_method_line_ids)]")
    available_payment_method_line_ids = fields.Many2many(
        'account.payment.method.line', compute='_compute_available_payment_method_line_ids')

    # ------------------------------------------------------------------
    # פרטי התאמת שכר (Instruction / Salary Adjustment Cycle — סעיפים 86, 93)
    # ------------------------------------------------------------------
    other_input_type_id = fields.Many2one(
        'hr.payslip.input.type', string='סוג התאמה',
        domain="[('available_in_attachments', '=', True)]")
    il_effect_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
    ], string='סוג השפעה', default='gross')
    duration_type = fields.Selection([
        ('one', 'חד פעמי'),
        ('limited', 'מוגבל'),
        ('unlimited', 'בלתי מוגבל'),
    ], string='משך', default='one')
    date_start = fields.Date(string='תאריך תחילה', default=fields.Date.context_today)

    # ------------------------------------------------------------------
    # מונים (Smart Buttons — סעיף 115)
    # ------------------------------------------------------------------
    payment_count = fields.Integer(compute='_compute_counts')
    salary_adjustment_count = fields.Integer(compute='_compute_counts')
    employee_count = fields.Integer(compute='_compute_counts')

    @api.depends('journal_id')
    def _compute_available_payment_method_line_ids(self):
        for cycle in self:
            cycle.available_payment_method_line_ids = (
                cycle.journal_id.outbound_payment_method_line_ids)

    def _compute_counts(self):
        payments = self.env['account.payment']._read_group(
            [('payroll_cycle_id', 'in', self.ids)], ['payroll_cycle_id'], ['__count'])
        payment_map = {cycle.id: count for cycle, count in payments}
        adjustments = self.env['hr.salary.attachment']._read_group(
            [('payroll_cycle_id', 'in', self.ids)], ['payroll_cycle_id'], ['__count'])
        adjustment_map = {cycle.id: count for cycle, count in adjustments}
        for cycle in self:
            cycle.payment_count = payment_map.get(cycle.id, 0)
            cycle.salary_adjustment_count = adjustment_map.get(cycle.id, 0)
            cycle.employee_count = len(cycle.line_ids.filtered('include'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.payroll.cycle') or self.env._('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # אכלוס שורות: מושכות עובדים לפי הגדרות מחזורי התשלום שלהם (סעיף 69),
    # או כל עובדי החברה עבור מחזור התאמות שכר (סעיף 102).
    # ------------------------------------------------------------------
    @api.onchange('cycle_kind', 'cycle_type', 'company_id')
    def _onchange_il_populate_lines(self):
        for cycle in self:
            if not cycle.company_id:
                continue
            if cycle.cycle_kind in ('payment', 'instruction'):
                if not cycle.cycle_type:
                    cycle.line_ids = [(5, 0, 0)]
                    continue
                settings = self.env['hr.employee.payment.cycle.setting'].search([
                    ('cycle_type', '=', cycle.cycle_type),
                    ('enabled', '=', True),
                    ('employee_id.company_id', '=', cycle.company_id.id),
                ])
                cycle.line_ids = [(5, 0, 0)] + [(0, 0, {
                    'employee_id': setting.employee_id.id,
                    'amount': setting.amount,
                    'partner_bank_id': setting.employee_id.work_contact_id.bank_ids[:1].id,
                }) for setting in settings]
            elif cycle.cycle_kind == 'salary_adjustment':
                employees = self.env['hr.employee'].search([
                    ('company_id', '=', cycle.company_id.id)])
                cycle.line_ids = [(5, 0, 0)] + [(0, 0, {
                    'employee_id': employee.id,
                    'amount': 0.0,
                }) for employee in employees]

    # ------------------------------------------------------------------
    # שרשרת Popups ליצירה: סוג (Wizard נפרד) → פרטי המחזור → שורות/הפקה.
    # אותה רשומה אמיתית נפתחת מחדש עם View שונה בכל שלב — לא Wizard זמני
    # נפרד לכל שלב — כדי לשמור על onchange/ולידציה עקביים בין השלבים.
    # ------------------------------------------------------------------
    def _il_reopen(self, view_xmlid, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'hr.payroll.cycle',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref(view_xmlid).id, 'form')],
            'target': 'new',
        }

    def action_goto_lines_step(self):
        self.ensure_one()
        if self.cycle_kind in ('payment', 'instruction') and not self.cycle_type:
            raise UserError('יש לבחור קטגוריית מחזור.')
        if self.cycle_kind in ('instruction', 'salary_adjustment') and not self.other_input_type_id:
            raise UserError('יש לבחור סוג התאמת שכר.')
        if not self.line_ids:
            self._onchange_il_populate_lines()
        return self._il_reopen('mdl_payroll_payments.hr_payroll_cycle_view_form_lines', 'בחירת עובדים')

    def action_back_to_header_step(self):
        self.ensure_one()
        return self._il_reopen('mdl_payroll_payments.hr_payroll_cycle_view_form_header', 'פרטי המחזור')

    def action_cancel_creation(self):
        for cycle in self:
            if cycle.state == 'draft' and not cycle.payment_count and not cycle.salary_adjustment_count:
                cycle.unlink()
        return {'type': 'ir.actions.act_window_close'}

    def action_apply_equal_amount(self):
        for cycle in self:
            cycle.line_ids.filtered('include').write({'amount': cycle.equal_amount})

    def action_reset_amounts(self):
        for cycle in self:
            for line in cycle.line_ids:
                setting = self.env['hr.employee.payment.cycle.setting'].search([
                    ('employee_id', '=', line.employee_id.id),
                    ('cycle_type', '=', cycle.cycle_type),
                ], limit=1)
                line.write({
                    'amount': setting.amount if setting else 0.0,
                    'include': True,
                    'partner_bank_id': line.employee_id.work_contact_id.bank_ids[:1].id,
                })

    # ------------------------------------------------------------------
    # ולידציות (סעיפים 109–111)
    # ------------------------------------------------------------------
    def _il_validate_generate(self, included_lines):
        self.ensure_one()
        if self.cycle_kind in ('payment', 'instruction'):
            if not self.cycle_type:
                raise ValidationError('יש לבחור קטגוריית מחזור.')
            for field_name, label in (('payment_date', 'תאריך תשלום'), ('journal_id', 'יומן'),
                                      ('payment_method_line_id', 'אמצעי תשלום')):
                if not self[field_name]:
                    raise ValidationError('שדה "%s" הוא חובה.' % label)
        if self.cycle_kind in ('instruction', 'salary_adjustment'):
            if not self.other_input_type_id:
                raise ValidationError('יש לבחור סוג התאמת שכר.')
            if not self.il_effect_type:
                raise ValidationError('יש לבחור סוג השפעה (ברוטו / נטו).')
            if not self.date_start:
                raise ValidationError('יש לבחור תאריך תחילה.')
        if not included_lines:
            raise ValidationError('אין שורות הכלולות ביצירה.')
        for line in included_lines:
            if not line.employee_id:
                raise ValidationError('שורה ללא עובד.')
            if line.employee_id.company_id != self.company_id:
                raise ValidationError('העובד %s אינו שייך לחברת המחזור.' % line.employee_id.name)
            if self.currency_id.compare_amounts(line.amount, 0.0) <= 0:
                raise ValidationError('הסכום עבור %s חייב להיות גדול מאפס.' % line.employee_id.name)
            if not line.partner_id:
                raise ValidationError('לעובד %s אין איש קשר (Partner) מקושר.' % line.employee_id.name)
            if self.cycle_kind in ('payment', 'instruction') and not line.partner_bank_id:
                raise ValidationError('לעובד %s אין חשבון בנק מוגדר.' % line.employee_id.name)

    def _il_payment_vals(self, line):
        self.ensure_one()
        return {
            'partner_id': line.partner_id.id,
            'partner_type': 'supplier',
            'amount': line.amount,
            'partner_bank_id': line.partner_bank_id.id,
            'payment_type': 'outbound',
            'company_id': self.company_id.id,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'payment_method_line_id': self.payment_method_line_id.id,
            'currency_id': self.currency_id.id,
            'memo': self.note,
            'payslip_id': False,
            'payroll_cycle_id': self.id,
        }

    def _il_salary_adjustment_vals(self, line):
        self.ensure_one()
        return {
            'employee_ids': [(6, 0, [line.employee_id.id])],
            'company_id': self.company_id.id,
            'other_input_type_id': self.other_input_type_id.id,
            'il_effect_type': self.il_effect_type,
            'duration_type': self.duration_type if self.cycle_kind == 'salary_adjustment' else 'one',
            'monthly_amount': line.amount,
            'date_start': self.date_start,
            'description': self.note,
            'payroll_cycle_id': self.id,
        }

    def action_generate(self):
        for cycle in self:
            if cycle.state != 'draft':
                raise UserError('ניתן להפיק רק מחזור בטיוטה.')
            included = cycle.line_ids.filtered('include')
            cycle._il_validate_generate(included)

            payments = self.env['account.payment']
            if cycle.cycle_kind in ('payment', 'instruction'):
                payments = self.env['account.payment'].create(
                    [cycle._il_payment_vals(line) for line in included])
                if cycle.cycle_type == 'food':
                    payments.action_post()
                    payments.action_cancel()

            if cycle.cycle_kind in ('instruction', 'salary_adjustment'):
                self.env['hr.salary.attachment'].create(
                    [cycle._il_salary_adjustment_vals(line) for line in included])

            cycle.state = 'generated'
        # סגירת ה-Popup וחזרה לרשימת המחזורים המרועננת.
        return self.env['ir.actions.act_window']._for_xml_id(
            'mdl_payroll_payments.action_hr_payroll_cycle')

    def action_reset_draft(self):
        for cycle in self:
            if cycle.payment_count or cycle.salary_adjustment_count:
                raise UserError(
                    'לא ניתן להחזיר מחזור שכבר יצר Records לטיוטה. ניתן ליצור מחזור חדש.')
            cycle.state = 'draft'

    def action_open_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'תשלומים',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('payroll_cycle_id', '=', self.id)],
        }

    def action_open_salary_adjustments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'התאמות שכר',
            'res_model': 'hr.salary.attachment',
            'view_mode': 'list,form',
            'domain': [('payroll_cycle_id', '=', self.id)],
        }


class HrPayrollCycleLine(models.Model):
    _name = 'hr.payroll.cycle.line'
    _description = 'שורת מחזור'
    _order = 'id'

    cycle_id = fields.Many2one(
        'hr.payroll.cycle', string='מחזור', required=True, index=True, ondelete='cascade')
    include = fields.Boolean(string='לכלול', default=True)
    employee_id = fields.Many2one('hr.employee', string='עובד', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='איש קשר', compute='_compute_partner_id', store=True, readonly=True)
    amount = fields.Monetary(string='סכום')
    partner_bank_id = fields.Many2one(
        'res.partner.bank', string='חשבון בנק',
        domain="[('partner_id', '=', partner_id)]")
    currency_id = fields.Many2one(related='cycle_id.currency_id', readonly=True)

    @api.depends('employee_id')
    def _compute_partner_id(self):
        for line in self:
            line.partner_id = line.employee_id.work_contact_id
