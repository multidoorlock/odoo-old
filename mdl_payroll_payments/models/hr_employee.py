# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .hr_employee_payment_cycle_setting import IL_CYCLE_TYPES


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    il_payment_cycle_setting_ids = fields.One2many(
        'hr.employee.payment.cycle.setting', 'employee_id',
        string='מחזורי תשלומים')

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        self.env['hr.employee.payment.cycle.setting'].sudo().create([
            {'employee_id': employee.id, 'cycle_type': cycle_type}
            for employee in employees
            for cycle_type, _label in IL_CYCLE_TYPES
        ])
        return employees
