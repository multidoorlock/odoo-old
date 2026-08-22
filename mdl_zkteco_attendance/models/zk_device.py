from odoo import api, fields, models


class ZKTecoDevice(models.Model):
    _name = "mdl.zk.device"
    _description = "ZKTeco Attendance Device"
    _order = "name, id"

    name = fields.Char(
        string="שם השעון",
        required=True,
    )

    serial_number = fields.Char(
        string="מספר סידורי",
        required=True,
        copy=False,
        index=True,
    )

    active = fields.Boolean(
        string="פעיל",
        default=True,
    )

    last_seen_at = fields.Datetime(
        string="תקשורת אחרונה",
        readonly=True,
    )

    last_ip = fields.Char(
        string="כתובת IP אחרונה",
        readonly=True,
    )

    attendance_stamp = fields.Char(
        string="Attendance Stamp",
        default="0",
        readonly=True,
    )

    operation_stamp = fields.Char(
        string="Operation Stamp",
        default="0",
        readonly=True,
    )

    photo_stamp = fields.Char(
        string="Photo Stamp",
        default="0",
        readonly=True,
    )

    default_photo_type = fields.Char(
        string="Default Photo Type",
        default="2",
        help="סוג התמונה שישמש כאשר השעון עדיין לא החזיר Photo Type.",
    )

    employee_ids = fields.One2many(
        comodel_name="hr.employee",
        inverse_name="zk_device_id",
        string="עובדים",
    )

    command_ids = fields.One2many(
        comodel_name="mdl.zk.command",
        inverse_name="device_id",
        string="פקודות",
    )

    _sql_constraints = [
        (
            "serial_number_unique",
            "unique(serial_number)",
            "המספר הסידורי של השעון חייב להיות ייחודי.",
        ),
    ]

    @api.model
    def get_or_create_from_request(self, serial_number, remote_ip=None):
        serial_number = (serial_number or "").strip()

        if not serial_number:
            return self.browse()

        device = self.sudo().search(
            [
                ("serial_number", "=", serial_number),
            ],
            limit=1,
        )

        values = {
            "last_seen_at": fields.Datetime.now(),
            "last_ip": remote_ip or False,
        }

        if not device:
            values.update({
                "name": f"ZKTeco {serial_number}",
                "serial_number": serial_number,
            })

            device = self.sudo().create(values)

        else:
            device.sudo().write(values)

        return device