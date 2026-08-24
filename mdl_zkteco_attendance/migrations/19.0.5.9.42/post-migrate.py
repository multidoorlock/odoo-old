from odoo.tools.sql import convert_column_translatable, table_columns


def migrate(cr, version):
    card_columns = table_columns(cr, "mdl_attendance_device_employee")
    if card_columns.get("device_name", {}).get("udt_name") == "jsonb":
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

    employee_columns = table_columns(cr, "hr_employee")
    if employee_columns.get("name", {}).get("udt_name") != "jsonb":
        convert_column_translatable(cr, "hr_employee", "name", "jsonb")

    resource_columns = table_columns(cr, "resource_resource")
    if resource_columns.get("name", {}).get("udt_name") == "jsonb":
        cr.execute(
            """
            UPDATE hr_employee AS employee
               SET name = COALESCE(employee.name, '{}'::jsonb)
                          || COALESCE(resource.name, '{}'::jsonb)
              FROM resource_resource AS resource
             WHERE resource.id = employee.resource_id
            """
        )
        convert_column_translatable(cr, "resource_resource", "name", "varchar")

    cr.execute(
        """
        UPDATE resource_resource AS resource
           SET name = COALESCE(
               employee.name ->> 'en_US',
               (SELECT value FROM jsonb_each_text(employee.name) LIMIT 1),
               resource.name
           )
          FROM hr_employee AS employee
         WHERE employee.resource_id = resource.id
        """
    )
    cr.execute(
        """
        UPDATE mdl_attendance_device_employee AS card
           SET device_name = COALESCE(
               employee.name ->> device.device_language,
               employee.name ->> 'en_US',
               (SELECT value FROM jsonb_each_text(employee.name) LIMIT 1),
               card.device_name
           )
          FROM hr_employee AS employee,
               mdl_attendance_device AS device
         WHERE employee.id = card.employee_id
           AND device.id = card.device_id
        """
    )
    cr.execute(
        """
        UPDATE ir_model_fields
           SET translate = NULL
         WHERE (model = 'mdl.attendance.device.employee' AND name = 'device_name')
            OR (model = 'resource.resource' AND name = 'name')
        """
    )
