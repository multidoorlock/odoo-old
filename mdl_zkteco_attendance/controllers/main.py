import re

from odoo import http
from odoo.http import request


class ZKTecoADMSController(http.Controller):

    @staticmethod
    def _plain_text_response(content):
        """
        Return plain-text HTTP responses to the ZKTeco device.

        ADMS/PUSH devices expect simple text responses rather than
        Odoo HTML pages or JSON responses.
        """
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "text/plain; charset=utf-8"),
            ],
        )

    @staticmethod
    def _decode_body(raw_body):
        """
        Convert the raw request body (bytes) into text.

        ZKTeco firmware may send text using different encodings,
        so we try a few common ones before falling back safely.
        """
        if not raw_body:
            return ""

        for encoding in ("utf-8", "gb18030", "latin-1"):
            try:
                return raw_body.decode(encoding)
            except UnicodeDecodeError:
                continue

        return raw_body.decode("utf-8", errors="replace")

    @staticmethod
    def _get_device():
        """
        Identify the physical clock from the SN query-string value.

        Example:
            /iclock/getrequest?SN=AJP3254400007

        The device model is responsible for finding the existing
        mdl.zk.device record or creating it automatically.
        """
        http_request = request.httprequest

        serial_number = (
            http_request.args.get("SN")
            or http_request.args.get("sn")
            or ""
        ).strip()

        return (
            request.env["mdl.zk.device"]
            .sudo()
            .get_or_create_from_request(
                serial_number=serial_number,
                remote_ip=http_request.remote_addr,
            )
        )

    def _save_raw_request(self, endpoint, device=None):
        """
        Save every request from the clock in mdl.zk.raw.log.

        This gives us a complete technical audit trail even when
        a request is ignored or cannot yet be interpreted.
        """
        http_request = request.httprequest

        raw_body = http_request.get_data(cache=True)
        body_text = self._decode_body(raw_body)

        content_type = (
            http_request.headers.get("Content-Type", "")
            or ""
        )

        # Do not dump arbitrary binary data into a text field.
        if (
            content_type.startswith("image/")
            or b"\x00" in raw_body
        ):
            body_for_log = (
                f"[Binary payload: {len(raw_body)} bytes]"
            )
        else:
            body_for_log = body_text

        query_string = http_request.query_string.decode(
            "utf-8",
            errors="replace",
        )

        table_name = (
            http_request.args.get("table")
            or ""
        ).upper()

        safe_header_names = (
            "Content-Type",
            "Content-Length",
            "User-Agent",
            "Host",
            "X-Forwarded-For",
            "X-Real-IP",
        )

        request_headers = "\n".join(
            f"{header_name}: "
            f"{http_request.headers.get(header_name)}"
            for header_name in safe_header_names
            if http_request.headers.get(header_name)
        )

        serial_number = (
            http_request.args.get("SN")
            or http_request.args.get("sn")
            or ""
        )

        log = (
            request.env["mdl.zk.raw.log"]
            .sudo()
            .create({
                "device_id": device.id if device else False,
                "device_sn": serial_number,
                "method": http_request.method,
                "endpoint": endpoint,
                "remote_ip": http_request.remote_addr,
                "query_string": query_string,
                "table_name": table_name,
                "request_body": body_for_log,
                "request_headers": request_headers,
            })
        )

        return log, raw_body, body_text

    @staticmethod
    def _update_stamps(device):
        """
        Store ADMS synchronization stamps reported by the device.

        These values are technical synchronization markers.
        They are not Odoo attendance records.
        """
        if not device:
            return

        http_request = request.httprequest
        values = {}

        stamp = http_request.args.get("Stamp")
        if stamp:
            values["attendance_stamp"] = stamp

        op_stamp = http_request.args.get("OpStamp")
        if op_stamp:
            values["operation_stamp"] = op_stamp

        photo_stamp = http_request.args.get("PhotoStamp")
        if photo_stamp:
            values["photo_stamp"] = photo_stamp

        if values:
            device.sudo().write(values)

    # -------------------------------------------------------------------------
    # /iclock/cdata
    # -------------------------------------------------------------------------

    @http.route(
        [
            "/iclock/cdata",
            "/iclock/cdata/",
        ],
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def cdata(self, **kwargs):
        """
        Main data endpoint used by the ZKTeco device.

        Current policy:
        - ADMS handshake: handled.
        - ATTLOG: stored in Raw Logs but NOT converted to hr.attendance.
        - USERINFO from clock: stored but ignored.
        - photos from clock: stored but ignored.
        - Odoo remains the source of truth for employee name/photo.
        """
        http_request = request.httprequest

        device = self._get_device()

        log, raw_body, body_text = self._save_raw_request(
            "/iclock/cdata",
            device=device,
        )

        self._update_stamps(device)

        table_name = (
            http_request.args.get("table")
            or ""
        ).upper()

        options = (
            http_request.args.get("options")
            or ""
        ).lower()

        # Initial ADMS handshake.
        if (
            http_request.method == "GET"
            and options == "all"
        ):
            serial_number = (
                device.serial_number
                if device
                else ""
            )

            attendance_stamp = (
                device.attendance_stamp
                if device
                else "0"
            ) or "0"

            operation_stamp = (
                device.operation_stamp
                if device
                else "0"
            ) or "0"

            photo_stamp = (
                device.photo_stamp
                if device
                else "0"
            ) or "0"

            response = (
                f"GET OPTION FROM:{serial_number}\n"
                f"Stamp={attendance_stamp}\n"
                f"OpStamp={operation_stamp}\n"
                f"PhotoStamp={photo_stamp}\n"
                "ErrorDelay=60\n"
                "Delay=10\n"
                "TransTimes=00:00;14:05\n"
                "TransInterval=1\n"
                "TransFlag=1111000000\n"
                "Realtime=1\n"
                "Encrypt=0\n"
            )

            log.sudo().write({
                "processing_state": "processed",
                "processing_message": "ADMS handshake",
            })

            return self._plain_text_response(response)

        if http_request.method == "POST":

            # Attendance records are received and logged,
            # but deliberately NOT converted to hr.attendance yet.
            if table_name == "ATTLOG":
                lines = [
                    line
                    for line in (
                        body_text
                        .replace("\r\n", "\n")
                        .replace("\r", "\n")
                        .split("\n")
                    )
                    if line.strip()
                ]

                log.sudo().write({
                    "processing_state": "ignored",
                    "processing_message": (
                        "ATTLOG received. "
                        "hr.attendance creation is deliberately disabled."
                    ),
                })

                return self._plain_text_response(
                    f"OK: {len(lines)}"
                )

            # Odoo is the source of truth.
            # We keep USERINFO in Raw Logs but do not import it.
            if (
                table_name == "USERINFO"
                or (
                    "PIN=" in body_text.upper()
                    and "NAME=" in body_text.upper()
                )
            ):
                log.sudo().write({
                    "processing_state": "ignored",
                    "processing_message": (
                        "USERINFO received from device and logged. "
                        "Ignored because Odoo is the source of truth "
                        "for employee data."
                    ),
                })

                return self._plain_text_response("OK")

            # Same policy for photos coming from the device.
            if table_name in ("BIOPHOTO", "USERPIC"):
                log.sudo().write({
                    "processing_state": "ignored",
                    "processing_message": (
                        "Photo data received from device and logged. "
                        "Ignored because Odoo is the source of truth "
                        "for employee photos."
                    ),
                })

                return self._plain_text_response("OK")

            # Any other POST is still kept for diagnostics.
            log.sudo().write({
                "processing_state": "processed",
                "processing_message": (
                    f"Received table "
                    f"{table_name or 'UNKNOWN'}"
                ),
            })

            return self._plain_text_response("OK")

        # Other GET requests to cdata that are not options=all.
        log.sudo().write({
            "processing_state": "processed",
            "processing_message": (
                "cdata request received"
            ),
        })

        return self._plain_text_response("OK")

    # -------------------------------------------------------------------------
    # /iclock/getrequest
    # -------------------------------------------------------------------------

    @http.route(
        [
            "/iclock/getrequest",
            "/iclock/getrequest/",
        ],
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def getrequest(self, **kwargs):
        """
        The device polls this endpoint asking whether Odoo has a command.

        If no command is queued:
            Odoo returns: OK

        If a command is queued:
            Odoo returns the command text in the HTTP response.
        """
        device = self._get_device()

        log, _, _ = self._save_raw_request(
            "/iclock/getrequest",
            device=device,
        )

        if not device:
            log.sudo().write({
                "processing_state": "error",
                "processing_message": (
                    "Missing device serial number"
                ),
            })

            return self._plain_text_response("OK")

        command = (
            request.env["mdl.zk.command"]
            .sudo()
            .search(
                [
                    ("device_id", "=", device.id),
                    ("state", "=", "queued"),
                ],
                order="id",
                limit=1,
            )
        )

        if not command:
            log.sudo().write({
                "processing_state": "processed",
                "processing_message": (
                    "No queued command"
                ),
            })

            return self._plain_text_response("OK")

        command.mark_sent()

        log.sudo().write({
            "command_id": command.id,
            "processing_state": "processed",
            "processing_message": (
                f"Sent command {command.id}"
            ),
        })

        return self._plain_text_response(
            command.get_wire_command() + "\n"
        )

    # -------------------------------------------------------------------------
    # /iclock/devicecmd
    # -------------------------------------------------------------------------

    @http.route(
        [
            "/iclock/devicecmd",
            "/iclock/devicecmd/",
        ],
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def devicecmd(self, **kwargs):
        """
        Receive the device's result for a command previously sent by Odoo.

        This endpoint only updates the command status.
        It never imports employee names or photos from the clock.
        """
        device = self._get_device()

        log, _, body_text = self._save_raw_request(
            "/iclock/devicecmd",
            device=device,
        )

        http_request = request.httprequest

        combined = (
            http_request.query_string.decode(
                "utf-8",
                errors="replace",
            )
            + "\n"
            + body_text
        )

        command_id_match = re.search(
            r"(?:^|[\s&])ID=(\d+)",
            combined,
            flags=re.IGNORECASE,
        )

        return_match = re.search(
            r"(?:^|[\s&])Return=(-?\d+)",
            combined,
            flags=re.IGNORECASE,
        )

        command = False

        if command_id_match and device:
            command_id = int(
                command_id_match.group(1)
            )

            # Only accept a result for a command belonging
            # to the same physical ZKTeco device.
            command = (
                request.env["mdl.zk.command"]
                .sudo()
                .search(
                    [
                        ("id", "=", command_id),
                        ("device_id", "=", device.id),
                    ],
                    limit=1,
                )
            )

        if command:
            return_code = (
                int(return_match.group(1))
                if return_match
                else 0
            )

            command.mark_result(
                return_code=return_code,
                response_body=body_text,
            )

            log.sudo().write({
                "command_id": command.id,
                "processing_state": "processed",
                "processing_message": (
                    f"Command {command.id} "
                    f"result {return_code}"
                ),
            })

        else:
            log.sudo().write({
                "processing_state": "ignored",
                "processing_message": (
                    "devicecmd received "
                    "without a matching command"
                ),
            })

        return self._plain_text_response("OK")