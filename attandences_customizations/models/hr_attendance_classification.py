from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrAttendanceClassificationRuleset(models.Model):
    """קבוצת כללים לסיווג רישומי נוכחות למשמרת בוקר/ערב, לפי שעת הכניסה.

    בנוי באותה צורה כמו Overtime Ruleset הקיים: כותרת + שורות כלל מסודרות
    ברצף, מיוחסת לעובד דרך גרסת ההעסקה שלו (hr.version).
    """
    _name = "hr.attendance.classification.ruleset"
    _description = "חוקי משמרות"

    name = fields.Char(string="שם", required=True)
    description = fields.Html(string="תיאור")
    company_id = fields.Many2one("res.company", string="חברה", default=lambda self: self.env.company)
    country_id = fields.Many2one("res.country", string="מדינה", default=lambda self: self.env.company.country_id)
    rule_ids = fields.One2many("hr.attendance.classification.rule", "ruleset_id", string="כללי סיווג")
    rules_count = fields.Integer(string="מספר כללים", compute="_compute_rules_count")
    active = fields.Boolean(default=True)

    @api.depends("rule_ids")
    def _compute_rules_count(self):
        for ruleset in self:
            ruleset.rules_count = len(ruleset.rule_ids)

    def _match_attendance_type(self, hour):
        """מחזיר את סוג המשמרת לפי שעת הכניסה (float, שעה מקומית), או False אם אין התאמה."""
        self.ensure_one()
        for rule in self.rule_ids.sorted("sequence"):
            if rule.time_from <= hour < rule.time_to:
                return rule.attendance_type
        return False


class HrAttendanceClassificationRule(models.Model):
    _name = "hr.attendance.classification.rule"
    _description = "כלל סיווג משמרת"
    _order = "sequence, id"

    ruleset_id = fields.Many2one(
        "hr.attendance.classification.ruleset", string="קבוצת כללים", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="ruleset_id.company_id", store=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="שם הכלל", required=True)
    time_from = fields.Float(string="משעה", default=0.0)
    time_to = fields.Float(string="עד שעה", default=24.0)
    attendance_type = fields.Selection(
        selection=[("morning", "משמרת בוקר"), ("afternoon", "משמרת ערב")],
        string="סוג המשמרת", required=True,
        help="סוג המשמרת שיוקצה לרישום נוכחות ששעת הכניסה שלו נמצאת בטווח שהוגדר.",
    )
    information_display = fields.Char(string="תיאור", compute="_compute_information_display")

    _time_from_is_hour = models.Constraint(
        "CHECK(0 <= time_from AND time_from < 24)", "משעה חייב להיות שעה ביום (0 עד 24)")
    _time_to_is_hour = models.Constraint(
        "CHECK(0 < time_to AND time_to <= 24)", "עד שעה חייב להיות שעה ביום (0 עד 24)")

    @api.constrains("time_from", "time_to")
    def _check_range(self):
        for rule in self:
            if rule.time_from >= rule.time_to:
                raise ValidationError("משעה חייב להיות קטן מעד שעה בכלל '%s'." % rule.name)

    def _format_hour(self, hour):
        h = int(hour)
        m = round((hour - h) * 60)
        return f"{h:02d}:{m:02d}"

    @api.depends("time_from", "time_to", "attendance_type")
    def _compute_information_display(self):
        labels = dict(self._fields["attendance_type"].selection)
        for rule in self:
            rule.information_display = (
                f"{rule._format_hour(rule.time_from)} - {rule._format_hour(rule.time_to)} "
                f"← {labels.get(rule.attendance_type, '')}"
            )
