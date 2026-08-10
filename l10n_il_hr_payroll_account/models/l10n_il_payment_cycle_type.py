from odoo import api, fields, models

# סוג מחזור תשלומים - פיקליסט קבוע (לא עוד טבלה שמנוהלת ע"י המשתמש). "תלוש"
# הוא סוג מיוחד: אף מסך יצירה ידנית (לא באשף מחזור, לא בטופס העובד) לא מציג
# אותו כאפשרות לבחירה - הוא נקבע *אך ורק* אוטומטית כשמשלמים Pay Run (ראו
# l10n_il_payslip_run_payment_wizard.py). "אוכל" הוא הסוג המיוחד היחיד עם
# השפעה אמיתית: תשלומים מסוג הזה נוצרים ישר בסטטוס 'canceled' (ראו
# l10n_il_payment_batch.py.action_create_batch) - כל שאר הסוגים זהים לגמרי
# מבחינת מה שהם עושים בפועל, הם רק תיוג/סינון.
L10N_IL_CYCLE_TYPE_SELECTION = [
    ("food", "אוכל"),
    ("advance", "מפרעה"),
    ("payslip", "תלוש"),
    ("loan", "הלוואה"),
]
# הסוגים שניתן לבחור ידנית (בטופס העובד, באשף מחזור) - "תלוש" מכוון תמיד
# אוטומטית בלבד, לעולם לא מוצג כאפשרות בחירה למשתמש.
L10N_IL_MANUAL_CYCLE_TYPES = ["food", "advance", "loan"]


class L10nIlEmployeePaymentCycleLine(models.Model):
    """סכום קבוע לעובד עבור סוג מחזור תשלומים - טבלה **קבועה** (3 שורות בדיוק,
    אחת לכל סוג בר-בחירה-ידנית: אוכל/מפרעה/הלוואה - "תלוש" לא מופיע כאן כלל,
    ראו L10N_IL_MANUAL_CYCLE_TYPES) שנזרעת אוטומטית לכל עובד (ראו hr_employee.py) -
    אי אפשר להוסיף או למחוק שורות ממנה (ראו create="false" delete="false" בתצוגה),
    רק לסמן "נכלל" ולהזין סכום."""
    _name = "l10n.il.employee.payment.cycle.line"
    _description = "סכום מחזור תשלומים לעובד"
    _order = "cycle_type"

    employee_id = fields.Many2one("hr.employee", string="עובד", required=True, ondelete="cascade", index=True)
    cycle_type = fields.Selection(
        [(k, v) for k, v in L10N_IL_CYCLE_TYPE_SELECTION if k in L10N_IL_MANUAL_CYCLE_TYPES],
        string="סוג", required=True)
    included = fields.Boolean(string="נכלל")
    amount = fields.Monetary(string="סכום")
    currency_id = fields.Many2one(related="employee_id.company_id.currency_id")

    @api.onchange("included")
    def _onchange_included(self):
        if not self.included:
            self.amount = 0.0
