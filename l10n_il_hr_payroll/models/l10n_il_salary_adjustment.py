from odoo import api, fields, models
from odoo.fields import Command


class HrSalaryAttachment(models.Model):
    """התאמת שכר (Salary Adjustment): מרחיב את התכונה הקיימת של אודו בשדה "שולם".

    שדה 'שולם' קובע אם ההתאמה כבר שולמה לעובד מחוץ לתלוש (למשל במזומן): אם כן,
    הסכום עדיין נכנס לנטו הרגיל דרך שורת ה-Input הרגילה של הסוג (מנגנון קיים של
    hr.salary.attachment - לא נגעתי בו), אבל מנוכה בחזרה מ"נטו לתשלום" בלבד (ראו
    hr.payslip._compute_input_line_ids למטה) כדי שלא ישולם פעמיים. אם לא מסומן,
    ההתאמה רק נוספת לנטו כרגיל, ללא ניכוי נגדי.
    """
    _inherit = "hr.salary.attachment"

    l10n_il_paid = fields.Boolean(
        string="שולם",
        help="מסומן: ההתאמה כבר שולמה לעובד מחוץ לתלוש - הסכום נשאר בנטו הרגיל "
             "(לצורכי דיווח/מס) אבל מנוכה בחזרה מ'נטו לתשלום' כדי שלא ישולם פעמיים. "
             "לא מסומן: ההתאמה מתווספת בפועל לנטו לתשלום.",
    )

    def _l10n_il_valid_for_payslip(self, slip):
        """מסנן להתאמות שכר תקפות עבור תלוש נתון (תאריכים + מבנה שכר) - אותו
        תנאי תקפות בו משתמש hr.salary.attachment._compute_input_line_ids עצמו.
        """
        return self.filtered(
            lambda a: a.state == "open"
            and a.date_start <= slip.date_to
            and (not a.date_end or a.date_end >= slip.date_from)
            and (not a.other_input_type_id.struct_ids or slip.struct_id in a.other_input_type_id.struct_ids)
        )


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    @api.depends("employee_id", "version_id", "struct_id", "date_from", "date_to")
    def _compute_input_line_ids(self):
        super()._compute_input_line_ids()
        paid_ded_type = self.env.ref(
            "l10n_il_hr_payroll.input_il_salary_adj_paid_deduction", raise_if_not_found=False)
        if not paid_ded_type:
            return
        for slip in self:
            existing = slip.input_line_ids.filtered(lambda line: line.input_type_id == paid_ded_type)
            remove_vals = [Command.unlink(line.id) for line in existing]
            if not slip.employee_id or not slip.employee_id.salary_attachment_ids or not slip.date_to:
                if existing:
                    slip.update({"input_line_ids": remove_vals})
                continue
            valid_attachments = slip.employee_id.salary_attachment_ids.filtered(
                "l10n_il_paid")._l10n_il_valid_for_payslip(slip)
            if not valid_attachments:
                if existing:
                    slip.update({"input_line_ids": remove_vals})
                continue
            total = 0.0
            type_names = []
            for input_type_id, attachments in valid_attachments.grouped("other_input_type_id").items():
                total += attachments._get_active_amount()
                type_names.append(input_type_id.name)
            create_vals = Command.create({
                "name": "תשלום: " + ", ".join(type_names),
                "amount": total if not slip.credit_note else -total,
                "input_type_id": paid_ded_type.id,
            })
            slip.update({"input_line_ids": remove_vals + [create_vals]})
