/** @odoo-module **/

import {
    Component,
    onMounted,
    onPatched,
    onWillUnmount,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { diffColumn } from "@web_gantt/gantt_helpers";
import { AttendanceGanttModel } from "@hr_attendance_gantt/attendance_gantt/attendance_gantt_model";
import { AttendanceGanttRenderer } from "@hr_attendance_gantt/attendance_gantt/attendance_gantt_renderer";
import { attendanceGanttView } from "@hr_attendance_gantt/attendance_gantt/attendance_gantt_view";

const TILE_METRICS_BY_SCALE = {
    day: { width: 46, height: 46, top: 4, compact: false },
    week: { width: 46, height: 46, top: 4, compact: false },
    month: { width: 46, height: 46, top: 4, compact: false },
};

const SUMMARY_HEIGHT = 28;
const SUMMARY_TOP = 4;
const BUCKET_ITEM_GAP = 5;
const BUCKET_PADDING = 5;
const MIN_TILE_GAP = 8;

const VARIANT_BY_STATE = {
    "1": "success",
    "1.5": "success",
    "2": "danger",
    "3": "danger",
    "4": "danger",
    "5": "success",
    "6": "danger",
    "7": "danger",
    "8": "danger",
    "9": "danger",
    "10": "success",
};

const COLOR_BY_VARIANT = {
    success: "#afffdb",
    danger: "#efbebe",
};

export class AttendanceTooltip extends Component {
    static template = "mdl_zkteco_attendance.AttendanceTooltip";
    static props = ["item"];
}

export class AttendanceEventTile extends Component {
    static template = "mdl_zkteco_attendance.AttendanceEventTile";
    static components = { AttendanceTooltip };
    static props = ["item", "style", "dragging", "selected", "onOpen", "onSelect", "onPointerDown", "onContextMenu"];

    setup() {
        this.state = useState({ hovered: false });
    }

    get ariaLabel() {
        return `${this.props.item.label} ${this.props.item.displayTime}: ${this.props.item.reason}`;
    }

    onClick(ev) {
        ev.stopPropagation();
        if (ev.ctrlKey || ev.metaKey) {
            this.props.onSelect(this.props.item);
            return;
        }
        if (this.props.item.dragged) {
            this.props.item.dragged = false;
            return;
        }
        this.props.onOpen(this.props.item);
    }

    onPointerDown(ev) {
        if (ev.button === 0) {
            this.props.onPointerDown(ev, this.props.item);
        }
    }

    onContextMenu(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this.props.onContextMenu(ev, this.props.item);
    }

    onKeydown(ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.props.onOpen(this.props.item);
        }
    }

}

export class AttendanceTreatmentSummary extends Component {
    static template = "mdl_zkteco_attendance.AttendanceTreatmentSummary";
    static props = ["summary", "style"];
}

export class AttendanceConnector extends Component {
    static template = "mdl_zkteco_attendance.AttendanceConnector";
    static props = ["connection"];

    setup() {
        this.rootRef = useRef("root");
        this.measuredGeometry = useState({
            measured: false,
            width: 0,
            height: 0,
            left: 0,
            top: 0,
            rectWidth: 0,
            rectHeight: 0,
            x1: 0,
            x2: 0,
        });
        onMounted(() => this._scheduleGeometryMeasurement());
        onPatched(() => this._scheduleGeometryMeasurement());
        onWillUnmount(() => {
            if (this._measurementFrame) {
                cancelAnimationFrame(this._measurementFrame);
            }
        });
    }

    get renderedGeometry() {
        return this.measuredGeometry.measured
            ? this.measuredGeometry
            : this.props.connection;
    }

    _scheduleGeometryMeasurement() {
        if (this._measurementFrame) {
            cancelAnimationFrame(this._measurementFrame);
        }
        this._measurementFrame = requestAnimationFrame(() => {
            this._measurementFrame = null;
            this._measureGeometry();
        });
    }

    _measureGeometry() {
        const root = this.rootRef.el;
        if (!root) {
            return;
        }
        const itemContainer = root.closest(".o_gantt_cells") || document;
        const findItemElement = (itemId) => itemContainer.querySelector(
            `[data-mdl-timeline-item-id="${CSS.escape(String(itemId))}"]`
        );
        const fromElement = findItemElement(this.props.connection.fromId);
        const toElement = findItemElement(this.props.connection.toId);
        if (!fromElement || !toElement) {
            return;
        }

        const rootRect = root.getBoundingClientRect();
        const fromRect = fromElement.getBoundingClientRect();
        const toRect = toElement.getBoundingClientRect();
        const nextGeometry = {
            measured: true,
            width: Math.max(1, rootRect.width),
            height: Math.max(1, rootRect.height),
            left: Math.min(fromRect.left, toRect.left) - rootRect.left,
            top: Math.min(fromRect.top, toRect.top) - rootRect.top,
            rectWidth: Math.max(fromRect.right, toRect.right)
                - Math.min(fromRect.left, toRect.left),
            rectHeight: Math.max(fromRect.bottom, toRect.bottom)
                - Math.min(fromRect.top, toRect.top),
            x1: (fromRect.left + fromRect.right) / 2 - rootRect.left,
            x2: (toRect.left + toRect.right) / 2 - rootRect.left,
        };
        const geometryChanged = !this.measuredGeometry.measured
            || ["width", "height", "left", "top", "rectWidth", "rectHeight", "x1", "x2"].some(
                (key) => Math.abs(this.measuredGeometry[key] - nextGeometry[key]) > 0.25
            );
        if (geometryChanged) {
            Object.assign(this.measuredGeometry, nextGeometry);
        }
    }

}

export class AttendanceContextMenu extends Component {
    static template = "mdl_zkteco_attendance.AttendanceContextMenu";
    static props = ["menu", "onSelect"];
}

export class AttendanceConflictGanttModel extends AttendanceGanttModel {
    async _fetchData(metaData, additionalContext) {
        const requestId = (this._timelineRequestId || 0) + 1;
        this._timelineRequestId = requestId;
        const scale = metaData.scale.id === "month"
            ? {
                ...metaData.scale,
                // Native week already includes the weekday. Keep that same useful
                // header in month/custom ranges that use the month scale.
                colHeaderFormatter: (date) => date.toFormat("cccc d"),
                // The native 52px month column only has room for a day number.
                // Preserve enough space for the requested weekday label as well.
                minimalColumnWidth: Math.max(metaData.scale.minimalColumnWidth, 92),
            }
            : metaData.scale;
        metaData = { ...metaData, scale, groupedBy: ["employee_id"] };
        const domain = this._getDomain(metaData);
        const timelinePromise = this.orm.call(
            "mdl.attendance.device.event",
            "get_conflict_timeline",
            [
                serializeDateTime(metaData.globalStart),
                serializeDateTime(metaData.globalStop),
                domain,
            ]
        );
        await super._fetchData(metaData, additionalContext);
        const conflictTimeline = await timelinePromise;
        if (requestId === this._timelineRequestId) {
            this.data.conflictTimeline = conflictTimeline;
            const existingEmployees = new Set(
                this.data.rows.map((row) => Number(row.resId)).filter(Boolean)
            );
            for (const timelineRow of conflictTimeline.rows || []) {
                const employeeId = Number(timelineRow.employee_id);
                if (existingEmployees.has(employeeId)) {
                    continue;
                }
                const employeeValue = [employeeId, timelineRow.employee_name];
                this.data.rows.push({
                    consolidate: false,
                    fromServer: false,
                    groupedBy: ["employee_id"],
                    groupedByField: "employee_id",
                    groupLevel: 0,
                    id: JSON.stringify([{ employee_id: employeeValue }]),
                    name: timelineRow.employee_name,
                    resId: employeeId,
                    recordIds: [],
                });
                existingEmployees.add(employeeId);
            }
            this.data.count = this.data.rows.length;
        }
    }
}

export class AttendanceConflictGanttRenderer extends AttendanceGanttRenderer {
    static template = "mdl_zkteco_attendance.AttendanceConflictGanttRenderer";
    static rowContentTemplate = "mdl_zkteco_attendance.AttendanceConflictGanttRenderer.RowContent";
    static components = {
        ...AttendanceGanttRenderer.components,
        AttendanceEventTile,
        AttendanceTreatmentSummary,
        AttendanceConnector,
        AttendanceContextMenu,
    };

    setup() {
        super.setup();
        this.contextMenuState = useState({ menu: null });
        this.interactionState = useState({ selectedIds: [], drag: null });
        useExternalListener(window, "click", () => {
            this.contextMenuState.menu = null;
        });
        useExternalListener(window, "pointermove", (ev) => this.onTimelinePointerMove(ev));
        useExternalListener(window, "pointerup", (ev) => this.onTimelinePointerUp(ev));
    }

    computeDerivedParams() {
        this._prepareTimelineRows();
        super.computeDerivedParams();
    }

    computeUnavailabilityPeriods() {
        super.computeUnavailabilityPeriods();
        // Keep Odoo's work-schedule background, but never allow time columns to
        // be folded in the conflict timeline.
        this.foldableColumns = new Array(this.columnCount).fill(0);
        this.foldableColumnsMapping = {};
    }

    computeFoldedGrid() {
        // Make Odoo clear every derived folded-grid mapping as if the user had
        // manually opened the final folded group. Merely zeroing
        // `foldableColumns` still leaves one-column folded spans behind and
        // prevents the timeline's bucket widths from expanding.
        this.offHoursState.foldedColumns = new Array(this.columnCount).fill(0);
        super.computeFoldedGrid();
    }

    getPills() {
        // The ORM records only provide native Gantt rows, filters and paging.
        // IN/OUT points are rendered by AttendanceEventTile, never as Gantt records.
        return [];
    }

    computeSomeWidths() {
        this._timelineColumnWidths = null;
        super.computeSomeWidths();
        if (
            !this._timelineUsesExpandedTimeColumns
            || this.offHoursState.foldedGridColumnSpans
        ) {
            return;
        }
        const widths = new Array(this.foldedGridColumnCount).fill(this.columnWidth);
        for (const [columnIndex, desiredWidth] of this._timelineDesiredColumnWidths) {
            if (0 <= columnIndex && columnIndex < widths.length) {
                widths[columnIndex] = Math.max(widths[columnIndex], desiredWidth);
            }
        }
        this._timelineColumnWidths = widths;
        this.virtualGrid.setColumnsWidths(widths);
        this.totalWidth = widths.reduce((sum, width) => sum + width, 0) + this.rowHeaderWidth;
    }

    getSubColumnsDistance(start, stop, cellPartWidth) {
        if (!this._timelineColumnWidths || this.offHoursState.foldedGridColumnSpans) {
            return super.getSubColumnsDistance(start, stop, cellPartWidth);
        }
        const { cellPart } = this.model.metaData.scale;
        let distance = 0;
        for (let column = start; column < stop; column++) {
            const coarseIndex = Math.floor((column - 1) / cellPart);
            const coarseWidth = this._timelineColumnWidths[coarseIndex] || this.columnWidth;
            distance += coarseWidth / cellPart;
        }
        return { distance, flexible: false };
    }

    getColInCoarseGridKeys() {
        if (
            this._timelineColumnWidths
            && this._timelineUsesExpandedTimeColumns
            && !this.offHoursState.foldedGridColumnSpans
        ) {
            // Keep every time-unit line in detailed views. Odoo normally
            // virtualizes these lines while scrolling; custom point elements must
            // keep a stable named grid line so tiles and connectors move together.
            const lastGridLine =
                this.columnCount * this.model.metaData.scale.cellPart + 1;
            return Array.from({ length: lastGridLine }, (_, index) => String(index + 1));
        }
        return super.getColInCoarseGridKeys();
    }

    processRow(row, pills, processAsGroup = true) {
        const previousRow = this._modelRowBeingProcessed;
        this._modelRowBeingProcessed = row;
        try {
            return super.processRow(row, [], processAsGroup);
        } finally {
            this._modelRowBeingProcessed = previousRow;
        }
    }

    getRowTypeHeight(type) {
        if (type === "t1" && this._modelRowBeingProcessed && !this._modelRowBeingProcessed.rows) {
            const timelineRow = this._timelineRowsByEmployee?.get(
                Number(this._modelRowBeingProcessed.resId)
            );
            if (timelineRow) {
                return timelineRow.rowHeight;
            }
        }
        if (type === "t2" && this._modelRowBeingProcessed && !this._modelRowBeingProcessed.rows) {
            return 8;
        }
        return super.getRowTypeHeight(type);
    }

    _prepareTimelineRows() {
        const sourceTimeline = this.model.data.conflictTimeline;
        const metrics = this._getTileMetrics();
        const cacheKey = [
            this.model.metaData.rangeId,
            this.model.metaData.scale.id,
            this.model.metaData.scale.cellPart,
            metrics.width,
            metrics.height,
            metrics.top,
        ].join(":");
        if (this._preparedTimeline === sourceTimeline && this._preparedScaleKey === cacheKey) {
            return;
        }
        this._preparedTimeline = sourceTimeline;
        this._preparedScaleKey = cacheKey;
        this._timelineRowsByEmployee = new Map();
        this._timelineItemsById = new Map();
        const rows = sourceTimeline?.rows || [];
        const { globalStart, globalStop, rangeId } = this.model.metaData;
        this._timelineDesiredColumnWidths = this._computeDesiredTimeColumnWidths(
            rows, metrics, globalStart, globalStop, rangeId
        );
        this._timelineUsesExpandedTimeColumns = this._timelineDesiredColumnWidths.size > 0;
        for (const sourceRow of rows) {
            const items = (sourceRow.items || [])
                .map((sourceItem) => {
                    const datetime = deserializeDateTime(sourceItem.datetime);
                    return {
                        ...sourceItem,
                        datetime,
                        displayDatetime: datetime,
                        employeeId: Number(sourceRow.employee_id),
                        displayTime: datetime.toFormat("HH:mm"),
                        variant: VARIANT_BY_STATE[sourceItem.state] || "danger",
                        compact: metrics.compact,
                        tooltipDate: datetime.toFormat("dd/LL/yyyy HH:mm:ss"),
                    };
                })
                .filter((item) => item.datetime.isValid && item.datetime >= globalStart && item.datetime < globalStop)
                .sort((left, right) => {
                    const timeDifference = left.datetime.toMillis() - right.datetime.toMillis();
                    if (timeDifference) {
                        return timeDifference;
                    }
                    const leftSortId = Number(left.sort_id || Number.MAX_SAFE_INTEGER);
                    const rightSortId = Number(right.sort_id || Number.MAX_SAFE_INTEGER);
                    const eventOrderDifference = leftSortId - rightSortId;
                    if (eventOrderDifference) {
                        return eventOrderDifference;
                    }
                    const sourceDifference = Number(left.source === "event") - Number(right.source === "event");
                    if (sourceDifference) {
                        return sourceDifference;
                    }
                    const idDifference = Number(left.source_id) - Number(right.source_id);
                    if (idDifference) {
                        return idDifference;
                    }
                    return String(left.kind).localeCompare(String(right.kind));
                });

            if (!this._isDetailedTimeline(rangeId, globalStart, globalStop)) {
                this._timelineRowsByEmployee.set(Number(sourceRow.employee_id), {
                    ...sourceRow,
                    items: [],
                    connections: [],
                    summaries: this._buildTreatmentSummaries(
                        items,
                        this._getTreatmentSummaryUnit(rangeId)
                    ),
                    metrics,
                    rowHeight: metrics.top * 2 + metrics.height,
                    detailed: false,
                });
                continue;
            }

            const itemsById = new Map(items.map((item) => [item.id, item]));
            const connections = (sourceRow.connections || [])
                .map((connection) => ({
                    ...connection,
                    fromItem: itemsById.get(connection.from),
                    toItem: itemsById.get(connection.to),
                }))
                .filter((connection) => connection.fromItem && connection.toItem);

            const connectedItemIds = new Set();
            const usableConnections = [];
            const itemIndexById = new Map(items.map((item, index) => [item.id, index]));
            for (const connection of connections) {
                const fromIndex = itemIndexById.get(connection.fromItem.id);
                const toIndex = itemIndexById.get(connection.toItem.id);
                // A connector is a visual statement that two direct neighbours
                // belong together.  Never draw it across a third event.
                if (Math.abs(fromIndex - toIndex) !== 1) {
                    continue;
                }
                if (
                    connectedItemIds.has(connection.fromItem.id) ||
                    connectedItemIds.has(connection.toItem.id)
                ) {
                    continue;
                }
                connectedItemIds.add(connection.fromItem.id);
                connectedItemIds.add(connection.toItem.id);
                connection.fromItem.paired = true;
                connection.toItem.paired = true;
                usableConnections.push(connection);
            }
            // Keep every event on the employee's single timeline row. Close
            // timestamps are packed horizontally inside an expanded time
            // column, with the same minimum gap whether or not they are linked.
            this._packItemsInsideTimeBuckets(items, metrics, globalStart);
            for (const item of items) {
                item.visualLane = 0;
            }
            const laneCount = 1;
            this._timelineRowsByEmployee.set(Number(sourceRow.employee_id), {
                ...sourceRow,
                items,
                connections: usableConnections,
                summaries: [],
                metrics,
                rowHeight: Math.max(
                    32,
                    metrics.top * 2
                        + laneCount * metrics.height
                        + Math.max(0, laneCount - 1) * MIN_TILE_GAP,
                ),
                detailed: true,
            });
            for (const item of items) {
                this._timelineItemsById.set(item.id, item);
            }
        }
    }

    _computeDesiredTimeColumnWidths(rows, metrics, globalStart, globalStop, rangeId) {
        const widths = new Map();
        const { scale } = this.model.metaData;
        if (!this._isDetailedTimeline(rangeId, globalStart, globalStop)) {
            return widths;
        }
        if (!["hour", "day"].includes(scale.interval)) {
            return widths;
        }
        const maximumCountByColumn = new Map();
        for (const sourceRow of rows) {
            const rowCountByColumn = new Map();
            for (const sourceItem of sourceRow.items || []) {
                const datetime = deserializeDateTime(sourceItem.datetime);
                if (!datetime.isValid || datetime < globalStart || datetime >= globalStop) {
                    continue;
                }
                const columnIndex = this._getTimelineColumnIndex(datetime, globalStart);
                rowCountByColumn.set(columnIndex, (rowCountByColumn.get(columnIndex) || 0) + 1);
            }
            for (const [columnIndex, count] of rowCountByColumn) {
                maximumCountByColumn.set(
                    columnIndex,
                    Math.max(maximumCountByColumn.get(columnIndex) || 0, count)
                );
            }
        }
        for (const [columnIndex, count] of maximumCountByColumn) {
            const contentWidth = count * metrics.width
                + Math.max(0, count - 1) * BUCKET_ITEM_GAP;
            widths.set(
                columnIndex,
                Math.max(scale.minimalColumnWidth, contentWidth + BUCKET_PADDING * 2)
            );
        }
        return widths;
    }

    _assignTimelineLanes(items, metrics, globalStart) {
        if (!items.length) {
            return 1;
        }
        const { interval } = this.model.metaData.scale;
        const defaultColumnWidth = this.columnWidth;
        const columnOffsets = [0];
        for (let index = 0; index < this.foldedGridColumnCount; index++) {
            columnOffsets.push(
                columnOffsets[index]
                    + (this._timelineDesiredColumnWidths.get(index) || defaultColumnWidth)
            );
        }
        const laneHeap = [];
        let laneCount = 0;
        const pushLane = (entry) => {
            laneHeap.push(entry);
            let index = laneHeap.length - 1;
            while (index > 0) {
                const parent = Math.floor((index - 1) / 2);
                if (laneHeap[parent].right <= entry.right) {
                    break;
                }
                laneHeap[index] = laneHeap[parent];
                index = parent;
            }
            laneHeap[index] = entry;
        };
        const popLane = () => {
            const first = laneHeap[0];
            const last = laneHeap.pop();
            if (laneHeap.length) {
                let index = 0;
                while (true) {
                    let child = index * 2 + 1;
                    if (child >= laneHeap.length) {
                        break;
                    }
                    if (child + 1 < laneHeap.length
                            && laneHeap[child + 1].right < laneHeap[child].right) {
                        child++;
                    }
                    if (laneHeap[child].right >= last.right) {
                        break;
                    }
                    laneHeap[index] = laneHeap[child];
                    index = child;
                }
                laneHeap[index] = last;
            }
            return first;
        };
        for (const item of items) {
            const columnIndex = this._getTimelineColumnIndex(item.datetime, globalStart);
            const columnStart = globalStart.startOf(interval).plus({ [interval]: columnIndex });
            const columnStop = columnStart.plus({ [interval]: 1 });
            const duration = Math.max(columnStop.toMillis() - columnStart.toMillis(), 1);
            const fraction = Math.max(
                0,
                Math.min(1, (item.datetime.toMillis() - columnStart.toMillis()) / duration),
            );
            const columnWidth = this._timelineDesiredColumnWidths.get(columnIndex)
                || defaultColumnWidth;
            const center = (columnOffsets[columnIndex] || 0) + fraction * columnWidth;
            const left = center - metrics.width / 2;
            const right = center + metrics.width / 2;
            const available = laneHeap[0]?.right + MIN_TILE_GAP <= left
                ? popLane()
                : null;
            const lane = available ? available.lane : laneCount++;
            pushLane({ lane, right });
            item.visualLane = lane;
        }
        return Math.max(1, laneCount);
    }

    _packItemsInsideTimeBuckets(items, metrics, globalStart) {
        const itemsByColumn = new Map();
        for (const item of items) {
            const columnIndex = this._getTimelineColumnIndex(item.datetime, globalStart);
            if (!this._timelineDesiredColumnWidths.has(columnIndex)) {
                continue;
            }
            if (!itemsByColumn.has(columnIndex)) {
                itemsByColumn.set(columnIndex, []);
            }
            itemsByColumn.get(columnIndex).push(item);
        }
        for (const [columnIndex, bucketItems] of itemsByColumn) {
            const columnWidth = this._timelineDesiredColumnWidths.get(columnIndex);
            const contentWidth =
                bucketItems.length * metrics.width
                + Math.max(0, bucketItems.length - 1) * BUCKET_ITEM_GAP;
            const firstCenter = (columnWidth - contentWidth) / 2 + metrics.width / 2;
            bucketItems.forEach((item, index) => {
                item.visualTimeColumn = columnIndex;
                item.visualBucketOffset =
                    firstCenter + index * (metrics.width + BUCKET_ITEM_GAP);
            });
        }
    }

    _getTimelineColumnIndex(datetime, globalStart = this.model.metaData.globalStart) {
        const { interval } = this.model.metaData.scale;
        return diffColumn(globalStart.startOf(interval), datetime.startOf(interval), interval);
    }

    _isDetailedTimeline(rangeId, globalStart, globalStop) {
        if (["day", "week", "month"].includes(rangeId)) {
            return true;
        }
        // A custom range still uses one of Odoo's real Gantt scales. It must render
        // the same point tiles as that scale, never an aggregate treatment pill.
        return rangeId === "custom" && globalStop > globalStart;
    }

    _getTreatmentSummaryUnit(rangeId) {
        if (rangeId === "week") {
            return "day";
        }
        if (rangeId === "custom") {
            const scaleUnit = this.model.metaData.scale.unit;
            return ["day", "week", "month", "year"].includes(scaleUnit)
                ? scaleUnit
                : "day";
        }
        return ["month", "quarter"].includes(rangeId) ? "month" : "year";
    }

    _buildTreatmentSummaries(items, unit) {
        const grouped = new Map();
        for (const item of items) {
            if (item.source !== "event") {
                continue;
            }
            const start = item.datetime.startOf(unit);
            const key = start.toISO();
            if (!grouped.has(key)) {
                grouped.set(key, {
                    id: `summary:${key}`,
                    start,
                    stop: start.plus({ [unit]: 1 }),
                    eventIds: new Set(),
                });
            }
            grouped.get(key).eventIds.add(item.source_id);
        }
        return [...grouped.values()]
            .map(({ id, start, stop, eventIds }) => ({
                id,
                start,
                stop,
                count: eventIds.size,
                label: `${eventIds.size} ${_t("אירועים לטיפול")}`,
            }))
            .sort((left, right) => left.start.toMillis() - right.start.toMillis());
    }

    _getTileMetrics() {
        return TILE_METRICS_BY_SCALE[this.model.metaData.scale.id] || TILE_METRICS_BY_SCALE.month;
    }

    getTimelineRow(row) {
        if (row.isGroup || !row.resId) {
            return null;
        }
        return this._timelineRowsByEmployee?.get(Number(row.resId)) || null;
    }

    getTimelineRowHitboxStyle(row) {
        const [rowStart, rowStop] = row.grid.row;
        return this.getGridPosition({
            column: [1, this.columnCount * this.model.metaData.scale.cellPart + 1],
            row: [rowStart, rowStop],
        });
    }

    _datetimeFromPointer(ev, element, clientX = ev.clientX) {
        const rect = element.getBoundingClientRect();
        const { globalStart, globalStop } = this.model.metaData;
        let raw;
        if (this._timelineColumnWidths?.length) {
            let offset = localization.direction === "rtl"
                ? rect.right - clientX
                : clientX - rect.left;
            offset = Math.max(0, Math.min(rect.width, offset));
            let columnIndex = 0;
            while (
                columnIndex < this._timelineColumnWidths.length - 1
                && offset > this._timelineColumnWidths[columnIndex]
            ) {
                offset -= this._timelineColumnWidths[columnIndex];
                columnIndex++;
            }
            const width = this._timelineColumnWidths[columnIndex] || this.columnWidth;
            const fraction = Math.max(0, Math.min(1, offset / width));
            const interval = this.model.metaData.scale.interval;
            const columnStart = globalStart.startOf(interval).plus({ [interval]: columnIndex });
            const columnStop = columnStart.plus({ [interval]: 1 });
            raw = columnStart.plus({
                milliseconds: (columnStop.toMillis() - columnStart.toMillis()) * fraction,
            });
        } else {
            const horizontalRatio = Math.max(
                0, Math.min(1, (clientX - rect.left) / rect.width)
            );
            const ratio = localization.direction === "rtl"
                ? 1 - horizontalRatio
                : horizontalRatio;
            const milliseconds = globalStop.toMillis() - globalStart.toMillis();
            raw = globalStart.plus({ milliseconds: milliseconds * ratio });
        }
        const minute = Math.round(raw.minute / 15) * 15;
        const snapped = raw.startOf("hour").plus({ minutes: minute });
        return snapped < globalStart ? globalStart : (snapped >= globalStop ? globalStop.minus({ minutes: 15 }) : snapped);
    }

    onEmptyTimelineContextMenu(ev, row) {
        ev.preventDefault();
        ev.stopPropagation();
        const datetime = this._datetimeFromPointer(ev, ev.currentTarget);
        this.contextMenuState.menu = {
            actions: [{
                key: "create_event",
                label: _t("יצירת אירוע נוכחות"),
                employee_id: Number(row.resId),
                event_datetime: serializeDateTime(datetime),
            }],
            x: Math.min(ev.clientX, window.innerWidth - 230),
            y: Math.min(ev.clientY, window.innerHeight - 100),
        };
    }

    startTimelineDrag(ev, item) {
        const eventId = item.event_id || (item.source === "event" ? item.source_id : false);
        if (!eventId) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const tile = ev.currentTarget;
        const rect = tile.getBoundingClientRect();
        this.interactionState.drag = {
            item, startX: ev.clientX, startY: ev.clientY,
            x: ev.clientX, y: ev.clientY, moved: false,
            grabX: ev.clientX - rect.left,
            grabY: ev.clientY - rect.top,
            width: rect.width,
            height: rect.height,
            eventId: Number(eventId),
            employeeId: item.employeeId,
            hitbox: document.querySelector(
                `.o_mdl_timeline_row_hitbox[data-employee-id="${item.employeeId}"]`
            ),
            datetime: item.datetime,
            label: item.tooltipDate,
        };
    }

    onTimelinePointerMove(ev) {
        const drag = this.interactionState.drag;
        if (drag) {
            drag.x = ev.clientX;
            // A timeline event always belongs to its employee. Vertical mouse
            // movement is deliberately ignored; dragging only changes time.
            drag.y = drag.startY;
            drag.moved = drag.moved || Math.hypot(
                ev.clientX - drag.startX, ev.clientY - drag.startY
            ) > 3;
            const hitbox = drag.hitbox;
            if (hitbox) {
                // The event datetime belongs to the centre of the tile. Keep
                // the exact point grabbed by the user under the pointer so a
                // drag that starts at an edge does not jump by half a tile.
                const tileCenterX = ev.clientX + drag.width / 2 - drag.grabX;
                drag.datetime = this._datetimeFromPointer(ev, hitbox, tileCenterX);
                drag.label = drag.datetime.toFormat("dd/LL/yyyy HH:mm");
            }
        }
    }

    async onTimelinePointerUp() {
        const drag = this.interactionState.drag;
        if (drag) {
            this.interactionState.drag = null;
            if (drag.moved && drag.eventId) {
                drag.item.dragged = true;
                await this.orm.call(
                    "mdl.attendance.device.event", "timeline_move_event",
                    [drag.eventId, drag.employeeId, serializeDateTime(drag.datetime)]
                );
                await this.model.fetchData();
            }
            return;
        }
        return;
    }

    isTimelineDragging(item) {
        const drag = this.interactionState.drag;
        return Boolean(
            drag?.moved && drag.item.id === item.id
        );
    }

    toggleTimelineSelection(item) {
        const selected = new Set(this.interactionState.selectedIds);
        if (selected.has(item.id)) {
            selected.delete(item.id);
        } else {
            selected.add(item.id);
        }
        this.interactionState.selectedIds = [...selected];
    }

    isTimelineSelected(item) {
        return this.interactionState.selectedIds.includes(item.id);
    }

    deleteSelectedTimelineItems() {
        const items = this.interactionState.selectedIds
            .map((id) => this._timelineItemsById.get(id)).filter(Boolean);
        const eventIds = [...new Set(items.filter((item) => item.source === "event")
            .map((item) => item.source_id))];
        const attendanceIds = [...new Set(items.filter((item) => item.source === "attendance")
            .map((item) => item.source_id))];
        if (!eventIds.length && !attendanceIds.length) {
            return;
        }
        this.dialogService.add(ConfirmationDialog, {
            title: _t("מחיקת אירועי נוכחות"),
            body: _t("למחוק את כל אירועי הנוכחות שנבחרו?"),
            confirmLabel: _t("מחיקה"),
            confirm: async () => {
                await this.orm.call(
                    "mdl.attendance.device.event", "timeline_delete_items",
                    [eventIds, attendanceIds]
                );
                this.interactionState.selectedIds = [];
                await this.model.fetchData();
            },
        });
    }

    _getTimelinePosition(datetime, item = null) {
        const { globalStart, globalStop, scale } = this.model.metaData;
        if (!datetime?.isValid || datetime < globalStart || datetime >= globalStop) {
            return null;
        }
        const { column, delta } = this.getSubColumnFromDate(datetime);
        let columnNumber =
            1 + diffColumn(globalStart, column, scale.interval) * scale.cellPart + delta;
        const subColumn = this.getSubColumnFromColNumber(columnNumber);
        const subColumnStop = subColumn.start.plus({ [scale.time]: scale.cellTime });
        const duration = subColumnStop.toMillis() - subColumn.start.toMillis();
        const ratio = Math.max(
            0,
            Math.min(1, (datetime.toMillis() - subColumn.start.toMillis()) / duration)
        );
        const coarseIndex = Math.floor((columnNumber - 1) / scale.cellPart);
        if (
            item?.visualTimeColumn === coarseIndex
            && Number.isFinite(item.visualBucketOffset)
        ) {
            return {
                column: 1 + coarseIndex * scale.cellPart,
                span: scale.cellPart,
                offset: item.visualBucketOffset,
            };
        }
        const subColumnWidth = this._timelineColumnWidths
            ? this._timelineColumnWidths[coarseIndex] / scale.cellPart
            : this.cellPartWidth;
        return {
            column: columnNumber,
            offset: ratio * subColumnWidth,
        };
    }

    getTimelineItemStyle(item, row) {
        const position = this._getTimelinePosition(item.displayDatetime, item);
        if (!position) {
            return null;
        }
        const { metrics } = this.getTimelineRow(row);
        const [rowStart, rowStop] = row.grid.row;
        const style = [
            this.getGridPosition({
                column: [position.column, position.column + (position.span || 1)],
                row: [rowStart, rowStop],
            }),
            `width:${metrics.width}px`,
            `height:${metrics.height}px`,
            `margin-inline-start:${position.offset - metrics.width / 2}px`,
            `margin-top:${metrics.top + (item.visualLane || 0) * (metrics.height + MIN_TILE_GAP)}px`,
        ];
        const drag = this.interactionState.drag;
        if (drag?.moved && drag.item.id === item.id) {
            style.push(
                `transform:translate(${drag.x - drag.startX}px,${drag.y - drag.startY}px)`,
                "z-index:1110",
                "pointer-events:none"
            );
        }
        return style.join(";");
    }

    getTimelineSummaryStyle(summary, row) {
        const { globalStart, globalStop } = this.model.metaData;
        const start = summary.start < globalStart ? globalStart : summary.start;
        const stop = summary.stop > globalStop ? globalStop : summary.stop;
        if (stop <= start) {
            return null;
        }
        const [columnStart, columnStop] = this.getGridColumnFromDates(start, stop);
        const [rowStart, rowStop] = row.grid.row;
        return [
            `grid-column:${columnStart}/${columnStop}`,
            `grid-row:${rowStart}/${rowStop}`,
            `height:${SUMMARY_HEIGHT}px`,
            `margin-top:${SUMMARY_TOP}px`,
            "margin-inline:2px",
        ].join(";");
    }

    getTimelineConnection(connection, row, timelineRow) {
        const fromPosition = this._getTimelinePosition(
            connection.fromItem.displayDatetime, connection.fromItem
        );
        const toPosition = this._getTimelinePosition(
            connection.toItem.displayDatetime, connection.toItem
        );
        if (!fromPosition || !toPosition) {
            return null;
        }

        const firstColumn = Math.min(fromPosition.column, toPosition.column);
        const lastColumn = Math.max(
            fromPosition.column + (fromPosition.span || 1),
            toPosition.column + (toPosition.span || 1)
        );
        const width = this.getSubColumnsDistance(
            firstColumn, lastColumn, this.cellPartWidth
        ).distance;
        const logicalFrom = this.getSubColumnsDistance(
            firstColumn, fromPosition.column, this.cellPartWidth
        ).distance + fromPosition.offset;
        const logicalTo = this.getSubColumnsDistance(
            firstColumn, toPosition.column, this.cellPartWidth
        ).distance + toPosition.offset;
        const isRtl = localization.direction === "rtl";
        const x1 = isRtl ? width - logicalFrom : logicalFrom;
        const x2 = isRtl ? width - logicalTo : logicalTo;
        const { metrics } = timelineRow;
        const top = metrics.top + Math.min(
            connection.fromItem.visualLane || 0,
            connection.toItem.visualLane || 0,
        ) * (metrics.height + MIN_TILE_GAP);

        const safeId = String(connection.id).replace(/[^a-zA-Z0-9_-]/g, "_");
        const [rowStart, rowStop] = row.grid.row;
        return {
            id: safeId,
            style: this.getGridPosition({
                column: [firstColumn, lastColumn],
                row: [rowStart, rowStop],
            }),
            width,
            height: timelineRow.rowHeight,
            left: Math.min(x1, x2) - metrics.width / 2,
            top,
            rectWidth: Math.abs(x2 - x1) + metrics.width,
            rectHeight: metrics.height,
            x1,
            x2,
            fromId: connection.fromItem.id,
            toId: connection.toItem.id,
            fromColor: COLOR_BY_VARIANT[connection.fromItem.variant],
            toColor: COLOR_BY_VARIANT[connection.toItem.variant],
        };
    }

    async openTimelineItem(item) {
        const eventId = item.event_id || (item.source === "event" ? item.source_id : false);
        this.contextMenuState.menu = null;
        if (!eventId) {
            this.notificationService.add(
                _t("לא נמצא אירוע נוכחות מקושר לרשומה זו."),
                { type: "warning" }
            );
            return;
        }
        try {
            const actionData = await this.orm.call(
                "mdl.attendance.device.event",
                "timeline_event_form_action",
                [eventId, false]
            );
            await this.actionService.doAction(actionData, {
                onClose: () => this.model.fetchData(),
            });
        } catch (error) {
            const message = error.data?.message || error.message || _t("לא ניתן לפתוח את הרשומה.");
            this.notificationService.add(message, { type: "danger", sticky: true });
        }
    }

    onTimelineContextMenu(ev, item) {
        if (
            this.interactionState.selectedIds.length > 1
            && this.interactionState.selectedIds.includes(item.id)
        ) {
            this.contextMenuState.menu = {
                item,
                actions: [{ key: "delete_selected", label: _t("מחיקה") }],
                x: Math.min(ev.clientX, window.innerWidth - 230),
                y: Math.min(ev.clientY, window.innerHeight - 220),
            };
            return;
        }
        if (!item.actions?.length) {
            return;
        }
        this.contextMenuState.menu = {
            item,
            actions: item.actions,
            x: Math.min(ev.clientX, window.innerWidth - 230),
            y: Math.min(ev.clientY, window.innerHeight - 220),
        };
    }

    async onContextAction(action) {
        this.contextMenuState.menu = null;
        if (action.key === "delete_selected") {
            this.deleteSelectedTimelineItems();
            return;
        }
        if (["dismiss_event", "dismiss_pair"].includes(action.key)) {
            this.dialogService.add(ConfirmationDialog, {
                title: _t("להסתיר את אירוע הנוכחות?"),
                body: _t("האירוע יוסתר לצמיתות ממסך הקונפליקטים."),
                confirmLabel: _t("הסתר"),
                confirm: () => this._executeContextAction(action),
            });
            return;
        }
        await this._executeContextAction(action);
    }

    async _executeContextAction(action) {
        try {
            if (action.key === "create_event") {
                const actionData = await this.orm.call(
                    "mdl.attendance.device.event", "timeline_manual_event_action",
                    [action.employee_id, "in", action.event_datetime, false]
                );
                await this.actionService.doAction(actionData, {
                    onClose: () => this.model.fetchData(),
                });
                return;
            }
            if (action.key === "open_event") {
                return this.openTimelineItem({ source: "event", source_id: action.event_id });
            }
            if (action.key === "open_attendance") {
                const actionData = await this.orm.call(
                    "mdl.attendance.device.event",
                    "timeline_attendance_form_action",
                    [action.attendance_id]
                );
                await this.actionService.doAction(actionData, {
                    onClose: () => this.model.fetchData(),
                });
                return;
            }
            if (action.key === "flip_event") {
                await this.orm.call(
                    "mdl.attendance.device.event",
                    "timeline_flip_event",
                    [action.event_id]
                );
                this.notificationService.add(_t("סוג אירוע הנוכחות עודכן."), {
                    type: "success",
                });
            } else if (action.key === "dismiss_event") {
                await this.orm.call(
                    "mdl.attendance.device.event",
                    "timeline_dismiss_event",
                    [action.event_id]
                );
            } else if (action.key === "dismiss_pair") {
                await this.orm.call(
                    "mdl.attendance.device.event",
                    "timeline_dismiss_pair",
                    [action.event_ids]
                );
            }
            await this.model.fetchData();
        } catch (error) {
            const message = error.data?.message || error.message || _t("הפעולה נכשלה.");
            this.notificationService.add(message, { type: "danger", sticky: true });
        }
    }

    _notifyResult(result, successMessage) {
        if (result?.ok === false) {
            this.notificationService.add(result.message, { type: "danger", sticky: true });
        } else {
            this.notificationService.add(successMessage, { type: "success" });
        }
    }
}

export const attendanceConflictGanttView = {
    ...attendanceGanttView,
    Model: AttendanceConflictGanttModel,
    Renderer: AttendanceConflictGanttRenderer,
};

registry.category("views").add("attendance_conflict_gantt", attendanceConflictGanttView);
