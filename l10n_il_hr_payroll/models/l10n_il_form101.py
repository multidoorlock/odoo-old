from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError


class L10nIlEmployeeChild(models.Model):
    _name = "l10n.il.employee.child"
    _description = "ילדי עובד"
    _order = "birthdate desc"

    employee_id = fields.Many2one("hr.employee", string="עובד", required=True, ondelete="cascade", index=True)
    name = fields.Char(string="שם הילד/ה", required=True)
    identification_id = fields.Char(string="מספר זהות")
    birthdate = fields.Date(string="תאריך לידה", required=True)
    in_custody = fields.Boolean(string="בחזקתי", default=True)
    receives_child_allowance = fields.Boolean(string="מקבל/ת קצבת ילדים", default=True)


class L10nIlForm101(models.Model):
    _name = "l10n.il.form101"
    _description = "טופס 101 - כרטיס עובד"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "tax_year desc, employee_id"

    _unique_employee_year = models.Constraint(
        "unique (employee_id, tax_year)",
        "כבר קיים טופס 101 לעובד זה עבור שנת המס הזו.",
    )

    # מיפוי שדה בטופס -> שדה מקביל בגרסת ההעסקה (hr.version) / בכרטיס העובד (hr.employee).
    # משמש הן למילוי אוטומטי בבחירת עובד (_onchange_employee_id) והן לזיהוי שינויים
    # בהפעלת הטופס, כדי ליצור גרסת העסקה חדשה במקום לדרוס את הקיימת (_do_apply).
    _VERSION_FIELD_MAP = {
        "identification_id": "identification_id",
        "sex": "sex",
        "marital": "marital",
        "country_id": "country_id",
        "l10n_il_aliyah_date": "l10n_il_aliyah_date",
        "private_street": "private_street",
        "private_city": "private_city",
        "private_zip": "private_zip",
        "kupat_holim": "l10n_il_kupat_holim",
        "is_main_employer": "l10n_il_main_employer",
        "spouse_complete_name": "spouse_complete_name",
        "spouse_birthdate": "spouse_birthdate",
        "spouse_id_number": "l10n_il_spouse_id",
        "settlement_code": "l10n_il_settlement_code",
    }
    _EMPLOYEE_FIELD_MAP = {
        "birthday": "birthday",
        "private_phone": "private_phone",
        "private_email": "private_email",
    }

    employee_id = fields.Many2one(
        "hr.employee", string="עובד", required=True, index=True, tracking=True,
        groups="hr_payroll.group_hr_payroll_user",
    )
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    tax_year = fields.Integer(
        string="שנת מס", required=True, tracking=True,
        default=lambda self: fields.Date.today().year,
    )

    _tax_year_four_digits = models.Constraint(
        "CHECK(tax_year BETWEEN 1000 AND 9999)",
        "שנת מס חייבת להיות מספר בן ארבע ספרות.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "טיוטה"),
            ("sent", "נשלח לעובד"),
            ("signed", "נחתם"),
            ("applied", "פעיל"),
            ("expired", "פג תוקף"),
        ],
        string="סטטוס", default="draft", required=True, tracking=True,
    )
    date_signed = fields.Date(string="תאריך חתימה", tracking=True)
    valid_until = fields.Date(
        string="בתוקף עד", compute="_compute_valid_until", store=True,
        tracking=True,
        help="תוקף שנתי קבוע: סוף שנת המס (31.12), כולל שנת המס עצמה. טופס פעיל שתאריך זה "
             "חלף בו יסומן אוטומטית כפג תוקף - אין אפשרות לקבוע תאריך תפוגה ידני.",
    )

    # ==== חלק א: פרטי המעביד (מקור: החברה) ====
    employer_deduction_file = fields.Char(
        related="company_id.l10n_il_deduction_file_no", string="תיק ניכויים", readonly=True)

    # ==== חלק ב: פרטי העובד ====
    # השדות הבאים אינם related: הם מתמלאים אוטומטית מהעובד בבחירתו (ראו _onchange_employee_id),
    # אך אינם כותבים חזרה באופן מיידי. שינוי מהם נכתב לעובד רק בהפעלת הטופס (_do_apply),
    # וכל שדה שיוצא שונה מהערך הנוכחי אצל העובד יוצר גרסת העסקה (hr.version) חדשה במקום
    # לדרוס את הגרסה הקיימת — כך נשמרת היסטוריה ולא נוצרות תופעות לוואי מהזנה בטופס.
    identification_id = fields.Char(string="מספר זהות")
    birthday = fields.Date(string="תאריך לידה")
    sex = fields.Selection(
        selection=[("male", "זכר"), ("female", "נקבה"), ("other", "אחר")], string="מין")
    marital = fields.Selection(selection="_get_marital_status_selection", string="מצב משפחתי")
    country_id = fields.Many2one("res.country", string="אזרחות")
    l10n_il_aliyah_date = fields.Date(
        string="תאריך עלייה", help="רלוונטי כאשר אזרחות העובד אינה ישראל.")
    private_street = fields.Char(string="רחוב")
    private_city = fields.Char(string="יישוב")
    private_zip = fields.Char(string="מיקוד")
    private_phone = fields.Char(string="טלפון")
    private_email = fields.Char(string="דוא״ל")
    kupat_holim = fields.Selection(
        selection=[
            ("clalit", "כללית"),
            ("maccabi", "מכבי"),
            ("meuhedet", "מאוחדת"),
            ("leumit", "לאומית"),
        ],
        string="קופת חולים",
    )

    def _get_marital_status_selection(self):
        return self.env["hr.version"]._get_marital_status_selection()

    # ==== חלק ג: פרטי ילדים (מקור: כרטיס העובד - טבלה משותפת, לא גרסתית) ====
    child_ids = fields.One2many(related="employee_id.l10n_il_child_ids", readonly=False, string="ילדים")

    # ==== חלק ד: פרטים על ההכנסה ====
    is_main_employer = fields.Boolean(string="הכנסה עיקרית")
    has_other_income = fields.Boolean(string="יש לי הכנסות נוספות ממשכורת", tracking=True)

    # ==== חלק ה: פרטי בן/בת הזוג ====
    spouse_complete_name = fields.Char(string="שם בן/בת הזוג")
    spouse_birthdate = fields.Date(string="תאריך לידה של בן/בת הזוג")
    spouse_id_number = fields.Char(string="מספר זהות של בן/בת הזוג")
    spouse_has_income = fields.Boolean(string="לבן/בת הזוג יש הכנסה", default=True)

    # ==== חלק ז: בקשת פטורים וזיכויים (הצהרות שנתיות - נשמרות על הטופס) ====
    is_resident = fields.Boolean(string="תושב/ת ישראל", default=True, tracking=True)
    is_disabled_blind = fields.Boolean(string="נכה/עיוור לפי סעיף 9(5)", tracking=True)
    is_settlement_resident = fields.Boolean(string="תושב/ת יישוב מזכה", tracking=True)
    settlement_code = fields.Char(string="קוד יישוב")
    settlement_date_from = fields.Date(string="תושב/ת היישוב מתאריך")
    is_new_immigrant = fields.Boolean(string="עולה חדש/ה", tracking=True)
    spouse_no_income = fields.Boolean(string="בן/בת זוג ללא הכנסות")
    is_single_parent = fields.Boolean(string="הורה יחיד")
    pays_alimony = fields.Boolean(string="משלם/ת מזונות לבן/בת זוג לשעבר")
    is_discharged_soldier = fields.Boolean(string="חייל/ת משוחרר/ת")
    service_end_date = fields.Date(string="תאריך שחרור")
    completed_degree = fields.Boolean(string="סיום תואר אקדמי/תעודת מקצוע")
    has_disabled_child = fields.Boolean(string="ילד נטול יכולת")

    # ==== חלק ח: תיאום מס ====
    request_tax_coordination = fields.Boolean(string="מבקש/ת תיאום מס", tracking=True)
    coordination_reason = fields.Selection(
        selection=[
            ("multiple_employers", "עובד/ת אצל יותר ממעסיק אחד"),
            ("job_change", "החלפת מקום עבודה במהלך השנה"),
            ("other", "אחר"),
        ],
        string="סיבת הבקשה",
    )

    # ==== נקודות זיכוי ====
    credit_points_base = fields.Float(
        string="נקודות בסיס (תושב)", compute="_compute_credit_points", store=True, digits=(16, 2))
    credit_points_woman = fields.Float(
        string="נקודות אישה", compute="_compute_credit_points", store=True, digits=(16, 2))
    credit_points_extra = fields.Float(
        string="נקודות נוספות", digits=(16, 2), tracking=True,
        help="נקודות זיכוי נוספות שנקבעו ידנית: ילדים, עולה חדש, חייל משוחרר, תואר, מזונות וכו' — לפי חוברת הניכויים לשנת המס.",
    )
    credit_points_total = fields.Float(
        string="סה״כ נקודות זיכוי", compute="_compute_credit_points", store=True, digits=(16, 2), tracking=True)
    current_credit_points = fields.Float(
        related="employee_id.l10n_il_credit_points", string="נקודות זיכוי פעילות בשכר")

    @api.depends("is_resident", "sex", "credit_points_extra")
    def _compute_credit_points(self):
        for form in self:
            form.credit_points_base = 2.25 if form.is_resident else 0.0
            form.credit_points_woman = 0.5 if form.sex == "female" else 0.0
            form.credit_points_total = (
                form.credit_points_base + form.credit_points_woman + form.credit_points_extra
            )

    @api.depends("tax_year")
    def _compute_valid_until(self):
        # תוקף שנתי קבוע: סוף שנת המס עצמה (31.12) - לא ניתן לעריכה ידנית, מתעדכן אוטומטית
        # אם שנת המס משתנה.
        for form in self:
            if form.tax_year:
                form.valid_until = date(form.tax_year, 12, 31)

    @api.depends("employee_id", "tax_year")
    def _compute_display_name(self):
        for form in self:
            form.display_name = f"טופס 101 - {form.employee_id.name or ''} - {form.tax_year}"

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        """מילוי אוטומטי של כל השדות המשותפים לטופס ולעובד, מהערך הנוכחי אצל העובד."""
        for form in self:
            if not form.employee_id:
                continue
            version = form.employee_id.version_id
            for form_field, version_field in form._VERSION_FIELD_MAP.items():
                form[form_field] = version[version_field]
            for form_field, employee_field in form._EMPLOYEE_FIELD_MAP.items():
                form[form_field] = form.employee_id[employee_field]
            form.is_resident = version.l10n_il_tax_residency != "non_resident"

    def action_send(self):
        self.write({"state": "sent"})

    def action_mark_signed(self):
        for form in self:
            if not form.date_signed:
                form.date_signed = fields.Date.today()
        self.write({"state": "signed"})

    def action_apply(self):
        """הפעלת הטופס בשכר. אם קיים טופס פעיל אחר לאותו עובד — נפתח אשף שמציג
        את הטופס הפעיל ושואל אם להחליף אותו (לא ייתכנו שני טפסים פעילים במקביל)."""
        self.ensure_one()
        if self.state != "signed":
            raise UserError("ניתן להפעיל בשכר רק טופס חתום.")
        others = self.search([
            ("employee_id", "=", self.employee_id.id),
            ("state", "=", "applied"),
            ("id", "!=", self.id),
        ])
        if others:
            return {
                "type": "ir.actions.act_window",
                "name": "החלפת טופס 101 פעיל",
                "res_model": "l10n.il.form101.replace.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {
                    "default_form_id": self.id,
                    "default_old_form_ids": [(6, 0, others.ids)],
                },
            }
        self._do_apply()

    @staticmethod
    def _to_write_value(value):
        return value.id if isinstance(value, models.BaseModel) else value

    def _do_apply(self):
        """החלת נתוני הטופס על נתוני השכר של העובד.

        כל שדה שערכו בטופס שונה מהערך הנוכחי אצל העובד/הגרסה שלו אינו נכתב במקום
        (דריסה של ההיסטוריה), אלא יוצר גרסת העסקה (hr.version) חדשה, מתוארכת מהיום,
        עם השינוי/ים — כך שההיסטוריה של העובד נשמרת.
        """
        for form in self:
            employee = form.employee_id
            version = employee.version_id

            version_diffs = {}
            for form_field, version_field in form._VERSION_FIELD_MAP.items():
                new_value = form._to_write_value(form[form_field])
                current_value = form._to_write_value(version[version_field])
                if new_value != current_value:
                    version_diffs[version_field] = new_value
            new_residency = "resident" if form.is_resident else "non_resident"
            if version.l10n_il_tax_residency != new_residency:
                version_diffs["l10n_il_tax_residency"] = new_residency
            if version.l10n_il_credit_points != form.credit_points_total:
                version_diffs["l10n_il_credit_points"] = form.credit_points_total

            employee_diffs = {}
            for form_field, employee_field in form._EMPLOYEE_FIELD_MAP.items():
                new_value = form._to_write_value(form[form_field])
                current_value = form._to_write_value(employee[employee_field])
                if new_value != current_value:
                    employee_diffs[employee_field] = new_value

            if version_diffs:
                new_version = employee.create_version({"date_version": fields.Date.today()})
                new_version.write(version_diffs)
            if employee_diffs:
                employee.write(employee_diffs)

            form.state = "applied"
            form.message_post(body=(
                f"הטופס הופעל בשכר: {form.credit_points_total:.2f} נקודות זיכוי, "
                f"בתוקף עד {form.valid_until.strftime('%d.%m.%Y') if form.valid_until else ''}."
                + (" נוצרה גרסת העסקה חדשה עקב שינוי בפרטי העובד." if version_diffs else "")
            ))

    def action_reset_to_draft(self):
        self.write({"state": "draft"})

    @api.model
    def _cron_expire_forms(self):
        """קרון יומי: טופס פעיל שתוקפו חלף מסומן פג תוקף, וסטטוס העובד מתעדכן אוטומטית."""
        expired = self.search([
            ("state", "=", "applied"),
            ("valid_until", "<", fields.Date.today()),
        ])
        for form in expired:
            form.state = "expired"
            form.message_post(body="תוקף הטופס פג — הסטטוס עודכן אוטומטית.")


class L10nIlForm101ReplaceWizard(models.TransientModel):
    _name = "l10n.il.form101.replace.wizard"
    _description = "החלפת טופס 101 פעיל"

    form_id = fields.Many2one("l10n.il.form101", string="הטופס החדש להפעלה", required=True)
    old_form_ids = fields.Many2many(
        "l10n.il.form101", string="טפסים פעילים שיוחלפו", readonly=True)

    def action_confirm(self):
        self.ensure_one()
        for old in self.old_form_ids:
            old.state = "expired"
            old.message_post(body=f"הטופס הוחלף על ידי {self.form_id.display_name} וסומן כפג תוקף.")
        self.form_id._do_apply()
