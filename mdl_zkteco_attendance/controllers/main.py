import base64
import logging
import re
from urllib.parse import unquote_plus

from psycopg2.errors import DeadlockDetected, SerializationFailure

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ZKTecoADMSController(http.Controller):
    @staticmethod
    def _response(content):
        return request.make_response(content, headers=[("Content-Type", "text/plain; charset=utf-8")])

    @staticmethod
    def _decode(raw):
        for encoding in ("utf-8", "gb18030", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                pass
        return raw.decode("utf-8", errors="replace")

    def _device(self):
        req = request.httprequest
        serial = (req.args.get("SN") or req.args.get("sn") or "").strip()
        return request.env["mdl.attendance.device"].sudo().get_or_create_from_request("zkteco", serial, req.remote_addr)

    def _log(self, endpoint, device):
        req = request.httprequest
        raw = req.get_data(cache=True)
        text = self._decode(raw)
        content_type = req.headers.get("Content-Type", "") or ""
        body = f"[Binary payload: {len(raw)} bytes]" if content_type.startswith("image/") or b"\x00" in raw else text
        safe_headers = ("Content-Type", "Content-Length", "User-Agent", "Host", "X-Forwarded-For", "X-Real-IP")
        headers = "\n".join(f"{key}: {req.headers.get(key)}" for key in safe_headers if req.headers.get(key))
        identifier = req.args.get("SN") or req.args.get("sn") or ""
        request_type = (
            req.args.get("table")
            or req.args.get("type")
            or req.args.get("tablename")
            or ""
        ).upper()
        log = request.env["mdl.attendance.device.log"].sudo().create({
            "device_id": device.id if device else False, "device_identifier": identifier,
            "request_type": request_type, "http_method": req.method, "endpoint": endpoint,
            "headers": headers, "body": body,
            "body_binary": base64.b64encode(raw) if raw else False,
            "query_string": req.query_string.decode("utf-8", errors="replace"), "remote_ip": req.remote_addr,
        })
        return log, raw, text

    def _stamps(self, device):
        if not device:
            return
        req = request.httprequest
        mapping = {"Stamp": "attendance_stamp", "OpStamp": "operation_stamp", "PhotoStamp": "photo_stamp"}
        vals = {field: req.args.get(param) for param, field in mapping.items() if req.args.get(param)}
        if vals:
            device.sudo().write(vals)

    def _reported_settings(self, device):
        if not device:
            return
        req = request.httprequest
        language = req.args.get("language") or req.args.get("Language")
        cooldown = (
            req.args.get("AlarmReRec")
            or req.args.get("alarmrerec")
            or req.args.get("ReCheckMin")
            or req.args.get("recheckmin")
        )
        if language is not None:
            device.sudo()._apply_reported_language(language)
        if cooldown is not None:
            device.sudo()._apply_reported_cooldown(cooldown)

    @http.route(["/iclock/cdata", "/iclock/cdata/"], type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def cdata(self, **kwargs):
        device = self._device()
        log, raw, text = self._log("/iclock/cdata", device)
        self._stamps(device)
        self._reported_settings(device)
        req = request.httprequest
        if not device:
            log.sudo().write({"processing_state": "error", "processing_message": "Missing device serial number"})
            return self._response("OK")
        if req.method == "GET" and (req.args.get("options") or "").lower() == "all":
            response = (
                f"GET OPTION FROM:{device.device_identifier}\nStamp={device.attendance_stamp or '0'}\n"
                f"OpStamp={device.operation_stamp or '0'}\nPhotoStamp={device.photo_stamp or '0'}\n"
                "ErrorDelay=60\nDelay=10\nTransTimes=00:00;14:05\nTransInterval=1\n"
                "TransFlag=1111111111\nRealtime=1\nEncrypt=0\n"
            )
            log.sudo().write({"processing_state": "processed", "processing_message": "ADMS handshake"})
            return self._response(response)
        try:
            count = device._adapter().process_payload(log, req.args.get("table"), raw, text) if req.method == "POST" else 0
        except (DeadlockDetected, SerializationFailure):
            raise
        except Exception as exc:
            _logger.exception("ZKTeco cdata processing failed for log %s", log.id)
            log.sudo().write({"processing_state": "error", "processing_message": str(exc)})
            count = 0
        return self._response(f"OK: {count}" if (req.args.get("table") or "").upper() == "ATTLOG" else "OK")

    @http.route(
        ["/iclock/querydata", "/iclock/querydata/"],
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def querydata(self, **kwargs):
        """Receive asynchronous results for PUSH ``GET OPTIONS`` commands."""
        device = self._device()
        log, raw, text = self._log("/iclock/querydata", device)
        if not device:
            log.sudo().write({
                "processing_state": "error",
                "processing_message": "Missing device serial number",
            })
            return self._response("OK")

        req = request.httprequest
        request_type = (
            req.args.get("type")
            or req.args.get("table")
            or req.args.get("tablename")
            or ""
        ).upper()
        cmdid = req.args.get("cmdid") or req.args.get("CmdId")
        command = False
        if cmdid and str(cmdid).isdigit():
            command_id = int(cmdid)
            command = request.env["mdl.attendance.device.command"].sudo().search([
                ("device_id", "=", device.id),
                "|",
                ("id", "=", command_id),
                ("legacy_command_id", "=", command_id),
            ], limit=1)
        try:
            device._adapter().process_payload(log, request_type, raw, text)
            if command:
                log.sudo().write({"command_id": command.id})
        except (DeadlockDetected, SerializationFailure):
            raise
        except Exception as exc:
            _logger.exception("ZKTeco querydata processing failed for log %s", log.id)
            log.sudo().write({
                "processing_state": "error",
                "processing_message": str(exc),
            })
        return self._response("OK")

    @http.route(["/iclock/getrequest", "/iclock/getrequest/"], type="http", auth="public", methods=["GET"], csrf=False)
    def getrequest(self, **kwargs):
        device = self._device()
        log, _, _ = self._log("/iclock/getrequest", device)
        if not device:
            log.sudo().write({"processing_state": "error", "processing_message": "Missing device serial number"})
            return self._response("OK")
        device.sudo()._queue_automatic_sync()
        command = request.env["mdl.attendance.device.command"].sudo().search([("device_id", "=", device.id), ("state", "=", "queued")], order="id", limit=1)
        if not command:
            log.sudo().write({"processing_state": "processed", "processing_message": "No queued command"})
            return self._response("OK")
        command.mark_sent()
        log.sudo().write({"command_id": command.id, "processing_state": "processed", "processing_message": f"Sent command {command.id}"})
        return self._response(command.get_wire_command() + "\n")

    @http.route(["/iclock/devicecmd", "/iclock/devicecmd/"], type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def devicecmd(self, **kwargs):
        device = self._device()
        log, _, text = self._log("/iclock/devicecmd", device)
        combined = request.httprequest.query_string.decode("utf-8", errors="replace") + "\n" + text
        id_match = re.search(r"(?:^|[\s&])ID=(\d+)", combined, re.I)
        return_match = re.search(r"(?:^|[\s&])Return=(-?\d+)", combined, re.I)
        command = request.env["mdl.attendance.device.command"].sudo().search([
            "|", ("id", "=", int(id_match.group(1))),
            ("legacy_command_id", "=", int(id_match.group(1))),
            ("device_id", "=", device.id),
        ], limit=1) if id_match and device else False
        if command:
            code = int(return_match.group(1)) if return_match else 0
            log.sudo().write({"command_id": command.id, "processing_state": "processed", "processing_message": f"Command {command.id} result {code}"})
            if code >= 0:
                command.device_id._adapter().process_command_response(
                    command, unquote_plus(combined),
                )
            command.mark_result(code, text, log)
        else:
            log.sudo().write({"processing_state": "ignored", "processing_message": "devicecmd without matching command"})
        return self._response("OK")
