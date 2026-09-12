from copy import deepcopy

from odoo import api, models


class HrEmployeeView(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _il_order_employee_smartbuttons(self, arch):
        """Order installed buttons without depending on optional HR addons.

        Keep the original nodes: action identifiers, access groups, context,
        and the two mutually exclusive native payslip/attendance variants.
        Native view postprocessing still applies access rights afterwards.
        """
        priorities = {
            'action_il_open_work_contact': 10,
            'action_open_versions': 20,
            'action_open_attendance_device_cards': 30,
            'action_open_payslips': 40,
            'action_il_open_payments': 50,
            'action_il_open_payroll_ledger': 60,
            'action_open_documents': 70,
            'action_open_work_entries': 90,
            'action_open_last_month_attendances': 100,
        }
        new_payslip = self.env.ref('hr_payroll.action_hr_payslip_new')
        priorities[str(new_payslip.id)] = 40

        def priority(button):
            if button.xpath("./field[@name='equipment_count']"):
                return 80
            # Other installed apps keep their relative order, ahead of the
            # requested final Work Entries / Monthly Hours buttons.
            return priorities.get(button.get('name'), 85)

        for box in arch.xpath("//div[@name='button_box']"):
            buttons = list(box.xpath('./button'))
            for button in buttons:
                for count in ('document_count', 'equipment_count'):
                    if button.xpath("./field[@name='%s']" % count):
                        condition = '%s == 0' % count
                        previous = button.get('invisible')
                        if previous and condition not in previous:
                            condition = '(%s) or (%s)' % (previous, condition)
                        elif previous:
                            condition = previous
                        button.set('invisible', condition)
            # Replace only button slots, retaining invisible helper fields and
            # any other native children in their original positions.
            ordered = iter(sorted(buttons, key=priority))
            box[:] = [next(ordered) if child.tag == 'button' else child
                      for child in box]
        return arch

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form':
            arch = self._il_order_employee_smartbuttons(deepcopy(arch))
        return arch, view
