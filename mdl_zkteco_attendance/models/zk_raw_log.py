from odoo import fields, models


class ZKTecoRawLog(models.Model):
    _name = "mdl.zk.raw.log"
    _description = "ZKTeco Raw Request"
    _order = "received_at desc, id desc"

    received_at = fields.Datetime(
        string="Received At",
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )

    device_id = fields.Many2one(
        comodel_name="mdl.zk.device",
        string="Device",
        readonly=True,
        ondelete="set null",
        index=True,
    )

    device_sn = fields.Char(
        string="Device Serial Number",
        readonly=True,
        index=True,
    )

    method = fields.Char(
        string="HTTP Method",
        readonly=True,
    )

    endpoint = fields.Char(
        string="Endpoint",
        readonly=True,
    )

    remote_ip = fields.Char(
        string="Remote IP",
        readonly=True,
    )

    query_string = fields.Text(
        string="Query String",
        readonly=True,
    )

    table_name = fields.Char(
        string="Table",
        readonly=True,
        index=True,
    )

    request_body = fields.Text(
        string="Request Body",
        readonly=True,
    )

    request_headers = fields.Text(
        string="Request Headers",
        readonly=True,
    )

    processing_state = fields.Selection(
        selection=[
            ("new", "New"),
            ("processed", "Processed"),
            ("ignored", "Ignored"),
            ("error", "Error"),
        ],
        string="Processing",
        default="new",
        readonly=True,
        index=True,
    )

    processing_message = fields.Text(
        string="Processing Message",
        readonly=True,
    )

    command_id = fields.Many2one(
        comodel_name="mdl.zk.command",
        string="Command",
        readonly=True,
        ondelete="set null",
    )