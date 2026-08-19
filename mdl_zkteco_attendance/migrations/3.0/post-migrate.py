from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Device = env["mdl.attendance.device"].with_context(active_test=False)
    Card = env["mdl.attendance.device.employee"].with_context(active_test=False)
    Command = env["mdl.attendance.device.command"]
    Log = env["mdl.attendance.device.log"]

    device_map = {}
    for old in env["mdl.zk.device"].with_context(active_test=False).search([]):
        device = Device.search([("legacy_device_id", "=", old.id)], limit=1)
        if not device:
            device = Device.create({
                "name": old.name, "manufacturer": "zkteco",
                "device_identifier": old.serial_number,
                "company_id": env.company.id, "active": old.active,
                "last_seen_at": old.last_seen_at, "last_ip": old.last_ip,
                "attendance_stamp": old.attendance_stamp,
                "operation_stamp": old.operation_stamp, "photo_stamp": old.photo_stamp,
                "default_photo_type": old.default_photo_type,
                "legacy_device_id": old.id,
            })
        device_map[old.id] = device

    card_map = {}
    employees = env["hr.employee"].with_context(active_test=False).search([("zk_device_id", "!=", False), ("zk_user_id", "!=", False)])
    for employee in employees:
        device = device_map.get(employee.zk_device_id.id)
        if not device:
            continue
        card = Card.search([("legacy_employee_id", "=", employee.id), ("device_id", "=", device.id)], limit=1)
        if not card:
            state_map = {"pending_pull": "pending_pull", "pending_push": "pending_push", "synced": "synced", "error": "error"}
            card = Card.with_context(attendance_device_discovery=True).create({
                "employee_id": employee.id, "device_id": device.id,
                "device_user_id": employee.zk_user_id, "device_name": employee.name,
                "profile_photo": employee.image_1920, "link_state": "linked",
                "sync_state": state_map.get(employee.zk_sync_state, "not_synced"),
                "last_sync_at": employee.zk_last_sync_at, "last_sync_error": employee.zk_sync_error,
                "legacy_employee_id": employee.id,
            })
        card_map[(employee.zk_device_id.id, employee.id)] = card

    command_map = {}
    type_map = {
        "pull_user": "request_user", "pull_photo": "request_profile_photo",
        "push_user": "update_name", "push_photo": "update_profile_photo", "custom": "custom",
    }
    for old in env["mdl.zk.command"].search([], order="id"):
        command = Command.search([("legacy_command_id", "=", old.id)], limit=1)
        if not command and old.device_id.id in device_map:
            card = card_map.get((old.device_id.id, old.employee_id.id)) if old.employee_id else False
            command = Command.create({
                "device_id": device_map[old.device_id.id].id,
                "device_employee_id": card.id if card else False,
                "command_type": type_map.get(old.command_type, "custom"),
                "state": old.state, "sent_at": old.sent_at, "completed_at": old.completed_at,
                "raw_command": old.command_text, "raw_response": old.response_body,
                "return_code": old.return_code, "error_message": old.error_message,
                "legacy_command_id": old.id,
            })
        if command:
            command_map[old.id] = command

    state_map = {"new": "new", "processed": "processed", "ignored": "ignored", "error": "error"}
    for old in env["mdl.zk.raw.log"].search([], order="id"):
        if Log.search_count([("legacy_log_id", "=", old.id)]):
            continue
        device = device_map.get(old.device_id.id) if old.device_id else False
        Log.create({
            "received_at": old.received_at, "device_id": device.id if device else False,
            "device_identifier": old.device_sn, "request_type": old.table_name,
            "http_method": old.method, "endpoint": old.endpoint,
            "headers": old.request_headers, "body": old.request_body,
            "query_string": old.query_string, "remote_ip": old.remote_ip,
            "processing_state": state_map.get(old.processing_state, "new"),
            "processing_message": old.processing_message,
            "command_id": command_map.get(old.command_id.id).id if old.command_id and command_map.get(old.command_id.id) else False,
            "legacy_log_id": old.id,
        })
