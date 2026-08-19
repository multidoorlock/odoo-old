from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceDevices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env["mdl.attendance.device"].create({
            "name": "Test clock", "manufacturer": "zkteco",
            "device_identifier": "TEST-SN", "company_id": cls.env.company.id,
            "timezone": "UTC", "punch_state_column": 3,
            "punch_in_values": "1", "punch_out_values": "15",
        })
        cls.employee = cls.env["hr.employee"].create({"name": "Clock Employee", "company_id": cls.env.company.id})
        cls.card = cls.env["mdl.attendance.device.employee"].with_context(attendance_device_discovery=True).create({
            "device_id": cls.device.id, "device_user_id": "74", "device_name": "Clock Employee",
            "employee_id": cls.employee.id,
        })

    def _log(self):
        return self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id, "device_identifier": self.device.device_identifier,
            "request_type": "ATTLOG", "http_method": "POST", "endpoint": "/iclock/cdata",
        })

    def test_in_out_and_duplicate(self):
        adapter = self.device._adapter()
        log = self._log()
        adapter.process_payload(log, "ATTLOG", b"", "74\t2026-08-11 08:00:00\t255\t1\t0\n74\t2026-08-11 17:00:00\t255\t15\t0")
        events = log.event_ids.sorted("event_datetime")
        self.assertEqual(events.mapped("processing_state"), ["processed", "processed"])
        self.assertEqual(events[0].attendance_id, events[1].attendance_id)
        self.assertEqual(events[0].attendance_id.check_in.hour, 8)
        self.assertEqual(events[1].attendance_id.check_out.hour, 17)
        duplicate_log = self._log()
        adapter.process_payload(duplicate_log, "ATTLOG", b"", "74\t2026-08-11 08:00:00\t255\t1\t0")
        self.assertEqual(duplicate_log.event_ids.processing_state, "ignored")

    def test_unlinked_card_waits(self):
        self.env["mdl.attendance.device.employee"].with_context(attendance_device_discovery=True).create({
            "device_id": self.device.id, "device_user_id": "75", "device_name": "Unknown",
        })
        log = self._log()
        self.device._adapter().process_payload(log, "ATTLOG", b"", "75\t2026-08-12 08:00:00\t255\t1\t0")
        self.assertEqual(log.event_ids.processing_state, "waiting_employee_link")
        self.assertFalse(log.event_ids.attendance_id)

    def test_double_in_not_applied(self):
        log = self._log()
        self.device._adapter().process_payload(log, "ATTLOG", b"", "74\t2026-08-13 08:00:00\t255\t1\t0\n74\t2026-08-13 08:05:00\t255\t1\t0")
        events = log.event_ids.sorted("event_datetime")
        self.assertEqual(events[0].processing_state, "processed")
        self.assertEqual(events[1].processing_state, "not_applied")
        self.assertEqual(events[1].processing_message, "Employee already has an open attendance")

    def test_malformed_line_is_preserved_as_error_event(self):
        log = self._log()
        self.device._adapter().process_payload(log, "ATTLOG", b"", "malformed-attlog-line")
        self.assertEqual(len(log.event_ids), 1)
        self.assertEqual(log.event_ids.processing_state, "error")
        self.assertEqual(log.event_ids.raw_line, "malformed-attlog-line")

    def test_manual_cards_use_maximum_identifier_plus_one(self):
        self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True
        ).create({
            "device_id": self.device.id,
            "device_user_id": "100",
            "device_name": "Highest existing card",
        })
        card = self.env["mdl.attendance.device.employee"].create({
            "device_id": self.device.id,
            "device_name": "New system card",
        })
        self.assertEqual(card.device_user_id, "101")
        self.assertFalse(card.employee_id)
        self.assertTrue(card.device_id)
        self.assertEqual(card.sync_state, "pending_push")
        self.assertTrue(card.env["mdl.attendance.device.command"].search_count([
            ("device_employee_id", "=", card.id),
            ("command_type", "=", "create_user"),
            ("state", "=", "queued"),
        ]))

    def test_deleting_odoo_card_queues_device_deletion(self):
        card = self.env["mdl.attendance.device.employee"].create({
            "device_id": self.device.id,
            "device_name": "Delete me",
        })
        pin = card.device_user_id
        card.unlink()
        command = self.env["mdl.attendance.device.command"].search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "delete_user"),
            ("state", "=", "queued"),
        ], order="id desc", limit=1)
        self.assertEqual(command.raw_command, f"DATA DELETE USERINFO PIN={pin}")
        self.assertFalse(command.device_employee_id)

    def test_user_privilege_and_verification_push_and_pull(self):
        self.card.write({"device_privilege": "14", "verification_mode": "19"})
        adapter = self.device._adapter()
        self.assertEqual(adapter.build_command("update_privilege", self.card),
                         "DATA UPDATE USERINFO PIN=74\tName=Clock Employee\tPri=14\tVerify=19")
        self.assertEqual(adapter.build_command("update_verification_mode", self.card),
                         "DATA UPDATE USERINFO PIN=74\tName=Clock Employee\tPri=14\tVerify=19")
        self.card._queue_command("request_privilege")
        self.card._queue_command("request_verification_mode")
        self.card._queue_command("request_user")
        log = self._log()
        adapter.process_payload(
            log, "USERINFO", b"", "USER PIN=74\tName=Clock Employee Updated\tPri=0\tVerify=15",
        )
        self.assertEqual(self.card.device_name, "Clock Employee Updated")
        self.assertEqual(self.card.device_privilege, "0")
        self.assertEqual(self.card.verification_mode, "15")

    def test_device_delete_operlog_deletes_odoo_card_without_loop(self):
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True
        ).create({
            "device_id": self.device.id,
            "device_user_id": "222",
            "device_name": "Deleted on clock",
        })
        log = self._log()
        log.write({"request_type": "OPERLOG"})
        self.device._adapter().process_payload(
            log, "OPERLOG", b"", "OPLOG 9\t0\t2026-08-19 10:00:00\t222\t0\t0\t0\n"
        )
        self.assertFalse(card.exists())
        self.assertFalse(self.env["mdl.attendance.device.command"].search_count([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "delete_user"),
            ("raw_command", "=", "DATA DELETE USERINFO PIN=222"),
        ]))
