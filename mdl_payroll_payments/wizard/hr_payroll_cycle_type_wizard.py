# -*- coding: utf-8 -*-
from odoo import fields, models


class HrPayrollCycleTypeWizard(models.TransientModel):
    """אשף בחירת סוג המחזור שייפתח (סעיפים 63–65 באפיון)."""
    _name = 'hr.payroll.cycle.type.wizard'
    _description = 'בחירת סוג מחזור'

    cycle_kind = fields.Selection([
        ('payment', 'תשלומים'),
        ('instruction', 'הוראות'),
        ('salary_adjustment', 'התאמות שכר'),
    ], string='סוג מחזור', required=True)

    def action_next(self):
        self.ensure_one()
        cycle = self.env['hr.payroll.cycle'].create({'cycle_kind': self.cycle_kind})
        # ממשיך את שרשרת ה-Popups בשלב הבא (פרטי המחזור) — לא מסך מלא.
        return cycle._il_reopen(
            'mdl_payroll_payments.hr_payroll_cycle_view_form_header', 'פרטי המחזור')
