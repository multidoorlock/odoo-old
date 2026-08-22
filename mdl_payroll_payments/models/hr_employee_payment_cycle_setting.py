# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

IL_CYCLE_TYPES = [
    ('advance', 'מפרעות'),
    ('food', 'אוכל'),
    ('loan', 'הלוואות'),
]


class HrEmployeePaymentCycleSetting(models.Model):
    """שלוש שורות הגדרה קבועות לכל עובד — מפרעות / אוכל / הלוואות
    (סעיפים 57–60 באפיון)."""
    _name = 'hr.employee.payment.cycle.setting'
    _description = 'הגדרת מחזורי תשלום לעובד'
    _order = 'employee_id, cycle_type'

    employee_id = fields.Many2one(
        'hr.employee', string='עובד', required=True, index=True, ondelete='cascade')
    cycle_type = fields.Selection(
        IL_CYCLE_TYPES, string='סוג מחזור', required=True)
    enabled = fields.Boolean(string='פעיל', default=False)
    amount = fields.Monetary(string='סכום')
    currency_id = fields.Many2one(
        'res.currency', related='employee_id.company_id.currency_id', readonly=True)

    _unique_employee_cycle_type = models.Constraint(
        'unique (employee_id, cycle_type)',
        'לכל עובד יכולה להיות שורה אחת בלבד לכל סוג מחזור.',
    )

    def init(self):
        # השלמת השורות החסרות לעובדים קיימים בעת התקנה / שדרוג המודול.
        super().init()
        self.env.cr.execute("""
            INSERT INTO hr_employee_payment_cycle_setting (employee_id, cycle_type, enabled, amount)
            SELECT e.id, t.cycle_type, FALSE, 0
            FROM hr_employee e
            CROSS JOIN (VALUES ('advance'), ('food'), ('loan')) AS t(cycle_type)
            WHERE NOT EXISTS (
                SELECT 1 FROM hr_employee_payment_cycle_setting s
                WHERE s.employee_id = e.id AND s.cycle_type = t.cycle_type
            )
        """)

    @api.constrains('amount')
    def _check_amount(self):
        for setting in self:
            if setting.amount < 0:
                raise ValidationError('סכום ברירת המחדל למחזור אינו יכול להיות שלילי.')

    def write(self, vals):
        if 'cycle_type' in vals and any(
                setting.cycle_type != vals['cycle_type'] for setting in self):
            raise ValidationError('לא ניתן לשנות את סוג המחזור של שורת הגדרה קיימת.')
        if 'employee_id' in vals and any(
                setting.employee_id.id != vals['employee_id'] for setting in self):
            raise ValidationError('לא ניתן להעביר שורת הגדרה לעובד אחר.')
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_fixed_rows(self):
        # שלוש השורות קבועות; הן נמחקות רק יחד עם העובד (Cascade ברמת DB).
        raise ValidationError(
            'לא ניתן למחוק את שורות הגדרת המחזורים של עובד — ניתן רק לכבות אותן.')
