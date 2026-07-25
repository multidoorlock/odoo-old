from odoo import fields, models


class HrVersion(models.Model):
    _inherit = "hr.version"

    # --- העסקה ---
    l10n_il_employee_category = fields.Selection(
        selection=[
            ("israeli", "עובד ישראלי"),
            ("foreign", "עובד זר"),
            ("palestinian", "עובד פלסטיני"),
        ],
        string="קטגוריית עובד",
        default="israeli",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="הקטגוריה הסטטוטורית של העובד. קובעת אילו כללי שכר, דיווחים וניכויים חלים עליו.",
    )
    l10n_il_has_advance = fields.Boolean(
        string="קיים מפרעה",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="כאשר מסומן, העובד ייכלל אוטומטית במחזורי מפרעות עם סכום ברירת המחדל שלו.",
    )
    l10n_il_advance_amount = fields.Float(
        string="סכום מפרעה",
        digits=(16, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="סכום ברירת המחדל למפרעה החודשית של העובד. ניתן לשינוי פר מחזור.",
    )

    # --- מס הכנסה ---
    l10n_il_tax_residency = fields.Selection(
        selection=[
            ("resident", "תושב ישראל"),
            ("non_resident", "תושב חוץ"),
        ],
        string="תושבות לצורכי מס",
        default="resident",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_credit_points = fields.Float(
        string="נקודות זיכוי",
        default=2.25,
        digits=(16, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="מספר נקודות הזיכוי של העובד לפי טופס 101. שווי הנקודה נקבע בפרמטר שנתי.",
    )
    l10n_il_main_employer = fields.Boolean(
        string="מעסיק עיקרי",
        default=True,
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="כאשר לא מסומן (מעסיק משני), ללא אישור תיאום מס ינוכה מס מרבי.",
    )
    l10n_il_tax_coordination = fields.Boolean(
        string="תיאום מס",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="מסומן כאשר קיים אישור תיאום מס בתוקף מרשות המסים.",
    )
    l10n_il_tax_coordination_rate = fields.Float(
        string="שיעור מס לפי תיאום (%)",
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור המס הקבוע מהאישור. כאשר מוגדר, המס מחושב לפי שיעור זה במקום מדרגות המס.",
    )
    l10n_il_tax_coordination_expiry = fields.Date(
        string="תוקף אישור תיאום מס",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_settlement_code = fields.Char(
        string="קוד יישוב מזכה",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="קוד היישוב לצורך הטבת מס ביישוב מוטב, כאשר העובד זכאי.",
    )

    # --- פנסיה ופיצויים ---
    l10n_il_pension_fund_id = fields.Many2one(
        "res.partner",
        string="קרן פנסיה",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="הגוף המוסדי המנהל את ההסדר הפנסיוני של העובד.",
    )
    l10n_il_pension_member_no = fields.Char(
        string="מספר עמית בקרן",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_pension_employee_rate = fields.Float(
        string="פנסיה - עובד (%)",
        default=6.0,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור ניכוי העובד לתגמולים. המינימום לפי צו ההרחבה: 6%.",
    )
    l10n_il_pension_employer_rate = fields.Float(
        string="פנסיה - מעסיק (%)",
        default=6.5,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור הפרשת המעסיק לתגמולים. המינימום לפי צו ההרחבה: 6.5%.",
    )
    l10n_il_severance_rate = fields.Float(
        string="פיצויים - מעסיק (%)",
        default=6.0,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור הפרשת המעסיק לפיצויים. המינימום לפי צו ההרחבה: 6%; הפרשה מלאה לפי סעיף 14: 8.33%.",
    )
    l10n_il_section14 = fields.Boolean(
        string="סעיף 14",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="מסומן כאשר חל על העובד האישור הכללי לפי סעיף 14 לחוק פיצויי פיטורים.",
    )

    # --- פרטים אישיים לטופס 101 ---
    l10n_il_aliyah_date = fields.Date(
        string="תאריך עלייה",
        groups="hr.group_hr_user",
        tracking=True,
    )
    l10n_il_spouse_id = fields.Char(
        string="מספר זהות של בן/בת הזוג",
        groups="hr.group_hr_user",
        tracking=True,
    )
    l10n_il_kupat_holim = fields.Selection(
        selection=[
            ("clalit", "כללית"),
            ("maccabi", "מכבי"),
            ("meuhedet", "מאוחדת"),
            ("leumit", "לאומית"),
        ],
        string="קופת חולים",
        groups="hr.group_hr_user",
        tracking=True,
    )

    # --- קרן השתלמות ---
    l10n_il_hishtalmut = fields.Boolean(
        string="קרן השתלמות",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_hishtalmut_fund_id = fields.Many2one(
        "res.partner",
        string="קרן השתלמות - גוף מנהל",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_hishtalmut_employee_rate = fields.Float(
        string="קרן השתלמות - עובד (%)",
        default=2.5,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_hishtalmut_employer_rate = fields.Float(
        string="קרן השתלמות - מעסיק (%)",
        default=7.5,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
