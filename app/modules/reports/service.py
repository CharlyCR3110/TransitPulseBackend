from datetime import UTC, datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.lib import seed_cache
from app.models.active_trip import ActiveTrip, ActiveTripStep
from app.models.report import Report
from app.models.report_reaction import ReportReaction
from app.models.user import User
from app.modules.reports.config import (
    CONFIRM_THRESHOLD,
    DEDUP_WINDOW_MINUTES,
    DISMISS_MARGIN,
    RATE_LIMIT_PER_HOUR,
    REPORT_CONFIRM_EXTENSION_MINUTES,
    compute_expires_at,
)
from app.modules.shared.exceptions import NotFoundError, ValidationAppError


class RateLimitExceeded(Exception):
    pass


class ReportExpired(Exception):
    pass


class ReportsService:
    def __init__(self, session: Session):
        self.session = session

    def submit(self, payload: dict, user: User | None, source_ip: str | None) -> dict:
        active_trip_id = payload["activeTripId"]
        report_type = payload["type"]
        description = payload.get("description", "")

        route_id, direction, stop_id, active_trip_pk = self._infer_route_context(
            active_trip_id
        )

        self._check_rate_limit(user, source_ip)

        dedup = self._find_dedup(route_id, direction, report_type)
        if dedup is not None:
            self._add_reaction(dedup, user, source_ip, "confirm", description or None)
            return self._report_out(dedup)

        now = datetime.now(UTC)
        report = Report(
            user_id=user.id if user is not None else None,
            route_id=route_id,
            direction=direction,
            stop_id=stop_id,
            active_trip_id=active_trip_pk,
            type=report_type,
            description=description,
            source_ip=source_ip,
            expires_at=compute_expires_at(report_type, now),
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return self._report_out(report)

    def list_active(
        self, route_id: str, direction: str | None = None
    ) -> list[dict]:
        now = datetime.now(UTC)
        query = (
            select(Report)
            .where(
                Report.route_id == route_id,
                Report.expires_at > now,
                Report.status.notin_(["resolved", "dismissed"]),
            )
            .order_by(Report.confirm_count.desc(), Report.created_at.desc())
        )
        if direction is not None:
            query = query.where(Report.direction == direction)

        reports = self.session.scalars(query).all()
        results = []
        for report in reports:
            out = self._report_out(report)
            out["latestDetail"] = self._latest_detail(report.id)
            results.append(out)
        return results

    def confirm(
        self,
        report_id: int,
        user: User | None,
        source_ip: str | None,
        detail: str | None,
    ) -> dict:
        report = self._get_active_report(report_id)
        self._add_reaction(report, user, source_ip, "confirm", detail)
        return self._report_out(report)

    def deny(
        self,
        report_id: int,
        user: User | None,
        source_ip: str | None,
    ) -> dict:
        report = self._get_active_report(report_id)
        self._add_reaction(report, user, source_ip, "deny", None)
        return self._report_out(report)

    def _infer_route_context(
        self, active_trip_id: str
    ) -> tuple[str, str, str | None, int]:
        active_trip = self.session.scalar(
            select(ActiveTrip).where(
                ActiveTrip.active_trip_id == active_trip_id,
                ActiveTrip.status == "in_progress",
            )
        )
        if active_trip is None:
            raise NotFoundError(
                "Active trip not found or not in progress",
                {"activeTripId": active_trip_id},
            )

        steps = self.session.scalars(
            select(ActiveTripStep)
            .where(ActiveTripStep.active_trip_id == active_trip.id)
            .order_by(ActiveTripStep.step_index)
        ).all()

        bus_step = None
        for step in steps:
            if step.kind == "bus" and step.step_index <= active_trip.current_step_index:
                bus_step = step
        if bus_step is None:
            for step in steps:
                if step.kind == "bus":
                    bus_step = step
                    break
        if bus_step is None:
            raise NotFoundError(
                "No bus step found on active trip",
                {"activeTripId": active_trip_id},
            )

        route_id = bus_step.route
        board_stop_id = bus_step.payload.get("boardStopId")

        cache = seed_cache.get_cache(self.session)
        direction = None
        for (rid, d), route_stops in cache.route_stops_by_route_dir.items():
            if rid != route_id:
                continue
            for rs in route_stops:
                if rs.stop_id == board_stop_id:
                    direction = d
                    break
            if direction is not None:
                break

        if direction is None:
            direction = "unknown"

        return route_id, direction, board_stop_id, active_trip.id

    def _check_rate_limit(self, user: User | None, source_ip: str | None) -> None:
        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        conditions = [Report.created_at > one_hour_ago]
        if user is not None:
            conditions.append(Report.user_id == user.id)
        elif source_ip is not None:
            conditions.append(Report.source_ip == source_ip)
        else:
            return

        count = self.session.scalar(select(func.count()).where(*conditions).select_from(Report))
        if count is not None and count >= RATE_LIMIT_PER_HOUR:
            raise RateLimitExceeded()

    def _find_dedup(
        self, route_id: str, direction: str, report_type: str
    ) -> Report | None:
        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=DEDUP_WINDOW_MINUTES)
        return self.session.scalar(
            select(Report)
            .where(
                Report.route_id == route_id,
                Report.direction == direction,
                Report.type == report_type,
                Report.expires_at > now,
                Report.created_at > window_start,
                Report.status.notin_(["resolved", "dismissed"]),
            )
            .order_by(Report.created_at.desc())
            .limit(1)
        )

    def _add_reaction(
        self,
        report: Report,
        user: User | None,
        source_ip: str | None,
        reaction: str,
        detail: str | None,
    ) -> None:
        existing = None
        if user is not None:
            existing = self.session.scalar(
                select(ReportReaction).where(
                    ReportReaction.report_id == report.id,
                    ReportReaction.user_id == user.id,
                )
            )
        elif source_ip is not None:
            existing = self.session.scalar(
                select(ReportReaction).where(
                    ReportReaction.report_id == report.id,
                    ReportReaction.user_id.is_(None),
                    ReportReaction.source_ip == source_ip,
                )
            )

        if existing is not None:
            existing.reaction = reaction
            existing.detail = detail
        else:
            self.session.add(
                ReportReaction(
                    report_id=report.id,
                    user_id=user.id if user is not None else None,
                    reaction=reaction,
                    detail=detail,
                    source_ip=source_ip,
                )
            )

        self.session.flush()
        self._recount(report)

        if reaction == "confirm":
            ext = REPORT_CONFIRM_EXTENSION_MINUTES.get(report.type, 15)
            report.expires_at = report.expires_at + timedelta(minutes=ext)
            if report.confirm_count >= CONFIRM_THRESHOLD and report.status == "new":
                report.status = "confirmed"

        if reaction == "deny":
            if report.deny_count > report.confirm_count + DISMISS_MARGIN:
                report.status = "dismissed"

        self.session.commit()
        self.session.refresh(report)

    def _recount(self, report: Report) -> None:
        report.confirm_count = self.session.scalar(
            select(func.count())
            .where(
                ReportReaction.report_id == report.id,
                ReportReaction.reaction == "confirm",
            )
            .select_from(ReportReaction)
        ) or 0
        report.deny_count = self.session.scalar(
            select(func.count())
            .where(
                ReportReaction.report_id == report.id,
                ReportReaction.reaction == "deny",
            )
            .select_from(ReportReaction)
        ) or 0

    def _get_active_report(self, report_id: int) -> Report:
        report = self.session.get(Report, report_id)
        if report is None:
            raise NotFoundError("Report not found", {"reportId": report_id})
        now = datetime.now(UTC)
        if report.expires_at is not None and report.expires_at < now:
            raise ReportExpired()
        return report

    def _latest_detail(self, report_id: int) -> str | None:
        return self.session.scalar(
            select(ReportReaction.detail)
            .where(
                ReportReaction.report_id == report_id,
                ReportReaction.reaction == "confirm",
                ReportReaction.detail.isnot(None),
            )
            .order_by(ReportReaction.created_at.desc())
            .limit(1)
        )

    @staticmethod
    def _report_out(report: Report) -> dict:
        return {
            "id": report.id,
            "userId": report.user_id,
            "routeId": report.route_id,
            "direction": report.direction,
            "stopId": report.stop_id,
            "type": report.type,
            "description": report.description,
            "status": report.status,
            "confirmCount": report.confirm_count,
            "denyCount": report.deny_count,
            "expiresAt": report.expires_at.isoformat() if report.expires_at else None,
            "createdAt": report.created_at.isoformat(),
        }
