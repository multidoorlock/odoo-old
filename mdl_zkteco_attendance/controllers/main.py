from odoo import http
from odoo.http import request


class ZKTecoADMSController(http.Controller):

    @staticmethod
    def _plain_text_response(content):
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "text/plain; charset=utf-8"),
            ],
        )

    @staticmethod
    def _save_raw_request(endpoint):
        http_request = request.httprequest

        device_sn = (
            http_request.args.get("SN")
            or http_request.args.get("sn")
            or ""
        )

        query_string = http_request.query_string.decode(
            "utf-8",
            errors="replace",
        )

        request_body = http_request.get_data(
            cache=True,
            as_text=True,
        )

        safe_header_names = (
            "Content-Type",
            "Content-Length",
            "User-Agent",
            "Host",
            "X-Forwarded-For",
            "X-Real-IP",
        )

        request_headers = "\n".join(
            f"{header_name}: {http_request.headers.get(header_name)}"
            for header_name in safe_header_names
            if http_request.headers.get(header_name)
        )

        request.env["mdl.zk.raw.log"].sudo().create({
            "device_sn": device_sn,
            "method": http_request.method,
            "endpoint": endpoint,
            "remote_ip": http_request.remote_addr,
            "query_string": query_string,
            "request_body": request_body,
            "request_headers": request_headers,
        })

        return device_sn

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
        device_sn = self._save_raw_request("/iclock/cdata")
        http_request = request.httprequest

        is_initial_connection = (
            http_request.method == "GET"
            and http_request.args.get("options") == "all"
        )

        if is_initial_connection:
            response = (
                f"GET OPTION FROM:{device_sn}\n"
                "Stamp=9999\n"
                "OpStamp=9999\n"
                "PhotoStamp=9999\n"
                "ErrorDelay=60\n"
                "Delay=10\n"
                "TransTimes=00:00;14:05\n"
                "TransInterval=1\n"
                "TransFlag=1111000000\n"
                "Realtime=1\n"
                "Encrypt=0\n"
            )

            return self._plain_text_response(response)

        return self._plain_text_response("OK")

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
        self._save_raw_request("/iclock/getrequest")

        return self._plain_text_response("OK")

    @http.route(
        [
            "/iclock/devicecmd",
            "/iclock/devicecmd/",
        ],
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def devicecmd(self, **kwargs):
        self._save_raw_request("/iclock/devicecmd")

        return self._plain_text_response("OK")