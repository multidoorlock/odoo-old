from collections import defaultdict
from datetime import timedelta
import uuid

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain


class AttendanceConflictTimeline(models.Model):
    _inherit = "mdl.attendance.device.event"

    _TREATMENT_STATES = {"not_applied", "waiting_employee_link", "error", "new"}

    @api.model
    def _timeline_check_manager(self):
        if not (
            self.env.user.has_group("mdl_zkteco_attendance.group_attendance_device_manager")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("אין לך הרשאה לטפל בקונפליקטים של נוכחות."))

    @api.model
    def _timeline_parse_range(self, date_start, date_end):
        start = fields.Datetime.to_datetime(date_start)
        end = fields.Datetime.to_datetime(date_end)
        if not start or not end or end <= start:
            raise UserError(_("טווח התאריכים אינו תקין."))
        if end - start > timedelta(days=370):
            raise UserError(_("ניתן להציג עד שנה בכל פעם."))
        return start, end

    @api.model
    def _timeline_dt(self, value):
        return fields.Datetime.to_string(value) if value else False

    @api.model
    def _timeline_event_employee(self, event):
        return event.employee_id or event.device_employee_id.employee_id

    @api.model
    def _timeline_lock_employee_ids(self, employee_ids):
        employee_ids = sorted({int(value) for value in employee_ids if value})
        for employee_id in employee_ids:
            # Odoo uses REPEATABLE READ. A lock alone would leave a waiting
            # request with its old snapshot, allowing two new punches to pair
            # twice. This no-op update is an MVCC fence: logical employee and
            # audit values stay unchanged, while a stale concurrent request
            # raises serialization failure for Odoo's standard request retry.
            self.env.cr.execute(
                "UPDATE hr_employee SET write_date = write_date WHERE id = %s RETURNING id",
                (employee_id,),
            )

    @api.model
    def _timeline_real_source_events(self, events):
        return events.filtered(lambda event: not (
            event.odoo_generated and event.attendance_id
            and not event.attendance_id._is_attendance_event_source()
        ))

    @api.model
    def _timeline_lock_sources(self, event_ids=(), attendance_ids=()):
        """Use employee-before-event locking in the legacy pairing RPCs too."""
        events = self.sudo().browse([value for value in event_ids if value]).exists()
        attendances = self.env["hr.attendance"].sudo().browse([
            value for value in attendance_ids if value
        ]).exists()
        self._timeline_lock_employee_ids(
            events.mapped("employee_id").ids
            + events.mapped("device_employee_id.employee_id").ids
            + attendances.mapped("employee_id").ids
        )

    @api.model
    def _timeline_expected_end(self, attendance):
        """Return (scheduled end, scheduled end with grace) as naive UTC datetimes."""
        employee = attendance.employee_id
        tz_name = employee.tz or employee.resource_calendar_id.tz or "UTC"
        employee_tz = pytz.timezone(tz_name)
        check_in_local = pytz.UTC.localize(attendance.check_in).astimezone(employee_tz)
        day_start = check_in_local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        intervals = employee._get_expected_attendances(day_start, day_end)
        interval_ends = [stop for _start, stop, _meta in intervals]
        if interval_ends:
            scheduled_local = max(interval_ends)
        else:
            hours = employee.resource_calendar_id.hours_per_day or 8.0
            scheduled_local = check_in_local + timedelta(hours=hours)
        grace_hours = employee.company_id.auto_check_out_tolerance or 0.0
        scheduled_utc = scheduled_local.astimezone(pytz.UTC).replace(tzinfo=None)
        return scheduled_utc, scheduled_utc + timedelta(hours=grace_hours)

    @api.model
    def _timeline_event_reason(self, event, state):
        if state == "2":
            return _("חסרה יציאה")
        if state == "3":
            return _("חסרה כניסה")
        if state == "7":
            return event.conflict_action_error or event.processing_message or _("Odoo חסם את יצירת הנוכחות")
        return event.conflict_reason

    @api.model
    def _timeline_event_actions(self, event, state, create_action=None):
        effective_state = event.manual_punch_state or event.punch_state
        actions = []
        if effective_state in ("in", "out"):
            actions.append({
                "key": "flip_event",
                "label": _("הפוך ליציאה") if effective_state == "in" else _("הפוך לכניסה"),
                "event_id": event.id,
            })
        actions.append({"key": "dismiss_event", "label": _("הסתר"), "event_id": event.id})
        return actions

    @apinflicts = candidates.filtered(
            lambda event: not event.conflict_dismissed
            and (event.processing_state != "processed" or not event.attendance_id)
        )
        event_employee_ids = list(dict.fromkeys(
            self._timeline_event_employee(event).id for event in conflicts
            if self._timeline_event_employee(event)
        ))
        if not only_conflicts and only_with_data:
            event_employee_ids = list(dict.fromkeys(
                self._timeline_event_employee(event).id for event in candidates
                if self._timeline_event_employee(event)
            ))
        elif not only_conflicts:
            event_employee_ids = self.env["hr.employee"].search([]).ids
        if not event_employee_ids:
            return {"rows": [], "start": self._timeline_dt(start), "end": self._timeline_dt(end)}

        all_events = Event.search([
            ("employee_id", "in", event_employee_ids),
            ("event_datetime", ">=", start),
            ("event_datetime", "<", end),
            ("processing_state", "!=", "ignored"),
            "|",
            ("manual_punch_state", "in", ["in", "out"]),
            ("punch_state", "in", ["in", "out"]),
        ], order="employee_id, event_datetime, id")
        all_events = self._timeline_real_source_events(all_events)

        attendance_candidates = self.env["hr.attendance"].sudo().search([
            ("employee_id", "in", event_employee_ids),
            ("check_in", "<", end),
            "|", ("check_out", "=", False), ("check_out", ">=", start),
        ], order="employee_id, check_in, id")
        employee_ids = event_employee_ids
        attendances = attendance_candidates.filtered(
            lambda attendance: attendance._is_attendance_event_source()
        )
        attendance_events = Event.search([
            ("attendance_id", "in", attendances.ids),
            ("processing_state", "=", "processed"),
            "|",
            ("manual_punch_state", "in", ["in", "out"]),
            ("punch_state", "in", ["in", "out"]),
        ], order="event_datetime, id")
        attendance_events_by_key = defaultdict(lambda: Event.browse())
        for event in attendance_events:
            effective_kind = event.manual_punch_state or event.punch_state
            attendance_events_by_key[(event.attendance_id.id, effective_kind)] |= event

        def source_event(attendance, kind, value):
            candidates = attendance_events_by_key[(attendance.id, kind)]
            if not candidates:
                return Event.browse()
            return min(
                candidates,
                key=lambda event: (abs((event.event_datetime - value).total_seconds()), event.id),
            )

        events_by_employee = defaultdict(lambda: Event.browse())
        conflict_ids = set(conflicts.ids)
        attendance_by_employee = defaultdict(lambda: self.env["hr.attendance"].browse())
        for event in all_events:
            employee = self._timeline_event_employee(event)
            if employee:
                events_by_employee[employee.id] |= event
        for attendance in attendances:
            attendance_by_employee[attendance.employee_id.id] |= attendance

        rows = []
        for employee_id in employee_ids:
            employee_events = events_by_employee[employee_id].sorted(lambda event: (event.event_datetime, event.id))
            employee_attendances = attendance_by_employee[employee_id].sorted(lambda attendance: (attendance.check_in, attendance.id))
            employee = (
                self._timeline_event_employee(employee_events[0])
                if employee_events
                else (employee_attendances[0].employee_id if employee_attendances
                      else self.env["hr.employee"].browse(employee_id))
            )
            items = []
            connections = []
            item_id_by_event = {}
            attendance_connection_ids = set()
            attendance_endpoint_ids = set()

            for attendance in employee_attendances:
                pair_key = f"attendance:{attendance.id}"
                if attendance.check_out:
                    state = "1"
                    in_source = source_event(attendance, "in", attendance.check_in)
                    out_source = source_event(attendance, "out", attendance.check_out)
                    show_in = not in_source.conflict_dismissed
                    show_out = not out_source.conflict_dismissed
                    if show_in:
                        items.append(self._timeline_attendance_item(
                            attendance, "in", attendance.check_in, state,
                            pair_key=pair_key if show_out else False,
                            event=in_source,
                        ))
                    if show_out:
                        items.append(self._timeline_attendance_item(
                            attendance, "out", attendance.check_out, state,
                            pair_key=pair_key if show_in else False,
                            event=out_source,
                        ))
                    if show_in and show_out:
                        connections.append({
                            "id": pair_key, "from": f"attendance:{attendance.id}:in",
                            "to": f"attendance:{attendance.id}:out", "state": state,
                            "pair_type": "attendance",
                            "actions": [],
                        })
                    attendance_connection_ids.add(attendance.id)
                    attendance_endpoint_ids.update({
                        f"attendance:{attendance.id}:in",
                        f"attendance:{attendance.id}:out",
                    })
                    if in_source and show_in:
                        item_id_by_event[in_source.id] = f"attendance:{attendance.id}:in"
                    if out_source and show_out:
                        item_id_by_event[out_source.id] = f"attendance:{attendance.id}:out"
                    continue

                in_source = source_event(attendance, "in", attendance.check_in)
                if in_source.conflict_dismissed:
                    continue
                items.append(self._timeline_attendance_item(
                    attendance, "in", attendance.check_in, "1.5",
                    event=in_source,
                ))
                if in_source:
                    item_id_by_event[in_source.id] = f"attendance:{attendance.id}:in"

            for event in employee_events.filtered(lambda candidate: candidate.id in conflict_ids):
                effective = event.manual_punch_state or event.punch_state
                blocked_reason = event.conflict_action_error or False
                state = "7" if blocked_reason else ("2" if effective == "in" else "3")
                items.append(self._timeline_event_item(
                    event, state, blocked_reason=blocked_reason,
                ))
                item_id_by_event[event.id] = f"event:{event.id}"

            # Synthetic endpoint events make Odoo-created attendances visible
            # and movable, but must not split the neighbour relationship
            # between two genuine clock events.
            event_sequence = list(employee_events.filtered(
                lambda candidate: not candidate.odoo_generated
                and not candidate.conflict_dismissed
            ))
            for index, in_event in enumerate(event_sequence[:-1]):
                out_event = event_sequence[index + 1]
                if not (
                    (in_event.manual_punch_state or in_event.punch_state) == "in"
                    and (out_event.manual_punch_state or out_event.punch_state) == "out"
                ):
                    continue
                from_item = item_id_by_event.get(in_event.id)
                to_item = item_id_by_event.get(out_event.id)
                if not from_item or not to_item:
                    continue
                # A closed attendance already has an authoritative connection.
                # A nearby conflict must never borrow either green endpoint for
                # a second, visually contradictory neighbour connection.
                if from_item in attendance_endpoint_ids or to_item in attendance_endpoint_ids:
                    continue
                if (
                    in_event.attendance_id
                    and in_event.attendance_id == out_event.attendance_id
                    and in_event.attendance_id.id in attendance_connection_ids
                ):
                    continue
                pair_key = f"neighbors:{in_event.id}:{out_event.id}"
                connections.append({
                    "id": pair_key,
                    "from": from_item,
                    "to": to_item,
                    "state": "7",
                    "pair_type": "neighbors",
                    "blocked": True,
                    "actions": [],
                })

            # Every employee in this result has a raw/candidate event. Attendances are
            # always valid context and never make an employee a conflict by themselves.
            rows.append({
                "employee_id": employee.id,
                "employee_name": employee.name,
                "avatar_url": f"/web/image/hr.employee/{employee.id}/avatar_128",
                "items": sorted(
                    items,
                    key=lambda item: (
                        item["datetime"],
                        item.get("sort_id") or 2 ** 63,
                        item["id"],
                    ),
                ),
                "connections": connections,
            })
        return {"rows": rows, "start": self._timeline_dt(start), "end": self._timeline_dt(end)}

    @api.model
    def _timeline_hidden_search_result(self, events, start, end):
        """Display the actual hidden source records without unhiding/re-pairing.

        The native search domain has already been applied, including employee,
        processing-state and visibility chips. Saved events must remain visible
        in this inspection mode even though their ordinary attendance projection
        deliberately omits hidden endpoints.
        """
        rows_by_employee = {}
        for event in events:
            employee = self._timeline_event_employee(event)
            row = rows_by_employee.setdefault(employee.id, {
                "employee_id": employee.id,
                "employee_name": employee.name,
                "avatar_url": f"/web/image/hr.employee/{employee.id}/avatar_128",
                "items": [], "connections": [],
            })
            kind = event.manual_punch_state or event.punch_state
            saved = event.processing_state == "processed" and event.attendance_id
            state = "1" if saved else ("2" if kind == "in" else "3")
            item = self._timeline_event_item(event, state)
            if event.conflict_dismissed:
                reason = _("אירוע מוסתר — נתוני המקור והנוכחות נשמרו")
            elif saved:
                reason = _("נוכחות תקינה הקיימת ב-Odoo")
            else:
                reason = item["reason"]
            item.update({
                "hidden": event.conflict_dismissed,
                "reason": reason,
                "tooltip": "\n".join([reason, self._timeline_dt(event.event_datetime)]),
                "tooltip_lines": [reason, self._timeline_dt(event.event_datetime)],
            })
            if saved:
                item["actions"] = self._timeline_attendance_actions(
                    event.attendance_id, event, kind,
                )
            row["items"].append(item)
        return {
            "rows": list(rows_by_employee.values()),
            "start": self._timeline_dt(start), "end": self._timeline_dt(end),
        }

    @api.model
    def _gantt_unavailability(self, field, res_ids, start, stop, scale):
        """Reuse the exact employee schedule shading from the native Attendance Gantt."""
        if field == "employee_id":
            return self.env["hr.attendance"]._gantt_unavailability(
                field, res_ids, start, stop, scale,
            )
        return super()._gantt_unavailability(field, res_ids, start, stop, scale)

    @api.model
    def timeline_flip_event(self, event_id):
        self._timeline_check_manager()
        event = self.sudo().browse(event_id).exists()
        if not event or event.processing_state == "ignored":
            raise UserError(_("לא ניתן להפוך אירוע שהוגדר כהתעלמות."))
        effective = event.manual_punch_state or event.punch_state
        if effective not in ("in", "out"):
            raise UserError(_("סוג האירוע אינו ניתן להיפוך."))
        event.write({
            "manual_punch_state": "out" if effective == "in" else "in",
        })
        return True

    @api.model
    def timeline_dismiss_event(self, event_id):
        return self.timeline_hide_items(event_ids=[event_id])

    @api.model
    def timeline_dismiss_pair(self, event_ids):
        return self.timeline_hide_items(event_ids=event_ids)

    @api.model
    def timeline_move_event(self, event_id, employee_id, event_datetime):
        self._timeline_check_manager()
        event = self.sudo().browse(int(event_id)).exists()
        employee = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        value = fields.Datetime.to_datetime(event_datetime)
        if not event or not employee or not value:
            raise UserError(_("אירוע הנוכחות, העובד או המועד אינם תקינים."))
        if event.processing_state == "ignored":
            raise UserError(_("לא ניתן להזיז אירוע שהוגדר כהתעלמות."))
        event.write({"employee_id": employee.id, "event_datetime": value})
        return True

    @api.model
    def timeline_hide_items(self, event_ids=None, attendance_ids=None):
        """Hide chosen endpoints without deleting raw events or attendance."""
        self._timeline_check_manager()
        events = self.sudo().browse([int(value) for value in (event_ids or [])]).exists()
        attendances = self.env["hr.attendance"].sudo().browse(
            [int(value) for value in (attendance_ids or [])]
        ).exists()
        if attendances:
            self._timeline_lock_sources(attendance_ids=attendances.ids)
            self._timeline_ensure_hide_endpoints(attendances)
            events |= self.sudo().search([("attendance_id", "in", attendances.ids)])
        events.write({"conflict_dismissed": True})
        return True

    @api.model
    def _timeline_ensure_hide_endpoints(self, attendances):
        """Store visibility for legacy native endpoints without running sync.

        Existing clock events, timestamps, links and attendance rows must stay
        untouched by Hide. Only a missing endpoint needs a new provenance row
        to remember its hidden state when the timeline is opened again.
        """
        Event = self.sudo()
        for attendance in attendances:
            if not attendance._is_attendance_event_source():
                continue
            linked = Event.search([
                ("attendance_id", "=", attendance.id),
                ("processing_state", "=", "processed"),
            ])
            kinds = {event.manual_punch_state or event.punch_state for event in linked}
            missing = [
                (kind, value)
                for kind, value in (("in", attendance.check_in), ("out", attendance.check_out))
                if value and kind not in kinds
            ]
            if not missing:
                continue
            device, card = attendance._attendance_event_source()
            log = self.env["mdl.attendance.device.log"].sudo().create({
                "device_id": device.id,
                "device_identifier": device.device_identifier,
                "request_type": "ODOO", "http_method": "ORM", "endpoint": "hr.attendance",
                "processing_state": "processed",
                "processing_message": "Generated hidden Odoo attendance endpoint",
            })
            Event.with_context(attendance_event_system_write=True).create([
                {
                    "employee_id": attendance.employee_id.id,
                    "event_datetime": value,
                    "processing_state": "processed",
                    "attendance_id": attendance.id,
                    "conflict_dismissed": True,
                    "log_id": log.id, "device_id": device.id,
                    "device_employee_id": card.id,
                    "device_user_id": card.device_user_id if card else False,
                    "raw_line": "Odoo attendance endpoint",
                    "raw_punch_state": kind, "punch_state": kind,
                    "event_fingerprint": "odoo:%s:%s:%s" % (attendance.id, kind, uuid.uuid4().hex),
                    "odoo_generated": True,
                }
                for kind, value in missing
            ])

    @api.model
    def timeline_delete_items(self, event_ids=None, attendance_ids=None):
        # Compatibility for a browser tab that still has the previous bundle.
        # A stale client must not retain a destructive version of the action.
        return self.timeline_hide_items(event_ids, attendance_ids)

    @api.model
    def _timeline_mark_failed(self, events, message):
        events.sudo().write({"conflict_action_failed": True, "conflict_action_error": message})
        return {"ok": False, "message": message}

    @api.model
    def timeline_create_attendance(self, in_event_id, out_event_id=False):
        self._timeline_check_manager()
        event_ids = [event_id for event_id in (in_event_id, out_event_id) if event_id]
        self._timeline_lock_sources(event_ids=event_ids)
        self.env.cr.execute(
            "SELECT id FROM mdl_attendance_device_event WHERE id = ANY(%s) FOR UPDATE",
            (event_ids,),
        )
        in_event = self.sudo().browse(in_event_id).exists()
        out_event = self.sudo().browse(out_event_id).exists() if out_event_id else self.browse()
        events = in_event | out_event
        events.invalidate_recordset()
        in_employee = self._timeline_event_employee(in_event)
        out_employee = self._timeline_event_employee(out_event) if out_event else in_employee
        if (
            not in_event
            or not in_employee
            or in_event.processing_state not in self._TREATMENT_STATES
            or in_event.conflict_dismissed
            or (in_event.manual_punch_state or in_event.punch_state) != "in"
        ):
            raise UserError(_("אירוע הכניסה אינו תקין."))
        if out_event and (
            out_event.processing_state not in self._TREATMENT_STATES
            or out_event.conflict_dismissed
            or (out_event.manual_punch_state or out_event.punch_state) != "out"
            or out_employee != in_employee
            or out_event.event_datetime <= in_event.event_datetime
            or out_event.event_datetime - in_event.event_datetime > timedelta(days=1)
        ):
            raise UserError(_("אירוע היציאה אינו מתאים לאירוע הכניסה."))
        events.filtered(lambda event: not event.employee_id).with_context(
            attendance_event_system_write=True,
        ).write({"employee_id": in_employee.id})
        values = {"employee_id": in_employee.id, "check_in": in_event.event_datetime}
        if out_event:
            values["check_out"] = out_event.event_datetime
        try:
            with self.env.cr.savepoint():
                attendance = self.env["hr.attendance"].sudo().create(values)
        except ValidationError as error:
            return self._timeline_mark_failed(events, str(error))
        events.write({
            "processing_state": "processed", "processing_message": False,
            "attendance_id": attendance.id, "conflict_action_failed": False,
            "conflict_action_error": False,
        })
        return {"ok": True, "attendance_id": attendance.id}

    @api.model
    def timeline_update_attendance(self, attendance_id, out_event_id):
        self._timeline_check_manager()
        self._timeline_lock_sources([out_event_id], [attendance_id])
        self.env.cr.execute(
            "SELECT id FROM hr_attendance WHERE id = %s FOR UPDATE",
            (attendance_id,),
        )
        self.env.cr.execute(
            "SELECT id FROM mdl_attendance_device_event WHERE id = %s FOR UPDATE",
            (out_event_id,),
        )
        attendance = self.env["hr.attendance"].sudo().browse(attendance_id).exists()
        event = self.sudo().browse(out_event_id).exists()
        attendance.invalidate_recordset()
        event.invalidate_recordset()
        if (
            not attendance or attendance.check_out or not event
            or event.processing_state not in self._TREATMENT_STATES
            or event.conflict_dismissed
        ):
            raise UserError(_("הנוכחות הפתוחה או אירוע היציאה אינם זמינים עוד."))
        event_employee = self._timeline_event_employee(event)
        if event_employee != attendance.employee_id or (event.manual_punch_state or event.punch_state) != "out":
            raise UserError(_("אירוע היציאה אינו מתאים לנוכחות הפתוחה."))
        if not event.employee_id:
            event.with_context(attendance_event_system_write=True).write({
                "employee_id": event_employee.id,
            })
        try:
            with self.env.cr.savepoint():
                self._timeline_check_attendance_editable(attendance)
                attendance.write({"check_out": event.event_datetime})
        except ValidationError as error:
            return self._timeline_mark_failed(event, str(error))
        event.write({
            "processing_state": "processed", "processing_message": False,
            "attendance_id": attendance.id, "conflict_action_failed": False,
            "conflict_action_error": False,
        })
        return {"ok": True, "attendance_id": attendance.id}

    @api.model
    def timeline_link_items(self, in_source, in_id, out_source, out_id):
        self._timeline_check_manager()
        if out_source != "event":
            raise UserError(_("ניתן לחבר יציאה שעדיין קיימת כאירוע נוכחות בלבד."))
        self._timeline_lock_sources(
            [out_id, in_id] if in_source == "event" else [out_id],
            [in_id] if in_source == "attendance" else [],
        )
        self.env.cr.execute(
            "SELECT id FROM mdl_attendance_device_event WHERE id = %s FOR UPDATE",
            (out_id,),
        )
        out_event = self.sudo().browse(out_id).exists()
        if (
            not out_event
            or out_event.processing_state not in self._TREATMENT_STATES
            or out_event.conflict_dismissed
            or (out_event.manual_punch_state or out_event.punch_state) != "out"
        ):
            raise UserError(_("אירוע היציאה אינו זמין לחיבור."))

        out_employee = self._timeline_event_employee(out_event)
        Event = self.sudo()
        if out_event.timeline_pair_event_id or out_event.timeline_pair_attendance_id:
            raise UserError(_("אירוע היציאה כבר מחובר. יש לנתק את הזוג לפני חיבור חדש."))
        links_to_clear = out_event
        values = {"timeline_pair_event_id": False, "timeline_pair_attendance_id": False}
        if in_source == "event":
            self.env.cr.execute(
                "SELECT id FROM mdl_attendance_device_event WHERE id = %s FOR UPDATE",
                (in_id,),
            )
            in_event = self.sudo().browse(in_id).exists()
            if (
                not in_event
                or in_event.processing_state not in self._TREATMENT_STATES
                or in_event.conflict_dismissed
                or (in_event.manual_punch_state or in_event.punch_state) != "in"
                or self._timeline_event_employee(in_event) != out_employee
                or in_event.event_datetime >= out_event.event_datetime
                or out_event.event_datetime - in_event.event_datetime > timedelta(days=1)
            ):
                raise UserError(_("אירוע הכניסה אינו מתאים לאירוע היציאה."))
            if Event.search_count([("timeline_pair_event_id", "=", in_event.id)]):
                raise UserError(_("אירוע הכניסה כבר מחובר. יש לנתק את הזוג לפני חיבור חדש."))
            links_to_clear |= in_event
            values["timeline_pair_event_id"] = in_event.id
            out_event.write({"timeline_blocked_in_event_ids": [(3, in_event.id)]})
        elif in_source == "attendance":
            self.env.cr.execute(
                "SELECT id FROM hr_attendance WHERE id = %s FOR UPDATE",
                (in_id,),
            )
            attendance = self.env["hr.attendance"].sudo().browse(in_id).exists()
            if (
                not attendance
                or attendance.check_out
                or attendance.employee_id != out_employee
                or attendance.check_in >= out_event.event_datetime
                or out_event.event_datetime - attendance.check_in > timedelta(days=1)
            ):
                raise UserError(_("הנוכחות הפתוחה אינה מתאימה לאירוע היציאה."))
            if Event.search_count([("timeline_pair_attendance_id", "=", attendance.id)]):
                raise UserError(_("הנוכחות הפתוחה כבר מחוברת. יש לנתק את הזוג לפני חיבור חדש."))
            values["timeline_pair_attendance_id"] = attendance.id
            out_event.write({"timeline_blocked_attendance_ids": [(3, attendance.id)]})
        else:
            raise UserError(_("מקור הכניסה אינו נתמך בחיבור ידני."))

        links_to_clear.write({
            "timeline_pair_event_id": False,
            "timeline_pair_attendance_id": False,
        })
        out_event.write(values)
        return True

    @api.model
    def timeline_unlink_pair(self, in_source, in_id, out_event_id):
        self._timeline_check_manager()
        self._timeline_lock_sources(
            [out_event_id, in_id] if in_source == "event" else [out_event_id],
            [in_id] if in_source == "attendance" else [],
        )
        self.env.cr.execute(
            "SELECT id FROM mdl_attendance_device_event WHERE id = %s FOR UPDATE",
            (out_event_id,),
        )
        out_event = self.sudo().browse(out_event_id).exists()
        if not out_event:
            return True
        values = {
            "timeline_pair_event_id": False,
            "timeline_pair_attendance_id": False,
        }
        if in_source == "event":
            in_event = self.sudo().browse(in_id).exists()
            if in_event:
                values["timeline_blocked_in_event_ids"] = [(4, in_event.id)]
        elif in_source == "attendance":
            attendance = self.env["hr.attendance"].sudo().browse(in_id).exists()
            if attendance:
                values["timeline_blocked_attendance_ids"] = [(4, attendance.id)]
        else:
            raise UserError(_("מקור הכניסה אינו נתמך בניתוק."))
        out_event.write(values)
        return True

    @api.model
    def timeline_manual_event_action(self, employee_id=False, punch_state="in", event_datetime=False, attendance_id=False):
        self._timeline_check_manager()
        context = {
            "default_employee_id": employee_id,
            "default_punch_state": punch_state,
            "default_event_datetime": event_datetime or fields.Datetime.now(),
            "default_attendance_id": attendance_id,
        }
        return {
            "type": "ir.actions.act_window",
            "name": _("אירוע נוכחות חדש"),
            "res_model": "mdl.attendance.conflict.event.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": context,
        }

    @api.model
    def timeline_attendance_form_action(self, attendance_id):
        self._timeline_check_manager()
        attendance = self.env["hr.attendance"].browse(attendance_id).exists()
        if not attendance:
            raise UserError(_("רשומת הנוכחות לא נמצאה."))
        view = self.env.ref(
            "mdl_zkteco_attendance.view_hr_attendance_conflict_readonly_form"
        )
        return {
            "type": "ir.actions.act_window", "name": _("נוכחות"),
            "res_model": "hr.attendance", "res_id": attendance.id,
            "view_mode": "form", "views": [(view.id, "form")],
            "target": "new",
            "context": {
                "form_view_initial_mode": "view",
                "create": False,
                "edit": False,
                "delete": False,
            },
        }

    @api.model
    def timeline_event_form_action(self, event_id, readonly=False):
        self._timeline_check_manager()
        event = self.sudo().browse(event_id).exists()
        if not event:
            raise UserError(_("אירוע הנוכחות לא נמצא."))
        view = self.env.ref(
            "mdl_zkteco_attendance.view_device_event_readonly_form"
            if readonly
            else "mdl_zkteco_attendance.view_device_event_form"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("אירוע נוכחות"),
            "res_model": "mdl.attendance.device.event",
            "res_id": event.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "target": "new",
            "context": {
                "form_view_initial_mode": "view" if readonly else "edit",
                "create": False,
                "edit": not readonly,
                "delete": False,
            },
        }
