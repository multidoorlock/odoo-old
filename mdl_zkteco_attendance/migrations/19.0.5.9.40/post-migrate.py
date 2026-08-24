from collections import Counter

from odoo.tools.sql import convert_column_translatable, table_columns


def migrate(cr, version):
    columns = table_columns(cr, "mdl_attendance_device_employee")
    if columns.get("device_name", {}).get("udt_name") == "jsonb":
        cr.execute(
            """
            ALTER TABLE mdl_attendance_device_employee
            ADD COLUMN device_name_plain VARCHAR
            """
        )
        cr.execute(
            """
            UPDATE mdl_attendance_device_employee AS card
               SET device_name_plain = COALESCE(
                   card.device_name ->> device.device_language,
                   card.device_name ->> 'en_US',
                   card.device_name ->> 'he_IL',
                   card.device_name ->> 'ar_001',
                   (SELECT value FROM jsonb_each_text(card.device_name) LIMIT 1)
               )
              FROM mdl_attendance_device AS device
             WHERE device.id = card.device_id
            """
        )
        cr.execute(
            """
            ALTER TABLE mdl_attendance_device_employee DROP COLUMN device_name;
            ALTER TABLE mdl_attendance_device_employee
                RENAME COLUMN device_name_plain TO device_name
            """
        )

    if table_columns(cr, "hr_employee").get("name", {}).get("udt_name") != "jsonb":
        convert_column_translatable(cr, "hr_employee", "name", "jsonb")

    cr.execute(
        """
        SELECT card.employee_id, device.device_language, card.device_name
          FROM mdl_attendance_device_employee AS card
          JOIN mdl_attendance_device AS device ON device.id = card.device_id
         WHERE card.employee_id IS NOT NULL
           AND card.device_name IS NOT NULL
           AND card.device_name != ''
        """
    )
    names_by_employee_language = {}
    for employee_id, language_code, device_name in cr.fetchall():
        key = (employee_id, language_code)
        names_by_employee_language.setdefault(key, Counter())[device_name] += 1
    for (employee_id, language_code), names in names_by_employee_language.items():
        selected_name = sorted(
            names.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        cr.execute(
            """
            UPDATE hr_employee
               SET name = jsonb_set(
                   COALESCE(name, '{}'::jsonb),
                   ARRAY[%s],
                   to_jsonb(%s::text),
                   true
               )
             WHERE id = %s
            """,
            (language_code, selected_name, employee_id),
        )

    cr.execute(
        """
        UPDATE ir_model_fields
           SET translate = NULL
         WHERE model = 'mdl.attendance.device.employee'
           AND name = 'device_name'
        """
    )
