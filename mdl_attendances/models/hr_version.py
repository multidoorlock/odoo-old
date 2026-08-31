from odoo import fields, models


class HrVersion(models.Model):
    _inherit = "hr.version"

    segment_ruleset_id = fields.Many2one(
        "hr.attendance.segment.ruleset",
        string="Attendance Segmentation Ruleset",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        groups="hr.group_hr_manager",
        tracking=True,
    )
