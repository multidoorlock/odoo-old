from odoo import api, fields, models
from odoo.exceptions import UserError

from .l10n_il_salary_adjustment import L10N_IL_POSITIVE_ONLY_TYPES


class L10nIlSalaryAdjustmentPaymentWizard(models.TransientModel):
    """"פעולה": יוצרת יחד תשלום (account.payment) והתאמת שכר חד-פעמית
    (hr.salary.attachment) באותם שדות (עובד/סכום/תאריך/הערה) - אבל בלי שום
    קשר ביניהם, שתי רשומות עצמאיות לגמרי. גישה: כפתור "יצירת פעולה" תחת תפריט
    התשלומים (לא קשור לעובד ספציפי - employee_id שדה רגיל לבחירה).
    """
    _name = "l10n.il.salary.adjustment.payment.wizard"
    _description = "יצירת פעולה"

    employee_id = fields.Many2one("hr.employee", string="עובד", required=True)
    other_input_type_id = fields.Many2one(
        "hr.payslip.input.type", string="סוג", required=True,
        # הוראה תמיד חיובית (מלווה תשלום יוצא לעובד) - לא ניתן לבחור כאן סוג
        # שסימנו נקבע כשלילי (ראו L10N_IL_NEGATIVE_ONLY_TYPES ב-l10n_il_salary_adjustment.py).
        domain=[("available_in_attachments", "=", True), ("code", "in", list(L10N_IL_POSITIVE_ONLY_TYPES))],
    )
    l10n_il_impact_type = fields.Selection(
        [("gross", "ברוטו"), ("net", "נטו")], string="סוג השפעה", default="gross", required=True)
    amount = fields.Monetary(string="סכום", required=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id)
    date = fields.Date(string="תאריך", required=True, default=fields.Date.context_today)
    memo = fields.Char(string="הערה")
    journal_id = fields.Many2one("account.journal", string="יומן")
    payment_method_line_id = fields.Many2one(
        "account.payment.method.line", string="אמצעי תשלום",
        domain="[('journal_id', 'in', [journal_id, False])]",
    )
    l10n_il_batch_id = fields.Many2one("l10n.il.payment.batch", string="מחזור")

    @api.onchange("journal_id")
    def _onchange_journal_id(self):
        if self.payment_method_line_id.journal_id and self.payment_method_line_id.journal_id != self.journal_id:
            self.payment_method_line_id = False

    @api.constrains("amount")
    def _check_amount_positive(self):
        for wizard in self:
            if wizard.amount <= 0:
                raise UserError("הסכום חייב להיות חיובי.")

    def action_create(self):
        self.ensure_one()
        if not self.employee_id.work_contact_id:
            raise UserError("לעובד הזה אין איש-קשר (work_contact_id) לקשר אליו תשלום.")

        # "הוראה" בודדת *היא* מחזור מסוג 'instruction' עם עובד יחיד - כדי
        # שתמיד יישאר רשומה אחת לצפייה במסך "מחזורים והוראות" הרגיל, בדיוק
        # כמו הוראה שנוצרה דרך אשף המחזור המרובה (l10n.il.payment.batch.wizard) -
        # לא שני רשומות יתומות בלי שום דבר מאחד אותן.
        batch = self.l10n_il_batch_id
        if not batch:
            batch = self.env["l10n.il.payment.batch"].create({
                "name": f"הוראה - {self.employee_id.name}",
                "date": self.date,
                "l10n_il_batch_kind": "instruction",
            })

        self.env["hr.salary.attachment"].create({
            "employee_ids": [(6, 0, [self.employee_id.id])],
            "other_input_type_id": self.other_input_type_id.id,
            "l10n_il_impact_type": self.l10n_il_impact_type,
            "monthly_amount": self.amount,
            "duration_type": "one",
            "date_start": self.date,
            "description": self.memo,
            "l10n_il_batch_id": batch.id,
        })
        payment_vals = {}
        if self.journal_id:
            payment_vals["journal_id"] = self.journal_id.id
        if self.payment_method_line_id:
            payment_vals["payment_method_line_id"] = self.payment_method_line_id.id
        self.env["account.payment"].create({
            **payment_vals,
            "partner_id": self.employee_id.work_contact_id.id,
            "partner_type": "supplier",
            "payment_type": "outbound",
            "amount": self.amount,
            "date": self.date,
            "memo": self.memo,
            "state": "in_process",
            "l10n_il_batch_id": batch.id,
        })

        return {
            "type": "ir.actions.act_window",
            "name": "מחזור",
            "res_model": "l10n.il.payment.batch",
            "res_id": batch.id,
            "view_mode": "form",
        }
