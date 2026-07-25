from odoo import api, fields, models
from odoo.exceptions import UserError

from .account_payment import L10N_IL_EMPLOYEE_PAYMENT_TYPE_SELECTION


class L10nIlPaymentBatch(models.Model):
    """מחזור תשלומים: קבוצת תשלומי עובדים (account.payment) שנוצרו יחד לכמה
    עובדים בבת אחת (למשל מפרעות חודשיות)."""
    _name = "l10n.il.payment.batch"
    _description = "מחזור תשלומים"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="שם", required=True, tracking=True)
    date = fields.Date(string="תאריך", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="חברה", default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    payment_ids = fields.One2many("account.payment", "l10n_il_batch_id", string="תשלומים")
    total_amount = fields.Monetary(string="סה״כ סכום", compute="_compute_totals")

    @api.depends("payment_ids.amount")
    def _compute_totals(self):
        for batch in self:
            batch.total_amount = sum(batch.payment_ids.mapped("amount"))


class L10nIlPaymentBatchWizard(models.TransientModel):
    """אשף דו-שלבי ליצירת מחזור תשלומים לעובדים: שלב 1 - פרטי התשלום המשותפים
    (בדיוק כמו יצירת תשלום בודד, ללא סכום ובלי עובד ספציפי); שלב 2 - בחירת
    העובדים וסכום לכל אחד.
    """
    _name = "l10n.il.payment.batch.wizard"
    _description = "יצירת מחזור תשלומים"

    name = fields.Char(
        string="שם", required=True,
        default=lambda self: f"תשלומים {fields.Date.context_today(self).strftime('%m/%Y')}")
    date = fields.Date(string="תאריך", required=True, default=fields.Date.context_today)
    payment_type = fields.Selection(
        selection=[("outbound", "שליחה"), ("inbound", "קבלה")],
        string="סוג תנועה", required=True, default="outbound",
    )
    l10n_il_employee_payment_type = fields.Selection(
        selection=L10N_IL_EMPLOYEE_PAYMENT_TYPE_SELECTION,
        string="סוג תשלום לעובד", required=True, default="advance",
    )
    l10n_il_affects_payroll = fields.Boolean(string="השפעה על שכר", default=True)
    journal_id = fields.Many2one("account.journal", string="יומן")
    payment_method_line_id = fields.Many2one("account.payment.method.line", string="אמצעי תשלום")
    memo = fields.Char(string="פתק")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id)
    set_all_amount = fields.Monetary(string="הגדר לכולם")
    line_ids = fields.One2many(
        "l10n.il.payment.batch.wizard.line", "wizard_id", string="עובדים")

    def _reopen_step2(self):
        return {
            "type": "ir.actions.act_window",
            "name": "מחזור תשלומים - עובדים וסכומים",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("l10n_il_hr_payroll.l10n_il_payment_batch_wizard_view_form_step2").id,
            "target": "new",
        }

    def action_back(self):
        """חזרה משלב 2 לשלב 1 (במקום סגירת האשף)."""
        return {
            "type": "ir.actions.act_window",
            "name": "מחזור תשלומים חדש",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("l10n_il_hr_payroll.l10n_il_payment_batch_wizard_view_form_step1").id,
            "target": "new",
        }

    def action_next(self):
        """שלב 2: טעינת כל העובדים (מסוננים לכשירות למפרעה אם רלוונטי) עם סכום
        ברירת מחדל כשמתאים."""
        self.ensure_one()
        employees = self.env["hr.employee"].search([
            ("company_id", "in", self.env.companies.ids),
        ])
        if self.l10n_il_employee_payment_type == "advance":
            employees = employees.filtered(lambda e: e.l10n_il_has_advance)
        if not employees:
            raise UserError("אין עובדים מתאימים.")
        lines = [(0, 0, {
            "employee_id": emp.id,
            "amount": emp.l10n_il_advance_amount if self.l10n_il_employee_payment_type == "advance" else 0.0,
            "included": True,
        }) for emp in employees]
        self.line_ids = [(5, 0, 0)] + lines
        return self._reopen_step2()

    def action_set_all_amount(self):
        """מגדיר את הסכום שהוזן ב'הגדר לכולם' על כל השורות המסומנות."""
        self.ensure_one()
        self.line_ids.filtered("included").write({"amount": self.set_all_amount})
        return self._reopen_step2()

    def action_reset_advance_amounts(self):
        """רק במחזור מפרעות: מושך מחדש את סכום המפרעה המוגדר לכל עובד מסומן."""
        self.ensure_one()
        for line in self.line_ids.filtered("included"):
            line.amount = line.employee_id.l10n_il_advance_amount
        return self._reopen_step2()

    def action_create_batch(self):
        self.ensure_one()
        included = self.line_ids.filtered("included")
        if not included:
            raise UserError("לא נבחר אף עובד לכלול במחזור.")
        if any(not line.amount for line in included):
            raise UserError("יש להזין סכום לכל העובדים שנבחרו.")
        batch = self.env["l10n.il.payment.batch"].create({
            "name": self.name,
            "date": self.date,
        })
        vals_list = []
        for line in included:
            vals = {
                "partner_id": line.employee_id.work_contact_id.id,
                "partner_type": "supplier",
                "payment_type": self.payment_type,
                "l10n_il_employee_payment_type": self.l10n_il_employee_payment_type,
                "l10n_il_affects_payroll": self.l10n_il_affects_payroll,
                "amount": line.amount,
                "date": self.date,
                "memo": self.memo,
                "l10n_il_batch_id": batch.id,
                "state": "in_process",
            }
            if self.journal_id:
                vals["journal_id"] = self.journal_id.id
            if self.payment_method_line_id:
                vals["payment_method_line_id"] = self.payment_method_line_id.id
            vals_list.append(vals)
        self.env["account.payment"].create(vals_list)
        return {
            "type": "ir.actions.act_window",
            "name": "מחזור תשלומים",
            "res_model": "l10n.il.payment.batch",
            "res_id": batch.id,
            "view_mode": "form",
        }


class L10nIlPaymentBatchWizardLine(models.TransientModel):
    _name = "l10n.il.payment.batch.wizard.line"
    _description = "שורת עובד במחזור תשלומים"

    wizard_id = fields.Many2one("l10n.il.payment.batch.wizard", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", string="עובד", required=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    amount = fields.Monetary(string="סכום")
    included = fields.Boolean(string="נכלל", default=True)
