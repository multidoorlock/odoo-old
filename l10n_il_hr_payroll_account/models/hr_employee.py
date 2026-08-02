from odoo import api, fields, models

from .l10n_il_payment_cycle_type import L10N_IL_MANUAL_CYCLE_TYPES


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    l10n_il_payment_cycle_line_ids = fields.One2many(
        "l10n.il.employee.payment.cycle.line", "employee_id", string="סכומי מחזורי תשלומים",
        groups="hr_payroll.group_hr_payroll_user",
    )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._l10n_il_seed_payment_cycle_lines()
        return employees

    def _l10n_il_seed_payment_cycle_lines(self):
        """זורעת בדיוק 3 שורות קבועות (אוכל/מפרעה/הלוואה) לכל עובד חדש - הטבלה
        עצמה קבועה (אי אפשר להוסיף/למחוק שורות, ראו l10n_il_payment_cycle_type.py),
        רק "נכלל"+סכום ניתנים לעריכה. משמשת גם ל-backfill חד-פעמי (ראו
        post_init_hook ב-__init__.py) לעובדים קיימים שנוצרו לפני הפיצ'ר הזה."""
        Line = self.env["l10n.il.employee.payment.cycle.line"]
        existing = Line.search([("employee_id", "in", self.ids)])
        existing_by_emp = {}
        for line in existing:
            existing_by_emp.setdefault(line.employee_id.id, set()).add(line.cycle_type)
        vals_list = []
        for employee in self:
            have = existing_by_emp.get(employee.id, set())
            for cycle_type in L10N_IL_MANUAL_CYCLE_TYPES:
                if cycle_type not in have:
                    vals_list.append({
                        "employee_id": employee.id, "cycle_type": cycle_type,
                        "included": False, "amount": 0.0,
                    })
        if vals_list:
            Line.create(vals_list)
