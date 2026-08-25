from collections import defaultdict
from datetime import timedelta

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

    @api.model
    def _timeline_attendance_actions(self, attendance, event=False, kind=False):
        actions = [{
            "key": "open_attendance",
            "label": _("פתח נוכחות"),
            "attendance_id": attendance.id,
        }]
        if event and kind in ("in", "out"):
            actions.append({
                "key": "flip_event",
                "label": _("הפוך ליציאה") if kind == "in" else _("הפוך לכניסה"),
                "event_id": event.id,
            })
        return actions

    @api.model
    def _timeline_block_reason(
        self, employee, check_in, check_out=False, exclude_attendance=False,
        enforce_max_duration=True,
    ):
        """Mirror hr.attendance overlap/open constraints without mutating any record."""
        if check_out and check_out <= check_in:
            return _("לא ניתן ליצור נוכחות – היציאה חייבת להיות אחרי הכניסה.")
        if enforce_max_duration and check_out and check_out - check_in > timedelta(days=1):
            return _("לא ניתן ליצור נוכחות – הזוג חורג ממגבלת 24 השעות.")
        Attendance = self.env["hr.attendance"].sudo()
        excluded_id = exclude_attendance.id if exclude_attendance else False
        base_domain = [("employee_id", "=", employee.id)]
        if excluded_id:
            base_domain.append(("id", "!=", excluded_id))

        before_in = Attendance.search(
            base_domain + [("check_in", "<=", check_in)],
            order="check_in desc", limit=1,
        )
        if before_in:
            if not before_in.check_out:
                return _("לא ניתן ליצור נוכחות – קיימת כבר נוכחות פתוחה.")
            if before_in.check_out > check_in:
                return _("לא ניתן ליצור נוכחות – קיימת נוכחות חופפת.")

        if not check_out:
            if Attendance.search(base_domain + [("check_out", "=", False)], limit=1):
                return _("לא ניתן ליצור נוכחות – קיימת כבר נוכחות פתוחה.")
            return False

        before_out = Attendance.search(
            base_domain + [("check_in", "<", check_out)],
            order="check_in desc", limit=1,
        )
        if before_out != before_in:
            return _("לא ניתן ליצור נוכחות – קיימת נוכחות חופפת.")
        return False

    @api.model
    def _timeline_reconcile_employee_ids(self, employee_ids, force_attendance_ids=None):
        """Make device events and managed attendances agree after every edit.

        Direct chronological neighbours are the only events that may form a pair.
        A managed attendance is reused only when it still represents the same pair;
        this preserves its ID on harmless time edits.  Attendances without a source
        IN event are treated as external Odoo data and are never deleted here.
        """
        employee_ids = [int(employee_id) for employee_id in set(employee_ids or []) if employee_id]
        forced_ids = set(int(attendance_id) for attendance_id in (force_attendance_ids or []) if attendance_id)
        if not employee_ids:
            return True

        Event = self.sudo()
        Attendance = self.env["hr.attendance"].sudo()
        Employee = self.env["hr.employee"].sudo()
        internal_context = {"attendance_event_edit_in_progress": True}

        for employee_id in sorted(employee_ids):
            employee = Employee.browse(employee_id).exists()
            if not employee:
                continue
            events = Event.search([
                ("employee_id", "=", employee.id),
                ("processing_state", "!=", "ignored"),
                ("conflict_dismissed", "=", False),
                ("event_datetime", "!=", False),
                "|",
                ("manual_punch_state", "in", ["in", "out"]),
                ("punch_state", "in", ["in", "out"]),
            ], order="event_datetime, id")
            employee_forced = Attendance.browse(list(forced_ids)).exists().filtered(
                lambda attendance: attendance.employee_id == employee
            )
            if not events and not employee_forced:
                continue

            if events:
                self.env.cr.execute(
                    "SELECT id FROM mdl_attendance_device_event WHERE id = ANY(%s) FOR UPDATE",
                    (events.ids,),
                )
                events.invalidate_recordset()

            linked_attendances = events.mapped("attendance_id").exists()
            candidate_attendances = linked_attendances | employee_forced
            if candidate_attendances:
                self.env.cr.execute(
                    "SELECT id FROM hr_attendance WHERE id = ANY(%s) FOR UPDATE",
                    (candidate_attendances.ids,),
                )
                candidate_attendances.invalidate_recordset()

            linked_sources = Event.search([
                ("attendance_id", "in", candidate_attendances.ids),
                ("processing_state", "!=", "ignored"),
                ("event_datetime", "!=", False),
            ], order="event_datetime, id") if candidate_attendances else Event.browse()
            sources_by_attendance = defaultdict(lambda: Event.browse())
            for source in linked_sources:
                sources_by_attendance[source.attendance_id.id] |= source

            def attendance_sources(attendance):
                sources = sources_by_attendance[attendance.id]
                in_sources = sources.filtered(
                    lambda event: (event.manual_punch_state or event.punch_state) == "in"
                )
                out_sources = sources.filtered(
                    lambda event: (event.manual_punch_state or event.punch_state) == "out"
                )
                source_in = min(
                    in_sources,
                    key=lambda event: (abs((event.event_datetime - attendance.check_in).total_seconds()), event.id),
                    default=Event.browse(),
                )
                source_out = min(
                    out_sources,
                    key=lambda event: (
                        abs((event.event_datetime - attendance.check_out).total_seconds()), event.id
                    ),
                    default=Event.browse(),
                ) if attendance.check_out else Event.browse()
                return source_in, source_out

            managed_attendances = Attendance.browse()
            source_pair_by_attendance = {}
            for attendance in candidate_attendances:
                source_in, source_out = attendance_sources(attendance)
                source_pair_by_attendance[attendance.id] = (source_in, source_out)
                if source_in or attendance.id in forced_ids:
                    managed_attendances |= attendance

            event_sequence = list(events)
            desired_pairs = []
            paired_event_ids = set()
            for index, in_event in enumerate(event_sequence[:-1]):
                out_event = event_sequence[index + 1]
                if not (
                    (in_event.manual_punch_state or in_event.punch_state) == "in"
                    and (out_event.manual_punch_state or out_event.punch_state) == "out"
                    and in_event.event_datetime < out_event.event_datetime
                ):
                    continue
                in_attendance = in_event.attendance_id.exists()
                out_attendance = out_event.attendance_id.exists()
                # A closed Odoo attendance already owns both of its endpoints.
                # Never let a neighbouring raw event steal one of those endpoints.
                if out_attendance and out_attendance != in_attendance:
                    continue
                if (
                    in_attendance
                    and in_attendance.check_out
                    and in_attendance != out_attendance
                ):
                    continue
                desired_pairs.append((in_event, out_event))
                paired_event_ids.update((in_event.id, out_event.id))

            reusable_by_pair = {}
            reserved_attendance_ids = set()
            for in_event, out_event in desired_pairs:
                common = in_event.attendance_id if in_event.attendance_id == out_event.attendance_id else Attendance.browse()
                candidates = common if common else in_event.attendance_id
                for attendance in candidates.exists():
                    if attendance.id in reserved_attendance_ids or attendance not in managed_attendances:
                        continue
                    source_in, source_out = source_pair_by_attendance.get(
                        attendance.id, (Event.browse(), Event.browse())
                    )
                    same_full_pair = bool(
                        attendance.check_out
                        and source_in == in_event
                        and source_out == out_event
                    )
                    same_open_in = bool(
                        not attendance.check_out
                        and source_in == in_event
                        and not source_out
                    )
                    if same_full_pair or same_open_in:
                        reusable_by_pair[(in_event.id, out_event.id)] = attendance
                        reserved_attendance_ids.add(attendance.id)
                        break

            singleton_open_by_event = {}
            preserved_full_pairs = {}
            preblocked_reason_by_event = {}
            # A genuine open attendance remains the legal representation of its
            # source IN until a direct-neighbour OUT can close it.  If that IN was
            # edited, update the same open attendance ID when the new value is legal.
            for attendance in managed_attendances.filtered(lambda record: not record.check_out):
                source_in, _source_out = source_pair_by_attendance.get(
                    attendance.id, (Event.browse(), Event.browse())
                )
                if not source_in or source_in.id in paired_event_ids:
                    continue
                blocked_reason = self._timeline_block_reason(
                    employee,
                    source_in.event_datetime,
                    exclude_attendance=attendance,
                )
                if blocked_reason:
                    preblocked_reason_by_event[source_in.id] = blocked_reason
                    continue
                reserved_attendance_ids.add(attendance.id)
                singleton_open_by_event[source_in.id] = attendance

            # Closed attendances already know their own IN/OUT relationship.  A
            # new raw event between those timestamps must not steal an endpoint
            # or cause the known attendance to be deleted merely because the two
            # source events are no longer adjacent in the raw sequence.
            for attendance in managed_attendances.filtered("check_out"):
                if attendance.id in reserved_attendance_ids:
                    continue
                source_in, source_out = source_pair_by_attendance.get(
                    attendance.id, (Event.browse(), Event.browse())
                )
                if not (
                    source_in
                    and source_out
                    and (source_in.manual_punch_state or source_in.punch_state) == "in"
                    and (source_out.manual_punch_state or source_out.punch_state) == "out"
                    and source_in.event_datetime < source_out.event_datetime
                ):
                    continue
                blocked_reason = self._timeline_block_reason(
                    employee,
                    source_in.event_datetime,
                    source_out.event_datetime,
                    exclude_attendance=attendance,
                )
                if blocked_reason:
                    preblocked_reason_by_event[source_in.id] = blocked_reason
                    preblocked_reason_by_event[source_out.id] = blocked_reason
                    continue
                reserved_attendance_ids.add(attendance.id)
                preserved_full_pairs[attendance.id] = (source_in, source_out)

            obsolete_attendances = managed_attendances.filtered(
                lambda attendance: attendance.id not in reserved_attendance_ids
            )
            if obsolete_attendances:
                obsolete_attendances.unlink()
                events.invalidate_recordset(["attendance_id"])

            represented = {}
            blocked_reason_by_event = dict(preblocked_reason_by_event)
            for attendance_id, (source_in, source_out) in preserved_full_pairs.items():
                attendance = Attendance.browse(attendance_id).exists()
                if not attendance:
                    continue
                try:
                    with self.env.cr.savepoint():
                        values = {
                            "employee_id": employee.id,
                            "check_in": source_in.event_datetime,
                            "check_out": source_out.event_datetime,
                        }
                        changed_values = {
                            key: value for key, value in values.items()
                            if (
                                attendance[key].id != value
                                if attendance._fields[key].type == "many2one"
                                else attendance[key] != value
                            )
                        }
                        if changed_values:
                            attendance.write(changed_values)
                except (UserError, ValidationError) as error:
                    attendance.unlink()
                    blocked_reason_by_event[source_in.id] = str(error)
                    blocked_reason_by_event[source_out.id] = str(error)
                    continue
                represented[source_in.id] = attendance
                represented[source_out.id] = attendance
            for event_id, attendance in singleton_open_by_event.items():
                source_in = Event.browse(event_id)
                try:
                    with self.env.cr.savepoint():
                        changed_values = {}
                        if attendance.employee_id != employee:
                            changed_values["employee_id"] = employee.id
                        if attendance.check_in != source_in.event_datetime:
                            changed_values["check_in"] = source_in.event_datetime
                        if changed_values:
                            attendance.write(changed_values)
                except (UserError, ValidationError) as error:
                    attendance.unlink()
                    blocked_reason_by_event[event_id] = str(error)
                    continue
                represented[event_id] = attendance
            for in_event, out_event in desired_pairs:
                attendance = reusable_by_pair.get((in_event.id, out_event.id), Attendance.browse()).exists()
                was_open_attendance = bool(attendance and not attendance.check_out)
                blocked_reason = self._timeline_block_reason(
                    employee,
                    in_event.event_datetime,
                    out_event.event_datetime,
                    exclude_attendance=attendance,
                )
                if blocked_reason:
                    if was_open_attendance:
                        represented[in_event.id] = attendance
                    elif attendance:
                        attendance.unlink()
                    blocked_reason_by_event[out_event.id] = blocked_reason
                    if not was_open_attendance:
                        blocked_reason_by_event[in_event.id] = blocked_reason
                    continue

                values = {
                    "employee_id": employee.id,
                    "check_in": in_event.event_datetime,
                    "check_out": out_event.event_datetime,
                }
                try:
                    with self.env.cr.savepoint():
                        if attendance:
                            changed_values = {
                                key: value for key, value in values.items()
                                if (
                                    attendance[key].id != value
                                    if attendance._fields[key].type == "many2one"
                                    else attendance[key] != value
                                )
                            }
                            if changed_values:
                                attendance.write(changed_values)
                        else:
                            attendance = Attendance.create(values)
                except (UserError, ValidationError) as error:
                    if attendance and not was_open_attendance:
                        attendance.unlink()
                    if was_open_attendance:
                        represented[in_event.id] = attendance
                    blocked_reason_by_event[out_event.id] = str(error)
                    if not was_open_attendance:
                        blocked_reason_by_event[in_event.id] = str(error)
                    continue
                represented[in_event.id] = attendance
                represented[out_event.id] = attendance

            # Preserve legal event links to external/manual Odoo attendances and
            # preserved open attendances.  Only an exact timestamp/type match is green.
            events.invalidate_recordset(["attendance_id"])
            for event in events:
                attendance = event.attendance_id.exists()
                if not attendance or event.id in represented:
                    continue
                kind = event.manual_punch_state or event.punch_state
                if (
                    kind == "in" and attendance.check_in == event.event_datetime
                    or kind == "out" and attendance.check_out == event.event_datetime
                ):
                    represented[event.id] = attendance

            for index, event in enumerate(events):
                attendance = represented.get(event.id, Attendance.browse())
                if attendance:
                    values = {
                        "processing_state": "processed",
                        "processing_message": False,
                        "attendance_id": attendance.id,
                        "conflict_action_failed": False,
                        "conflict_action_error": False,
                    }
                else:
                    kind = event.manual_punch_state or event.punch_state
                    default_reason = _("חסרה יציאה") if kind == "in" else _("חסרה כניסה")
                    reason = blocked_reason_by_event.get(event.id, default_reason)
                    values = {
                        "processing_state": "not_applied",
                        "processing_message": reason,
                        "attendance_id": False,
                        "conflict_action_failed": bool(event.id in blocked_reason_by_event),
                        "conflict_action_error": blocked_reason_by_event.get(event.id, False),
                    }
                changed_values = {
                    key: value for key, value in values.items()
                    if (
                        event[key].id != value
                        if event._fields[key].type == "many2one"
                        else event[key] != value
                    )
                }
                if changed_values:
                    event.with_context(**internal_context).write(changed_values)
        return True

    @api.model
    def _timeline_single_in_presentation(self, event, employee, sequence_conflict=False):
        normalized = (event.processing_message or "").lower()
        if sequence_conflict or "open attendance" in normalized:
            return "2", {
                "key": "flip_event", "label": _("הפוך ליציאה"), "event_id": event.id,
            }, False
        blocked_reason = self._timeline_block_reason(employee, event.event_datetime)
        if not blocked_reason and event.conflict_action_failed:
            blocked_reason = event.conflict_action_error or event.processing_message
        if blocked_reason:
            return "9", {
                "key": "retry_single", "label": _("נסה שוב"), "event_id": event.id,
            }, blocked_reason
        return "8", {
            "key": "create_open_attendance", "label": _("צור נוכחות"), "event_id": event.id,
        }, False

    @api.model
    def _timeline_event_item(
        self, event, state, action=None, pair_key=None, previous=None, blocked_reason=False,
    ):
        effective_state = event.manual_punch_state or event.punch_state
        card = event.device_employee_id
        reason = blocked_reason or self._timeline_event_reason(event, state)
        details = [reason, fields.Datetime.to_string(event.event_datetime)]
        if card:
            details.append(_("כרטיס: %(card)s", card=card.display_name))
        if event.device_id:
            details.append(_("שעון: %(device)s", device=event.device_id.display_name))
        details.append(
            _("מקור: אירוע ידני")
            if event.log_id.request_type == "MANUAL"
            else _("מקור: שעון נוכחות")
        )
        if previous:
            details.append(_(
                "האירוע הקודם: %(kind)s %(time)s",
                kind=_("כניסה") if previous["kind"] == "in" else _("יציאה"),
                time=previous["datetime"],
            ))
        return {
            "id": f"event:{event.id}",
            "source": "event",
            "source_id": event.id,
            "kind": effective_state,
            "datetime": self._timeline_dt(event.event_datetime),
            "state": state,
            "label": _("כניסה") if effective_state == "in" else _("יציאה"),
            "reason": reason,
            "tooltip": "\n".join(details),
            "tooltip_lines": details,
            "device": event.device_id.display_name,
            "card": card.display_name if card else "",
            "log_id": event.log_id.id,
            "pair_key": pair_key,
            "blocked": bool(blocked_reason or state in ("7", "9")),
            "edited": event.timeline_is_edited,
            "sort_id": event.id,
            # Pairing is calculated by the server. Manual drag linking is disabled.
            "linkable": False,
            "actions": self._timeline_event_actions(event, state, action),
        }

    @api.model
    def _timeline_attendance_item(
        self, attendance, kind, value, state, action=None, placeholder=False,
        pair_key=None, event=False,
    ):
        reason_by_state = {
            "1": _("נוכחות תקינה הקיימת ב-Odoo"),
            "1.5": _("נוכחות פתוחה הקיימת ב-Odoo"),
            "6": _("נוכחות פתוחה עם אירוע יציאה שמוכן לעדכון"),
            "7": _("לא ניתן לעדכן כרגע את הנוכחות"),
        }
        return {
            "id": f"attendance:{attendance.id}:{kind}{':placeholder' if placeholder else ''}",
            "source": "attendance",
            "source_id": attendance.id,
            "event_id": event.id if event else False,
            "kind": kind,
            "datetime": self._timeline_dt(value),
            "state": state,
            "label": _("כניסה") if kind == "in" else _("יציאה"),
            "reason": reason_by_state[state],
            "tooltip": "%s\n%s" % (reason_by_state[state], fields.Datetime.to_string(value)),
            "tooltip_lines": [reason_by_state[state], fields.Datetime.to_string(value)],
            "placeholder": placeholder,
            "pair_key": pair_key,
            "blocked": state == "7",
            "edited": event.timeline_is_edited if event else False,
            "sort_id": event.id if event else False,
            "linkable": False,
            "actions": self._timeline_attendance_actions(attendance, event, kind),
        }

    @api.model
    def get_conflict_timeline(self, date_start, date_end, active_domain=None):
        self._timeline_check_manager()
        start, end = self._timeline_parse_range(date_start, date_end)
        Event = self.sudo()
        candidate_domain = [
            ("event_datetime", ">=", start),
            ("event_datetime", "<", end),
            ("processing_state", "!=", "ignored"),
            ("employee_id", "!=", False),
            "|",
            ("manual_punch_state", "in", ["in", "out"]),
            ("punch_state", "in", ["in", "out"]),
        ]
        candidates = Event.search(
            Domain(candidate_domain) & Domain(active_domain or Domain.TRUE),
            order="employee_id, event_datetime, id",
        )
        # Repair stale states left by an interrupted/imported batch before deciding
        # which employees still have conflicts.  The reconciliation is idempotent
        # and uses row locks, so opening the view cannot create duplicates.
        candidate_employee_ids = {
            self._timeline_event_employee(event).id
            for event in candidates
            if self._timeline_event_employee(event)
        }
        if candidate_employee_ids:
            self._timeline_reconcile_employee_ids(candidate_employee_ids)
            candidates = Event.search(
                Domain(candidate_domain) & Domain(active_domain or Domain.TRUE),
                order="employee_id, event_datetime, id",
            )
        conflicts = candidates.filtered(
            lambda event: not event.conflict_dismissed
            and (event.processing_state != "processed" or not event.attendance_id)
        )
        event_employee_ids = list(dict.fromkeys(
            self._timeline_event_employee(event).id for event in conflicts
            if self._timeline_event_employee(event)
        ))
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

        attendance_candidates = self.env["hr.attendance"].sudo().search([
            ("employee_id", "in", event_employee_ids),
            ("check_in", "<", end),
            "|", ("check_out", "=", False), ("check_out", ">=", start),
        ], order="employee_id, check_in, id")
        employee_ids = event_employee_ids
        attendances = attendance_candidates
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
                else employee_attendances[0].employee_id
            )
            items = []
            connections = []
            item_id_by_event = {}
            attendance_connection_ids = set()

            for attendance in employee_attendances:
                pair_key = f"attendance:{attendance.id}"
                if attendance.check_out:
                    state = "1"
                    in_source = source_event(attendance, "in", attendance.check_in)
                    out_source = source_event(attendance, "out", attendance.check_out)
                    items.append(self._timeline_attendance_item(
                        attendance, "in", attendance.check_in, state,
                        pair_key=pair_key,
                        event=in_source,
                    ))
                    items.append(self._timeline_attendance_item(
                        attendance, "out", attendance.check_out, state,
                        pair_key=pair_key,
                        event=out_source,
                    ))
                    connections.append({
                        "id": pair_key, "from": f"attendance:{attendance.id}:in",
                        "to": f"attendance:{attendance.id}:out", "state": state,
                        "actions": [],
                    })
                    attendance_connection_ids.add(attendance.id)
                    if in_source:
                        item_id_by_event[in_source.id] = f"attendance:{attendance.id}:in"
                    if out_source:
                        item_id_by_event[out_source.id] = f"attendance:{attendance.id}:out"
                    continue

                in_source = source_event(attendance, "in", attendance.check_in)
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

            event_sequence = list(employee_events)
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
        self._timeline_check_manager()
        event = self.sudo().browse(event_id).exists()
        if not event:
            return True
        if event.processing_state in ("processed", "ignored"):
            raise UserError(_("האירוע כבר טופל ואינו זמין להסתרה."))
        event.write({"conflict_dismissed": True})
        return True

    @api.model
    def timeline_dismiss_pair(self, event_ids):
        self._timeline_check_manager()
        events = self.sudo().browse(event_ids).exists()
        if len(events) != 2 or any(
            event.processing_state in ("processed", "ignored") or event.attendance_id
            for event in events
        ):
            raise UserError(_("ניתן להסתיר רק זוג שמורכב משני אירועים שטרם נכנסו לנוכחות."))
        events.write({"conflict_dismissed": True})
        return True

    @api.model
    def _timeline_mark_failed(self, events, message):
        events.sudo().write({"conflict_action_failed": True, "conflict_action_error": message})
        return {"ok": False, "message": message}

    @api.model
    def timeline_create_attendance(self, in_event_id, out_event_id=False):
        self._timeline_check_manager()
        event_ids = [event_id for event_id in (in_event_id, out_event_id) if event_id]
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
