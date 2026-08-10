from odoo import api, fields, models
from odoo.exceptions import UserError

from .l10n_il_payment_cycle_type import L10N_IL_MANUAL_CYCLE_TYPES
from .l10n_il_salary_adjustment import L10N_IL_POSITIVE_ONLY_TYPES, L10N_IL_SALARY_ADJUSTMENT_TYPES

L10N_IL_BATCH_KIND_SELECTION = [
    ("payment", "תשלום"),
    ("salary_adjustment", "התאמת שכר"),
    ("instruction", "הוראה"),
]

# צבעי הבועה לפי שלב - זהה בדיוק ל-STATUS_COLOR של hr.payslip.run
# (hr_payroll/models/hr_payslip_run.py), כדי שה-highlight_color בכרטיס הקנבן
# יתאים לאותו קונבנציה (ירוק=בוצע, סגול=שולם...).
L10N_IL_BATCH_STATE_COLOR = {
    "01_ready": 4,
    "02_close": 10,
    "03_paid": 5,
    "04_cancel": 0,
}


class L10nIlPaymentBatch(models.Model):
    """מחזור (או הוראה בודדת שנוצרה מתוך מחזור): קבוצת תשלומי עובדים
    (account.payment) ו/או התאמות שכר (hr.salary.attachment) שנוצרו יחד לכמה
    עובדים בבת אחת - עשוי לכלול כמה סוגי מחזור-תשלומים בו-זמנית (כל תשלום
    מתויג בנפרד, ראו account_payment.py.l10n_il_cycle_type)."""
    _name = "l10n.il.payment.batch"
    _description = "מחזור"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="שם", required=True, tracking=True)
    l10n_il_batch_kind = fields.Selection(
        L10N_IL_BATCH_KIND_SELECTION, string="סוג", required=True, default="payment", tracking=True)
    date = fields.Date(string="תאריך", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="חברה", default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    payment_ids = fields.One2many("account.payment", "l10n_il_batch_id", string="תשלומים")
    attachment_ids = fields.One2many(
        "hr.salary.attachment", "l10n_il_batch_id", string="התאמות שכר")
    total_amount = fields.Monetary(string="סה״כ סכום", compute="_compute_totals")
    payment_count = fields.Integer(string="מספר תשלומים", compute="_compute_totals")
    employee_count = fields.Integer(string="מספר עובדים", compute="_compute_totals")
    # שדות תצוגה-בלבד (מחושבים, לא stored) - קיימים אך ורק כדי להזין את אותו
    # widget שמשמש את hr.payslip.run (ה"בועת התקדמות" של Pay Runs) על מסך
    # המחזורים שלנו, בלי להוסיף/לשנות שום נתון אמיתי: אין למחזור "שלב" ששמור
    # במאגר - זו נגזרת חיה של מצב התשלומים/ההתאמות בפועל בלבד.
    state = fields.Selection([
        ("01_ready", "טרם שולם"),
        ("02_close", "בתהליך"),
        ("03_paid", "שולם"),
        ("04_cancel", "בוטל"),
    ], string="שלב", compute="_compute_state")
    payslips_with_issues = fields.Integer(string="תשלומים שנכשלו", compute="_compute_state")
    has_error = fields.Boolean(string="יש בעיה", compute="_compute_state")
    color = fields.Integer(string="צבע", compute="_compute_state")

    @api.depends("payment_ids.amount", "payment_ids", "attachment_ids")
    def _compute_totals(self):
        for batch in self:
            batch.total_amount = sum(batch.payment_ids.mapped("amount"))
            batch.payment_count = len(batch.payment_ids)
            employees = batch.payment_ids.partner_id.employee_ids | batch.attachment_ids.employee_ids
            batch.employee_count = len(employees)

    @api.depends("payment_ids.state", "attachment_ids.state", "l10n_il_batch_kind")
    def _compute_state(self):
        for batch in self:
            payments = batch.payment_ids
            attachments = batch.attachment_ids
            failed = payments.filtered(lambda p: p.state in ("canceled", "rejected"))
            if batch.l10n_il_batch_kind == "salary_adjustment":
                # מחזור התאמות שכר: כולם רצים (open) = לא שולם; חלק רצים
                # וחלק סגורים (close) = בתהליך; כולם סגורים = שולם.
                closed = attachments.filtered(lambda a: a.state == "close")
                if not attachments or not closed:
                    batch.state = "01_ready"
                elif len(closed) == len(attachments):
                    batch.state = "03_paid"
                else:
                    batch.state = "02_close"
            elif batch.l10n_il_batch_kind == "instruction":
                # מחזור הוראות: כל ההתאמות סגורות וכל התשלומים שולמו = שולם;
                # אף תשלום לא שולם ואף התאמה לא סגורה = לא שולם; כל מצב אחר
                # (לפחות תשלום אחד שולם, או לפחות הוראה אחת סגורה, אך לא הכל) = בתהליך.
                paid = payments.filtered(lambda p: p.state == "paid")
                closed = attachments.filtered(lambda a: a.state == "close")
                all_done = bool(payments) and bool(attachments) and len(paid) == len(payments) and len(closed) == len(attachments)
                none_done = not paid and not closed
                if all_done:
                    batch.state = "03_paid"
                elif none_done:
                    batch.state = "01_ready"
                else:
                    batch.state = "02_close"
            else:
                # מחזור תשלומים: כל התשלומים בטיוטה/בביצוע = לא שולם; רק חלק
                # שולמו = בתהליך; כולם שולמו = שולם.
                paid = payments.filtered(lambda p: p.state == "paid")
                if not payments or not paid:
                    batch.state = "01_ready"
                elif len(paid) == len(payments):
                    batch.state = "03_paid"
                else:
                    batch.state = "02_close"
            batch.payslips_with_issues = len(failed)
            batch.has_error = bool(failed)
            batch.color = L10N_IL_BATCH_STATE_COLOR[batch.state]


class L10nIlPaymentBatchWizard(models.TransientModel):
    """אשף רב-שלבי ליצירת מחזור: שלב 0 - בחירת "סוג" המחזור (תשלום/התאמת
    שכר/הוראה, ראו L10N_IL_BATCH_KIND_SELECTION); שלב 1 - פרטים משותפים לכל
    שורות המחזור (משתנה לפי הסוג); שלב 2 - בחירת העובדים וסכום/הגדרות לכל אחד.

    - "תשלום"/"הוראה": ניתן לבחור כמה סוגי-מחזור-תשלומים בו-זמנית (אוכל/מפרעה/
      הלוואה - "תלוש" לעולם לא ניתן לבחירה ידנית, ראו L10N_IL_MANUAL_CYCLE_TYPES) -
      רשימת העובדים = איחוד כל מי שיש לו שורה מסומנת "נכלל" לפחות באחד מהסוגים
      שנבחרו; לכל עובד מוצגת עמודת-סכום נפרדת לכל סוג שנבחר (0/read-only אם
      לעובד אין שורה מסומנת מאותו סוג ספציפי). כל שילוב (עובד, סוג) עם סכום
      חיובי יוצר תשלום נפרד משלו (תשלום מסוג "אוכל" נוצר ישר ב-state='canceled',
      ראו account_payment.py.l10n_il_cycle_type) - "הוראה" יוצרת גם
      hr.salary.attachment תואם לכל תשלום כזה (אותו other_input_type_id/
      l10n_il_impact_type/duration_type='one' לכולם).
    - "התאמת שכר": ללא שינוי - עובדים = כל העובדים בחברה (אין מושג סוג-מחזור
      רלוונטי), 'נכלל'=False כברירת מחדל, יוצר hr.salary.attachment בלבד.
    """
    _name = "l10n.il.payment.batch.wizard"
    _description = "יצירת מחזור"

    l10n_il_batch_kind = fields.Selection(
        L10N_IL_BATCH_KIND_SELECTION, string="סוג המחזור", default="payment", required=True)
    name = fields.Char(
        string="שם", required=True,
        default=lambda self: f"תשלום {fields.Date.context_today(self).strftime('%m/%Y')}")
    date = fields.Date(string="תאריך", required=True, default=fields.Date.context_today)
    l10n_il_include_food = fields.Boolean(string="אוכל")
    l10n_il_include_advance = fields.Boolean(string="מפרעה")
    l10n_il_include_loan = fields.Boolean(string="הלוואה")
    other_input_type_id = fields.Many2one(
        "hr.payslip.input.type", string="סוג",
        domain=[("available_in_attachments", "=", True), ("code", "in", list(L10N_IL_SALARY_ADJUSTMENT_TYPES))],
        help="משותף לכל ההתאמות שייווצרו במחזור הזה (רלוונטי ל'התאמת שכר'/'הוראה' בלבד).",
    )
    l10n_il_impact_type = fields.Selection(
        [("gross", "ברוטו"), ("net", "נטו")], string="סוג השפעה", default="gross",
        help="משותף לכל ההתאמות שייווצרו במחזור הזה (רלוונטי ל'התאמת שכר'/'הוראה' בלבד).",
    )
    duration_type = fields.Selection(
        [("one", "חד פעמי"), ("limited", "מוגבל"), ("unlimited", "ללא הגבלה")],
        string="משך זמן", default="one",
        help="רלוונטי ל'התאמת שכר' בלבד - ב'הוראה' תמיד חד-פעמי.",
    )
    journal_id = fields.Many2one("account.journal", string="יומן")
    payment_method_line_id = fields.Many2one(
        "account.payment.method.line", string="אמצעי תשלום",
        domain="[('journal_id', 'in', [journal_id, False])]",
        help="רק אמצעי תשלום שתואמים ליומן שנבחר למעלה (או משותפים לכל היומנים).",
    )
    memo = fields.Char(string="הערה")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id)
    set_all_amount = fields.Monetary(string="הגדר לכולם")
    set_all_food_amount = fields.Monetary(string="הגדר סכום אוכל לכולם")
    set_all_advance_amount = fields.Monetary(string="הגדר סכום מפרעה לכולם")
    set_all_loan_amount = fields.Monetary(string="הגדר סכום הלוואה לכולם")
    line_ids = fields.One2many(
        "l10n.il.payment.batch.wizard.line", "wizard_id", string="עובדים")
    # סוגי ה-Input המותרים כשבוחרים "סוג" בתוך מחזור מסוג 'הוראה' - קבוע (לא
    # תלוי בשום דבר), רק כדי שה-domain בתצוגה יוכל להפנות לשדה עם ערך רשימת-ID
    # (domain= לא יכול להטמיע ישירות קבוע פייתון כמו L10N_IL_POSITIVE_ONLY_TYPES).
    l10n_il_positive_only_type_ids = fields.Many2many(
        "hr.payslip.input.type", compute="_compute_l10n_il_positive_only_type_ids")

    @api.depends("l10n_il_batch_kind")
    def _compute_l10n_il_positive_only_type_ids(self):
        types = self.env["hr.payslip.input.type"].search([("code", "in", list(L10N_IL_POSITIVE_ONLY_TYPES))])
        for wizard in self:
            wizard.l10n_il_positive_only_type_ids = types

    @api.onchange("journal_id")
    def _onchange_journal_id(self):
        # אמצעי תשלום ששייך ליומן ספציפי אחר לא תואם עוד ליומן החדש שנבחר -
        # בדיוק התנאי שאודו עצמו בודק ב-account.payment._check_payment_method_line_id
        # (journal_id and journal_id != payment.journal_id -> ValidationError).
        if self.payment_method_line_id.journal_id and self.payment_method_line_id.journal_id != self.journal_id:
            self.payment_method_line_id = False

    def _reopen(self, view_xmlid, name):
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(f"l10n_il_hr_payroll_account.{view_xmlid}").id,
            "target": "new",
        }

    def action_choose_kind(self):
        """שלב 0 -> שלב 1: פותח את שלב 1 (אותה תצוגה אחת, מותנית לפי הסוג).
        ממלא את השם אוטומטית לפי הסוג שנבחר (כמו שהיום כבר ממולא תאריך בשם) -
        עדיין שדה רגיל וניתן לעריכה ידנית בשלב 1 אם רוצים שם אחר."""
        self.ensure_one()
        kind_label = dict(L10N_IL_BATCH_KIND_SELECTION)[self.l10n_il_batch_kind]
        self.name = f"{kind_label} {fields.Date.context_today(self).strftime('%m/%Y')}"
        return self._reopen("l10n_il_payment_batch_wizard_view_form_step1", "מחזור חדש")

    def action_back_to_kind(self):
        """חזרה משלב 1 לבחירת הסוג (שלב 0)."""
        return self._reopen("l10n_il_payment_batch_wizard_view_form_step0", "מחזור חדש")

    def _reopen_step2(self):
        return self._reopen("l10n_il_payment_batch_wizard_view_form_step2", "מחזור - עובדים וסכומים")

    def action_back(self):
        """חזרה משלב 2 לשלב 1."""
        return self._reopen("l10n_il_payment_batch_wizard_view_form_step1", "מחזור חדש")

    def _l10n_il_selected_cycle_types(self):
        self.ensure_one()
        return [
            t for t, flag in [
                ("food", self.l10n_il_include_food),
                ("advance", self.l10n_il_include_advance),
                ("loan", self.l10n_il_include_loan),
            ] if flag
        ]

    def action_next(self):
        """שלב 2: טעינת רשימת העובדים המתאימה. 'תשלום'/'הוראה' - איחוד כל
        העובדים עם שורה מסומנת "נכלל" בלפחות אחד מסוגי-המחזור שנבחרו (checkbox
        לכל סוג) - עמודת-סכום נפרדת לכל סוג שנבחר, 0/לא-ניתן-לעריכה אם לעובד
        אין שורה מאותו סוג ספציפי. 'התאמת שכר' - כל העובדים בחברה (אין מושג
        "סוג" רלוונטי כאן), עם 'נכלל'=False כברירת מחדל כדי לא ליצור התאמה
        לכולם בטעות."""
        self.ensure_one()
        if self.l10n_il_batch_kind == "salary_adjustment":
            employees = self.env["hr.employee"].search([("company_id", "in", self.env.companies.ids)])
            if not employees:
                raise UserError("אין עובדים בחברה.")
            lines = [(0, 0, {
                "employee_id": emp.id,
                "amount": 0.0,
                "included": False,
            }) for emp in employees]
        else:
            selected_types = self._l10n_il_selected_cycle_types()
            if not selected_types:
                raise UserError("יש לבחור לפחות סוג מחזור אחד.")
            cycle_lines = self.env["l10n.il.employee.payment.cycle.line"].search([
                ("cycle_type", "in", selected_types), ("included", "=", True),
                ("employee_id.company_id", "in", self.env.companies.ids),
            ])
            if not cycle_lines:
                raise UserError("אין עובדים עם סכום מוגדר לאף אחד מהסוגים שנבחרו.")
            amounts_by_employee = {}
            for line in cycle_lines:
                amounts_by_employee.setdefault(line.employee_id, {})[line.cycle_type] = line.amount
            lines = [(0, 0, {
                "employee_id": emp.id,
                # חשבון בנק ברירת מחדל: אם לעובד יש אחד - הוא נמשך ישר; אם יש
                # יותר מאחד - נמשך הראשון מביניהם (primary_bank_account_id הילידי,
                # הקובע לפי הרצף הנמוך ביותר ב-salary_distribution).
                "partner_bank_id": emp.primary_bank_account_id.id,
                "included": True,
                "food_amount": amounts.get("food", 0.0),
                "has_food": "food" in amounts,
                "advance_amount": amounts.get("advance", 0.0),
                "has_advance": "advance" in amounts,
                "loan_amount": amounts.get("loan", 0.0),
                "has_loan": "loan" in amounts,
            }) for emp, amounts in amounts_by_employee.items()]
        self.line_ids = [(5, 0, 0)] + lines
        return self._reopen_step2()

    def action_set_all_amount(self):
        """מגדיר את הסכום שהוזן ב'הגדר לכולם' על שדה 'amount' של כל השורות
        המסומנות - רלוונטי ל'התאמת שכר' בלבד (סכום אחד לעובד, אין מושג סוג)."""
        self.ensure_one()
        for line in self.line_ids.filtered("included"):
            line.amount = self.set_all_amount
        return self._reopen_step2()

    def _action_set_all_for_type(self, cycle_type, amount):
        """מגדיר סכום אחיד לכולם, רק על עמודת-הסכום של סוג-מחזור ספציפי
        (אוכל/מפרעה/הלוואה) - רק לשורות שהעובד בפועל זכאי לאותו סוג (has_X)."""
        self.ensure_one()
        amount_field, has_field = {
            "food": ("food_amount", "has_food"),
            "advance": ("advance_amount", "has_advance"),
            "loan": ("loan_amount", "has_loan"),
        }[cycle_type]
        for line in self.line_ids.filtered(lambda l: l.included and getattr(l, has_field)):
            line.write({amount_field: amount})
        return self._reopen_step2()

    def action_set_all_food(self):
        return self._action_set_all_for_type("food", self.set_all_food_amount)

    def action_set_all_advance(self):
        return self._action_set_all_for_type("advance", self.set_all_advance_amount)

    def action_set_all_loan(self):
        return self._action_set_all_for_type("loan", self.set_all_loan_amount)

    def action_create_batch(self):
        self.ensure_one()
        included = self.line_ids.filtered("included")
        if not included:
            raise UserError("לא נבחר אף עובד לכלול במחזור.")

        if self.l10n_il_batch_kind == "salary_adjustment":
            if any(not line.amount for line in included):
                raise UserError("יש להזין סכום לכל העובדים שנבחרו.")
            if not self.other_input_type_id or not self.l10n_il_impact_type:
                raise UserError("יש לבחור סוג וסוג השפעה.")
            batch = self.env["l10n.il.payment.batch"].create({
                "name": self.name, "date": self.date, "l10n_il_batch_kind": self.l10n_il_batch_kind,
            })
            for line in included:
                vals = {
                    "employee_ids": [(6, 0, [line.employee_id.id])],
                    "other_input_type_id": self.other_input_type_id.id,
                    "l10n_il_impact_type": self.l10n_il_impact_type,
                    "duration_type": self.duration_type,
                    "monthly_amount": line.amount,
                    "date_start": self.date,
                    "description": self.memo,
                    "l10n_il_batch_id": batch.id,
                }
                if self.duration_type == "limited":
                    vals["total_amount"] = line.amount
                self.env["hr.salary.attachment"].create(vals)
            return {
                "type": "ir.actions.act_window",
                "name": "מחזור",
                "res_model": "l10n.il.payment.batch",
                "res_id": batch.id,
                "view_mode": "form",
            }

        selected_types = self._l10n_il_selected_cycle_types()
        type_amount_fields = {"food": "food_amount", "advance": "advance_amount", "loan": "loan_amount"}
        if any(not line.partner_bank_id for line in included):
            raise UserError("יש לבחור חשבון בנק לכל העובדים שנבחרו.")
        if not any(getattr(line, type_amount_fields[t]) for line in included for t in selected_types):
            raise UserError("יש להזין סכום לפחות עבור עובד אחד, בסוג אחד לפחות.")
        if self.l10n_il_batch_kind == "instruction" and (not self.other_input_type_id or not self.l10n_il_impact_type):
            raise UserError("יש לבחור סוג וסוג השפעה.")

        batch = self.env["l10n.il.payment.batch"].create({
            "name": self.name,
            "date": self.date,
            "l10n_il_batch_kind": self.l10n_il_batch_kind,
        })
        payment_vals = {}
        if self.journal_id:
            payment_vals["journal_id"] = self.journal_id.id
        if self.payment_method_line_id:
            payment_vals["payment_method_line_id"] = self.payment_method_line_id.id

        for line in included:
            if not line.employee_id.work_contact_id:
                raise UserError(f"לעובד {line.employee_id.name} אין איש-קשר לקשר אליו תשלום.")
            for cycle_type in selected_types:
                amount = getattr(line, type_amount_fields[cycle_type])
                if not amount:
                    continue
                # "אוכל" הוא הסוג המיוחד היחיד: התשלום נוצר ישר בסטטוס 'canceled' -
                # לא ישפיע על כלום, שום תלוש לא ימשוך אותו (ראו _l10n_il_collect_payments,
                # שכבר מוציאה 'canceled' מהחישוב). כל שאר הסוגים נוצרים 'in_process' כרגיל.
                payment_state = "canceled" if cycle_type == "food" else "in_process"
                self.env["account.payment"].create({
                    **payment_vals,
                    "partner_id": line.employee_id.work_contact_id.id,
                    "partner_type": "supplier",
                    "partner_bank_id": line.partner_bank_id.id,
                    "payment_type": "outbound",
                    "amount": amount,
                    "date": self.date,
                    "memo": self.memo,
                    "l10n_il_batch_id": batch.id,
                    "l10n_il_cycle_type": cycle_type,
                    "state": payment_state,
                })
                if self.l10n_il_batch_kind == "instruction":
                    self.env["hr.salary.attachment"].create({
                        "employee_ids": [(6, 0, [line.employee_id.id])],
                        "other_input_type_id": self.other_input_type_id.id,
                        "l10n_il_impact_type": self.l10n_il_impact_type,
                        "monthly_amount": amount,
                        "duration_type": "one",
                        "date_start": self.date,
                        "description": self.memo,
                        "l10n_il_batch_id": batch.id,
                    })
        return {
            "type": "ir.actions.act_window",
            "name": "מחזור",
            "res_model": "l10n.il.payment.batch",
            "res_id": batch.id,
            "view_mode": "form",
        }


class L10nIlPaymentBatchWizardLine(models.TransientModel):
    _name = "l10n.il.payment.batch.wizard.line"
    _description = "שורת עובד במחזור"

    wizard_id = fields.Many2one("l10n.il.payment.batch.wizard", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", string="עובד", required=True)
    employee_bank_account_ids = fields.Many2many(
        related="employee_id.bank_account_ids", string="חשבונות בנק של העובד")
    partner_bank_id = fields.Many2one(
        "res.partner.bank", string="חשבון בנק",
        domain="[('id', 'in', employee_bank_account_ids)]",
        help="רק חשבונות הבנק של העובד עצמו. חובה לכל עובד שנכלל במחזורי תשלום/הוראה.",
    )
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    included = fields.Boolean(string="נכלל", default=True)
    # רלוונטי ל'התאמת שכר' בלבד (אין מושג "סוג מחזור" שם - סכום אחד לעובד).
    amount = fields.Monetary(string="סכום")
    # רלוונטי ל'תשלום'/'הוראה' - עמודת-סכום נפרדת לכל סוג-מחזור, 0/read-only
    # (has_X=False) אם לעובד אין שורה מסומנת מאותו סוג ספציפי (ראו action_next).
    food_amount = fields.Monetary(string="אוכל")
    has_food = fields.Boolean()
    advance_amount = fields.Monetary(string="מפרעה")
    has_advance = fields.Boolean()
    loan_amount = fields.Monetary(string="הלוואה")
    has_loan = fields.Boolean()
