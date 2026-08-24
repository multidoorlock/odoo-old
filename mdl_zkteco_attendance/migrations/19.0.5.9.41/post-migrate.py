from odoo.tools.sql import convert_column_translatable, table_columns


def migrate(cr, version):
    employee_columns = table_columns(cr, "hr_employee")
    resource_columns = table_columns(cr, "resource_resource")

    if employee_columns.get("name", {}).get("udt_name") != "jsonb":
        convert_column_translatable(cr, "hr_employee", "name", "jsonb")

    if resource_columns.get("name", {}).get("udt_name") == "jsonb":
        # Employee translations lived temporarily on resource.resource in the
        # previous version. Move every language to the native employee name.
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
        UPDATE ir_model_fields
           SET translate = NULL
         WHERE model = 'resource.resource'
           AND name = 'name'
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
