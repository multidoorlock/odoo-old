# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class HrPayrollInstructionWizard(models.TransientModel):
    """הוראה בודדת: יצירת Payment + Salary Adjustment יחד, ללא כל קשר
    ביניהם לאחר היצירה (סעיפים 82–91 באפיון)."""
    _name = 'hr.payroll.instruction.wizard'
    _description = 'הוראת תשלום והתאמת שכר'

    employee_id = fields.Many2one('hr.employee', string='עובד', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='איש קשר', compute='_compute_partner_id', store=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='חברה', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(string='סכום', required=True)
    note = fields.Text(string='הערה')

    # פרטי תשלום
    payment_date = fields.Date(string='תאריך תשלום', default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string='יומן',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    payment_method_line_id = fields.Many2one(
        'account.payment.method.line', string='אמצעי תשלום',
        domain="[('id', 'in', available_payment_method_line_ids)]")
    available_payment_method_line_ids = fields.Many2many(
        'account.payment.method.line', compute='_compute_available_payment_method_line_ids')
    partner_bank_id = fields.Many2one(
        'res.partner.bank', string='חשבון בנק', domain="[('partner_id', '=', partner_id)]")

    # פרטי התאמת שכר
    other_input_type_id = fields.Many2one(
        'hr.payslip.input.type', string='סוג התאמה', required=True,
        domain="[('available_in_attachments', '=', True)]")
    il_effect_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
    ], string='סוג השפעה', required=True, default='gross')
    date_start = fields.Date(string='תאריך תחילה', required=True, default=fields.Date.context_today)

    @api.depends('employee_id')
    def _compute_partner_id(self):
        for wizard in self:
            wizard.partner_id = wizard.employee_id.work_contact_id

    @api.depends('journal_id')
    def _compute_available_payment_method_line_ids(self):
        for wizard in self:
            wizard.available_payment_method_line_ids = (
                wizard.journal_id.outbound_payment_method_line_ids)

    @api.constrains('amount')
    def _check_amount(self):
        for wizard in self:
            if wizard.amount <= 0:
                raise UserError('הסכום חייב להיות גדול מאפס.')

    def action_create_instruction(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError('לעובד שנבחר אין איש קשר (Partner) מקושר.')
        if not self.partner_bank_id:
            raise UserError('יש לבחור חשבון בנק לתשלום.')
        for field_name, label in (('journal_id', 'יומן'), ('payment_method_line_id', 'אמצעי תשלום'),
                                  ('payment_date', 'תאריך תשלום')):
            if not self[field_name]:
                raise UserError('שדה "%s" הוא חובה.' % label)

        self.env['hr.salary.attachment'].create({
            'employee_ids': [(6, 0, [self.employee_id.id])],
            'company_id': self.company_id.id,
            'other_input_type_id': self.other_input_type_id.id,
            'il_effect_type': self.il_effect_type,
            'duration_type': 'one',
            'monthly_amount': self.amount,
            'date_start': self.date_start,
            'description': self.note,
        })
        self.env['account.payment'].create({
            'partner_id': self.partner_id.id,
            'partner_type': 'supplier',
            'amount': self.amount,
            'memo': self.note,
            'payment_type': 'outbound',
            'company_id': self.company_id.id,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'payment_method_line_id': self.payment_method_line_id.id,
            'currency_id': self.currency_id.id,
            'partner_bank_id': self.partner_bank_id.id,
            'payslip_id': False,
        })
        return {'type': 'ir.actions.act_window_close'}
