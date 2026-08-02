from odoo import fields, models


class ZKTecoRawLog(models.Model):
    _name = "mdl.zk.raw.log"
    _description = "ZKTeco Raw Request"
    _order = "received_at desc, id desc"

    received_at = fields.Datetime(
        string="Received At",
        default=fields.Datetime.now,
        required=True,
    )

    device_sn = fields.Char(
        string="Device Serial Number",
        index=True,
    )

    method = fields.Char(
        string="HTTP Method",
    )

    endpoint = fields.Char(
        string="Endpoint",
    )

    remote_ip = fields.Char(
        string="Remote IP",
    )

    query_string = fields.Text(
        string="Query String",
    )

    request_body = fields.Text(
        string="Request Body",
    )

    request_headers = fields.Text(
        string="Request Headers",
    )
