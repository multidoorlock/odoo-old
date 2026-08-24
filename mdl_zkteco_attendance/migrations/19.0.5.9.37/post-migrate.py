from collections import Counter

from odoo import api, SUPERUSER_ID
from odoo.tools.sql import column_exists


SUPPORTED_LANGUAGES = {"he_IL", "ar_001", "en_US"}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Device = env["mdl.attendance.device"].with_context(active_test=False)

    # Preserve the most common language previously selected on this clock's
    # employee cards when moving the setting from card level to device level.
    languages_by_device = {}
    if column_exists(cr, "mdl_attendance_device_employee", "device_name_lang_id"):
        cr.execute(
            """
            SELECT card.device_id, lang.code
              FROM mdl_attendance_device_employee AS card
              JOIN res_lang AS lang ON lang.id = card.device_name_lang_id
             WHERE card.device_id IS NOT NULL
            """
        )
        for device_id, language_code in cr.fetchall():
            if language_code in SUPPORTED_LANGUAGES:
                languages_by_device.setdefault(device_id, Counter())[language_code] += 1

    for device in Device.search([]):
        language_counts = languages_by_device.get(device.id)
        if language_counts:
            language_code = sorted(
                language_counts.items(), key=lambda item: (-item[1], item[0])
            )[0][0]
            device.with_context(skip_employee_name_sync=True).write({
                "device_language": language_code,
            })
