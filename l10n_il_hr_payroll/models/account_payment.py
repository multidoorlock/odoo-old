from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero

# קודי סוגי-קלט של התאמות שכר שהכלל שלהם מנכה (הופך סימן) במקום מוסיף ישירות
# ל-NET - צריך לדעת את זה כדי לקבוע אם התאמה מסוימת "חיובית" (מקבלת תשלום
# נפרד משלה) או "שלילית" (רק מקטינה את שארית תשלום ה"תלוש"), בלי תלות בסימן
# הגולמי של hr.salary.attachment._get_active_amount() (שתמיד חיובי כברירת
# מחדל, גם עבור סוג ניכוי - ה"הפיכה לשלילי" קורית בתוך נוסחת הכלל עצמו).
L10N_IL_DEDUCTION_INPUT_CODES = {"IL_LOAN", "IL_MEALS", "IL_OTHER_DED"}

# משותף עם l10n.il.payment.batch.wizard - אותו "סוג תשלום לעובד" בדיוק בשני
# המסכים (יצירה בודדת ומחזור), מקור אמת יחיד.
L10N_IL_EMPLOYEE_PAYMENT_TYPE_SELECTION = [
    ("advance", "מפרעה"),
    ("loan", "הלוואה"),
    ("other", "אחר"),
    ("payslip", "תלוש"),
    ("salary_adjustment", "שינוי שכר"),
]


class AccountPayment(models.Model):
    """מרחיב תשלום חשבונאי (account.payment) כדי לתמוך בתשלומי עובדים (מפרעות,
    הלוואות וכו') לצד תשלומי ספקים/לקוחות רגילים - הכל נשמר באותה טבלת תשלומים
    אחת, באותו שדה שותף (partner_id) הקיים - בדיוק כמו שתשלומי ספק נוספו על גבי
    תשלומי לקוח: אין שדה "עובד" נפרד, רק סינון/כותרת שונים לאותו partner_id
    במסך הייעודי לשכר (ראו views/l10n_il_account_payment_views.xml). "העובד"
    של תשלום מסוים, כשצריך לוגיקת שכר, נגזר מ-partner_id.employee_ids (שדה
    הפוך קיים על res.partner מתוך hr.employee.work_contact_id).

    כשהתשלום הוא לעובד ומסומן "השפעה על שכר", הוא נאסף אוטומטית לתלוש השכר הבא
    של אותו עובד (ראו hr.payslip._l10n_il_collect_payments): תשלום ששלחנו לעובד
    (Send/outbound) מנוכה מהנטו לתשלום שלו; תשלום שהתקבל ממנו (Receive/inbound)
    נוסף לנטו לתשלום שלו.
    """
    _inherit = "account.payment"

    l10n_il_employee_payment_type = fields.Selection(
        selection=L10N_IL_EMPLOYEE_PAYMENT_TYPE_SELECTION,
        string="סוג תשלום לעובד", tracking=True,
    )
    l10n_il_affects_payroll = fields.Boolean(
        string="השפעה על שכר", tracking=True,
        help="מסומן: התשלום נאסף אוטומטית לתלוש השכר הבא של העובד. תשלום ששלחנו "
             "(Send) מנוכה מהנטו לתשלום שלו; תשלום שהתקבל (Receive) נוסף לנטו לתשלום שלו.",
    )
    l10n_il_batch_id = fields.Many2one(
        "l10n.il.payment.batch", string="מחזור תשלומים", index=True, ondelete="set null",
        help="ריק בתשלום בודד (off-cycle).",
    )
    payslip_id = fields.Many2one(
        "hr.payslip", string="תלוש מקושר", index=True, tracking=True,
        help="התלוש שבו נכלל התשלום. ניתן לקשר ידנית, אך חייב להיות תלוש של אותו עובד.",
    )

    @api.onchange("partner_id")
    def _onchange_l10n_il_partner_employee(self):
        employee = self.partner_id.employee_ids[:1]
        # אפשרות "מפרעה" רלוונטית רק לעובד שמסומן אצלו "קיים מפרעה" - אין
        # תמיכה טבעית ב-Odoo להסתיר אופציה בודדת מתוך שדה Selection לפי ערך
        # של שדה אחר, לכן זה נאכף כאן (ניקוי תגובתי) ובאילוץ השרת למטה
        # (_check_advance_eligibility), לא כהסתרה ויזואלית באפשרויות.
        if self.l10n_il_employee_payment_type == "advance" and employee and not employee.l10n_il_has_advance:
            self.l10n_il_employee_payment_type = False
        if self.payslip_id and self.payslip_id.employee_id != employee:
            self.payslip_id = False

    @api.onchange("l10n_il_affects_payroll")
    def _onchange_affects_payroll(self):
        if not self.l10n_il_affects_payroll:
            self.payslip_id = False

    @api.constrains("partner_id", "payslip_id")
    def _check_payslip_employee_match(self):
        for payment in self:
            if payment.payslip_id and payment.payslip_id.employee_id not in payment.partner_id.employee_ids:
                raise ValidationError("התלוש המקושר לתשלום חייב להיות תלוש של אותו עובד.")

    @api.constrains("partner_id", "l10n_il_employee_payment_type")
    def _check_advance_eligibility(self):
        for payment in self:
            if payment.l10n_il_employee_payment_type != "advance":
                continue
            employee = payment.partner_id.employee_ids[:1]
            if employee and not employee.l10n_il_has_advance:
                raise ValidationError("אי אפשר לבחור 'מפרעה' לעובד שלא מסומן אצלו 'קיים מפרעה'.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._l10n_il_clear_payslip_if_not_affecting(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._l10n_il_clear_payslip_if_not_affecting(vals)
        return super().write(vals)

    @staticmethod
    def _l10n_il_clear_payslip_if_not_affecting(vals):
        """התלוש המקושר רלוונטי רק לתשלום עם 'השפעה על שכר' - אם השדה מבוטל
        (ולא נקבע payslip_id מפורשות באותה כתיבה, כמו בזרימת יצירת תשלומי
        התלוש האוטומטיים) יש לוודא שהוא אכן מתאפס ולא נשאר ערך ישן/מוטעה.
        """
        if vals.get("l10n_il_affects_payroll") is False and "payslip_id" not in vals:
            vals["payslip_id"] = False


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    l10n_il_payment_ids = fields.One2many(
        "account.payment", "payslip_id", string="תשלומים")

    @api.model_create_multi
    def create(self, vals_list):
        slips = super().create(vals_list)
        slips._l10n_il_collect_payments()
        return slips

    def compute_sheet(self):
        self._l10n_il_collect_payments()
        return super().compute_sheet()

    def action_payslip_paid(self):
        to_process = self.filtered(lambda p: p.state != "paid")
        # חייבים לחשב את תשלומי התלוש/התאמות השכר *לפני* super(): קריאת ה-write
        # הילידית ל-state='paid' סוגרת (state='close') כל התאמת שכר חד-פעמית
        # ששולמה במלואה (ראו hr.payslip.write ב-hr_payroll הליבה) - לכן אחרי
        # super() הן כבר לא "open" ולא יימצאו יותר על ידי _l10n_il_valid_for_payslip.
        vals_list = to_process._l10n_il_compute_payslip_payment_vals()
        res = super().action_payslip_paid()
        if vals_list:
            self.env["account.payment"].create(vals_list)
        return res

    def _l10n_il_compute_payslip_payment_vals(self):
        """בכל סימון תלוש כ"שולם" נוצרים תשלומים (account.payment) שמייצגים את
        התשלום שבוצע בפועל בפירוט: תשלום אחד לכל התאמת שכר חיובית שלא סומנה
        "שולם" (למשל בונוס - עדיין לא שולמה חוץ לתלוש, לכן משולמת עכשיו יחד
        איתו), ותשלום אחד נוסף מסוג "תלוש" עבור השארית (הנטו לתשלום, בניכוי
        התאמות השכר האלו - כולל השליליות, שלא מקבלות שורת תשלום נפרדת משלהן
        אלא רק מקטינות את מה שבאמת משולם). כל אלו נוצרים כבר בסטטוס "שולם"
        (מייצגים תשלום שכבר בוצע), עם 'השפעה על שכר' כבוי - הם רק תיעוד של מה
        ששולם, לא קלט לחישוב תלוש עתידי. תשלומים קיימים (למשל מפרעה שסומנה
        "השפעה על שכר") כבר נסגרים/משויכים לתלוש הזה קודם לכן, בעת החישוב עצמו
        (ראו _l10n_il_collect_payments) - לא נוגעים בהם כאן. מחזיר vals לא
        יוצר ישירות, כדי לאפשר לקרוא לזה לפני super().action_payslip_paid().
        """
        vals_list = []
        for slip in self:
            if not slip.employee_id or not slip.employee_id.work_contact_id:
                continue
            already_created = self.env["account.payment"].search_count([
                ("payslip_id", "=", slip.id),
                ("l10n_il_employee_payment_type", "in", ("payslip", "salary_adjustment")),
            ])
            if already_created:
                continue
            net_to_pay_line = slip.line_ids.filtered(lambda l: l.code == "NET_TO_PAY")
            if not net_to_pay_line:
                continue
            net_to_pay = net_to_pay_line.total
            valid_unpaid = slip.employee_id.salary_attachment_ids.filtered(
                lambda a: not a.l10n_il_paid)._l10n_il_valid_for_payslip(slip)

            adjustments_total = 0.0
            for input_type_id, attachments in valid_unpaid.grouped("other_input_type_id").items():
                raw_amount = attachments._get_active_amount()
                sign = -1 if input_type_id.code in L10N_IL_DEDUCTION_INPUT_CODES else 1
                amount = raw_amount * sign
                adjustments_total += amount
                if amount > 0:
                    vals_list.append({
                        "partner_id": slip.employee_id.work_contact_id.id,
                        "partner_type": "supplier",
                        "payment_type": "outbound",
                        "l10n_il_employee_payment_type": "salary_adjustment",
                        "l10n_il_affects_payroll": False,
                        "memo": input_type_id.name,
                        "amount": amount,
                        "date": slip.paid_date or slip.date_to or fields.Date.today(),
                        "state": "paid",
                        "payslip_id": slip.id,
                    })

            payslip_amount = net_to_pay - adjustments_total
            if not float_is_zero(payslip_amount, precision_digits=2):
                vals_list.append({
                    "partner_id": slip.employee_id.work_contact_id.id,
                    "partner_type": "supplier",
                    "payment_type": "outbound" if payslip_amount >= 0 else "inbound",
                    "l10n_il_employee_payment_type": "payslip",
                    "l10n_il_affects_payroll": False,
                    "amount": abs(payslip_amount),
                    "date": slip.paid_date or slip.date_to or fields.Date.today(),
                    "state": "paid",
                    "payslip_id": slip.id,
                })
        return vals_list

    def _l10n_il_collect_payments(self):
        """איסוף כל תשלומי העובד (account.payment) שמשפיעים על שכר וסטטוסם "בביצוע"
        (in_process) לתלוש: סכימה (שלח = ניכוי, התקבל = תוספת) ל-Salary Input,
        וסימון כשולמו (state='paid') - כולל יצירת פקודת היומן החשבונאית בפועל.
        """
        input_type = self.env.ref("l10n_il_hr_payroll.input_il_payment_adj", raise_if_not_found=False)
        if not input_type:
            return
        for slip in self:
            if not slip.employee_id or not slip.employee_id.work_contact_id or slip.state not in ("draft", "verify"):
                continue
            # תנאי האיסוף: תשלום עובד בביצוע שעדיין לא מקושר לאף תלוש (פנוי
            # לתלוש הבא שיבוא), או שכבר מקושר ידנית ספציפית לתלוש הזה עצמו -
            # תשלום שקושר ידנית לתלוש אחר לא ייאסף על ידי תלוש אחר בטעות.
            # כולל גם תשלומים שכבר שולמו ושויכו לתלוש הזה בעבר (קריאה חוזרת
            # ל-compute_sheet לא תמחק את השורה שכבר נאספה בפעם הקודמת).
            payments = self.env["account.payment"].search([
                ("partner_id", "=", slip.employee_id.work_contact_id.id),
                ("l10n_il_affects_payroll", "=", True),
                "|",
                "&", ("state", "=", "in_process"), "|", ("payslip_id", "=", False), ("payslip_id", "=", slip.id),
                "&", ("state", "=", "paid"), ("payslip_id", "=", slip.id),
            ])
            input_line = slip.input_line_ids.filtered(lambda i: i.input_type_id == input_type)
            if payments:
                total = sum(
                    (payment.amount if payment.payment_type == "inbound" else -payment.amount)
                    for payment in payments
                )
                if input_line:
                    input_line.amount = total
                else:
                    self.env["hr.payslip.input"].create({
                        "payslip_id": slip.id,
                        "input_type_id": input_type.id,
                        "amount": total,
                    })
                to_mark = payments.filtered(lambda p: p.state == "in_process")
                if to_mark:
                    to_mark.write({"state": "paid", "payslip_id": slip.id})
            elif input_line:
                input_line.unlink()
