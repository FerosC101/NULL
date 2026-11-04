"""CSV evidence import. Files are kept as received, and rows that can't be read are rejected with a reason.

Nothing is guessed. A timestamp with no time zone, a status NULL can't interpret or a missing required
value rejects that row, and the person importing sees how many rows and why before anything is committed.
"""

import csv
import hashlib
import io
import json
import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, ImportFile, User
from app.services.sources import ALL_SOURCE_KEYS

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_VALUE = 500
SAMPLE_REJECTIONS = 20
PREVIEW_ROWS = 3
# How close a sign-in must come before a logon for the logon to be attributed to it.
SESSION_MATCH_WINDOW = timedelta(hours=1)

_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_SUCCESS = {"success", "succeeded", "successful", "allow", "allowed", "ok", "0"}
_FAILURE = {"failure", "failed", "fail", "deny", "denied", "blocked", "error"}
_TRUE = {"true", "yes", "y", "1", "on", "enabled"}
_FALSE = {"false", "no", "n", "0", "off", "disabled"}
_MFA_TRUE = {"mfa", "multifactor", "multi-factor", "satisfied", "mfa requirement satisfied by claim in the token"}
_MFA_FALSE = {"none", "singlefactor", "single-factor", "not required", "notapplied", "not applied"}
_LOGON_TYPES = {
    "2": "interactive",
    "3": "network",
    "4": "batch",
    "5": "service",
    "7": "unlock",
    "10": "remote_interactive",
    "11": "cached_interactive",
}


class Reject(Exception):
    """A row NULL can't read. The message is shown to the person importing."""


class ImportProblem(Exception):
    """A file or commit that can't go ahead."""


def _text(raw: str, zone) -> str:
    if len(raw) > MAX_VALUE:
        raise Reject(f"A value is longer than {MAX_VALUE} characters")
    return raw


def _time(raw: str, zone) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise Reject("A timestamp isn't in ISO 8601 format") from None
    if value.tzinfo is None:
        if zone is None:
            raise Reject("A timestamp has no time zone, and none was chosen for this file")
        value = value.replace(tzinfo=zone)
    return value.astimezone(UTC)


def _host(raw: str, zone) -> str:
    """Systems disagree on case and domain suffix, so hosts are joined on their short upper-case name."""
    value = _text(raw, zone)
    return value if _IPV4.match(value) else value.split(".")[0].upper()


def _user(raw: str, zone) -> str:
    return _text(raw, zone).split("\\")[-1].split("@")[0].lower()


def _count(raw: str, zone) -> int:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        raise Reject("A number can't be read") from None
    if value < 0:
        raise Reject("A number is negative")
    return int(value)


def _flag(raw: str, zone) -> bool:
    value = raw.lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise Reject(f'"{raw[:40]}" isn\'t a yes or no value')


def _result(raw: str, zone) -> str:
    value = raw.lower()
    if value in _SUCCESS:
        return "success"
    if value in _FAILURE:
        return "failure"
    raise Reject(f'Status "{raw[:40]}" isn\'t recognized')


def _mfa(raw: str, zone) -> bool:
    value = raw.lower()
    if value.startswith("multi") or value in _TRUE or value in _MFA_TRUE:
        return True
    if value.startswith("single") or value in _FALSE or value in _MFA_FALSE:
        return False
    raise Reject(f'MFA value "{raw[:40]}" isn\'t recognized')


def _lower(raw: str, zone) -> str:
    return _text(raw, zone).lower()


def _logon_type(raw: str, zone) -> str:
    return _LOGON_TYPES.get(raw, _text(raw, zone).lower().replace(" ", "_"))


def _hosts(raw: str, zone) -> list[str]:
    return [_host(part.strip(), zone) for part in re.split(r"[;,]", raw) if part.strip()]


def _iso(raw: str, zone) -> str:
    return _time(raw, zone).isoformat()


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    convert: Callable = _text
    required: bool = True
    aliases: tuple[str, ...] = ()
    default: Any = None


@dataclass(frozen=True)
class FileKind:
    key: str
    label: str
    source: str
    entity: str
    columns: tuple[Column, ...]
    static: dict = field(default_factory=dict)
    # A point-in-time list, such as an asset register. It may have no time of its own.
    snapshot: bool = False
    # Ongoing activity, which sets the period the dataset covers.
    series: bool = True
    # Logged around the clock, so a missing hour means something.
    continuous: bool = False


TIME_ALIASES = (
    "date (utc)",
    "date",
    "timestamp",
    "timestamp (utc)",
    "time",
    "time (utc)",
    "published",
    "createdDateTime",
)
SESSION_ALIASES = ("idp session id", "idp_session_id", "session id", "session_id")
CHANGE_ALIASES = ("change ref", "change_ref", "change", "ticket")

KINDS: dict[str, FileKind] = {
    kind.key: kind
    for kind in [
        FileKind(
            "signin_logs",
            "Sign-in logs",
            "idp_auth",
            "user",
            (
                Column("ts", "Time", _time, aliases=TIME_ALIASES),
                Column(
                    "user",
                    "User",
                    _user,
                    aliases=("username", "user", "user principal name", "actor.alternateid", "userprincipalname"),
                ),
                Column(
                    "result",
                    "Result",
                    _result,
                    aliases=("status", "result", "outcome.result", "outcome"),
                ),
                Column(
                    "app",
                    "Application",
                    _lower,
                    aliases=("application", "app", "app display name", "appdisplayname", "target.displayname"),
                ),
                Column(
                    "mfa",
                    "MFA step",
                    _mfa,
                    aliases=(
                        "authentication requirement",
                        "authenticationrequirement",
                        "mfa",
                        "mfa result",
                        "multifactor authentication result",
                    ),
                ),
                Column(
                    "session_id",
                    "Session ID",
                    aliases=(
                        "request id",
                        "correlation id",
                        "requestid",
                        "correlationid",
                        "session id",
                        "authenticationcontext.externalsessionid",
                        "uuid",
                    ),
                ),
                Column(
                    "src_ip",
                    "Source IP",
                    required=False,
                    aliases=("ip address", "ip", "ipaddress", "client.ipaddress", "source ip"),
                ),
                Column(
                    "geo",
                    "Location",
                    required=False,
                    aliases=("location", "geo", "client.geographicalcontext.country"),
                ),
            ),
            continuous=True,
        ),
        FileKind(
            "network_flows",
            "Network flows",
            "network",
            "hostname",
            (
                Column("ts", "Time", _time, aliases=("hour start (utc)", "hour start", *TIME_ALIASES)),
                Column("hostname", "Host", _host, aliases=("hostname", "host", "computer", "device", "source host")),
                Column("subnet", "Subnet", aliases=("subnet", "network", "vlan", "segment")),
                Column("bytes_out", "Bytes out", _count, aliases=("bytes out", "bytes_out", "bytes sent", "out bytes")),
                Column("flows", "Flow count", _count, required=False, aliases=("flow count", "flows", "connections")),
            ),
            continuous=True,
        ),
        FileKind(
            "endpoint_events",
            "Endpoint events",
            "edr",
            "hostname",
            (
                Column("ts", "Time", _time, aliases=TIME_ALIASES),
                Column("hostname", "Host", _host, aliases=("hostname", "host", "computer", "device", "device name")),
                Column("event", "Event type", _lower, aliases=("event type", "event", "type")),
                Column("events", "Event count", _count, required=False, aliases=("event count", "events", "count")),
                Column("severity", "Severity", _lower, required=False, aliases=("severity", "level")),
                Column("rule", "Rule", required=False, aliases=("rule", "detection", "alert name", "title")),
                Column("disposition", "Disposition", _lower, required=False, aliases=("disposition", "status")),
            ),
        ),
        FileKind(
            "endpoint_agents",
            "Endpoint agents",
            "coverage",
            "hostname",
            (
                Column(
                    "ts",
                    "Snapshot time",
                    _time,
                    required=False,
                    aliases=("snapshot time (utc)", "snapshot time", "exported at"),
                ),
                Column("hostname", "Host", _host, aliases=("hostname", "host", "computer", "device", "device name")),
                Column(
                    "last_heartbeat",
                    "Last heartbeat",
                    _iso,
                    aliases=("last heartbeat (utc)", "last heartbeat", "last seen", "last check-in", "last contact"),
                ),
                Column(
                    "agent_state",
                    "Agent state",
                    _lower,
                    required=False,
                    aliases=("agent state", "state", "enrollment"),
                    default="enrolled",
                ),
                Column(
                    "agent_version",
                    "Agent version",
                    required=False,
                    aliases=("agent version", "version", "sensor version"),
                ),
            ),
            snapshot=True,
            series=False,
        ),
        FileKind(
            "asset_register",
            "Asset register",
            "inventory",
            "hostname",
            (
                Column(
                    "ts",
                    "Recorded at",
                    _time,
                    required=False,
                    aliases=("recorded at (utc)", "recorded at", "exported at"),
                ),
                Column("hostname", "Host", _host, aliases=("hostname", "host", "computer", "device", "asset name")),
                Column(
                    "asset_class",
                    "Asset class",
                    _lower,
                    required=False,
                    aliases=("asset class", "class", "asset type", "type"),
                    default="unclassified",
                ),
                Column("team", "Team", required=False, aliases=("team", "owner", "department")),
                Column("site", "Site", required=False, aliases=("site", "location")),
                Column("criticality", "Criticality", _lower, required=False, aliases=("criticality", "tier")),
                Column("subnet", "Subnet", required=False, aliases=("subnet", "network")),
                Column("in_scope", "In scope", _flag, required=False, aliases=("in scope", "in_scope"), default=True),
            ),
            snapshot=True,
            series=False,
        ),
        FileKind(
            "windows_logons",
            "Windows logons",
            "directory",
            "user",
            (
                Column("ts", "Time", _time, aliases=("timecreated (utc)", "timecreated", *TIME_ALIASES)),
                Column("hostname", "Host", _host, aliases=("computer", "hostname", "host", "workstation")),
                Column("user", "User", _user, aliases=("targetusername", "user", "account", "username")),
                Column("logon_type", "Logon type", _logon_type, aliases=("logontype", "logon type")),
                Column("src_ip", "Source IP", required=False, aliases=("ipaddress", "ip address", "source ip")),
                Column("event_id", "Event ID", required=False, aliases=("eventid", "event id")),
                Column("idp_session_id", "IdP session", required=False, aliases=SESSION_ALIASES),
                Column("change_ref", "Change reference", required=False, aliases=CHANGE_ALIASES),
            ),
            static={"kind": "dc_logon"},
        ),
        FileKind(
            "vpn_sessions",
            "VPN sessions",
            "directory",
            "user",
            (
                Column("ts", "Time", _time, aliases=("start time (utc)", "start time", *TIME_ALIASES)),
                Column("user", "User", _user, aliases=("username", "user", "account")),
                Column("src_ip", "Source IP", aliases=("source ip", "src_ip", "client ip", "public ip")),
                Column("src_asn", "Source ASN", required=False, aliases=("source asn", "src_asn", "asn")),
                Column(
                    "assigned_ip", "Assigned IP", required=False, aliases=("assigned ip", "assigned_ip", "tunnel ip")
                ),
                Column("idp_session_id", "IdP session", required=False, aliases=SESSION_ALIASES),
                Column("change_ref", "Change reference", required=False, aliases=CHANGE_ALIASES),
            ),
            static={"kind": "vpn_session"},
        ),
        FileKind(
            "change_tickets",
            "Change tickets",
            "directory",
            "change_ref",
            (
                Column("ts", "Logged at", _time, aliases=("logged at (utc)", "logged at", "created", "opened at")),
                Column("change_ref", "Ticket", aliases=("ticket", "change ref", "number", "change number")),
                Column("hostnames", "Hosts", _hosts, aliases=("hosts", "hostnames", "affected hosts", "ci")),
                Column(
                    "window_start",
                    "Window start",
                    _iso,
                    aliases=("window start (utc)", "window start", "planned start", "start date"),
                ),
                Column(
                    "window_end",
                    "Window end",
                    _iso,
                    aliases=("window end (utc)", "window end", "planned end", "end date"),
                ),
                Column("approved_by", "Approved by", required=False, aliases=("approved by", "approver")),
                Column("summary", "Summary", required=False, aliases=("summary", "short description", "description")),
            ),
            static={"kind": "change_record"},
            series=False,
        ),
        FileKind(
            "log_forwarding",
            "Log forwarding",
            "directory",
            "hostname",
            (
                Column(
                    "ts",
                    "Checked at",
                    _time,
                    required=False,
                    aliases=("checked at (utc)", "checked at", "exported at"),
                ),
                Column("hostname", "Host", _host, aliases=("hostname", "host", "computer", "device")),
                Column("forwarding", "Forwarding", _flag, aliases=("forwarding", "forwarding enabled", "enabled")),
            ),
            static={"kind": "log_coverage"},
            snapshot=True,
            series=False,
        ),
    ]
}


def _normal(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def suggest(headers: list[str]) -> tuple[str | None, dict[str, str]]:
    """The file kind whose required columns all match, and the mapping that matched."""
    best: tuple[int, str | None, dict[str, str]] = (0, None, {})
    lookup = {_normal(h): h for h in reversed(headers)}
    for kind in KINDS.values():
        mapping = mapping_for(kind, lookup)
        required = [c for c in kind.columns if c.required]
        if all(c.name in mapping for c in required) and len(mapping) > best[0]:
            best = (len(mapping), kind.key, mapping)
    return best[1], best[2]


def mapping_for(kind: FileKind, lookup: dict[str, str]) -> dict[str, str]:
    mapping = {}
    for column in kind.columns:
        header = next((lookup[_normal(a)] for a in column.aliases if _normal(a) in lookup), None)
        if header:
            mapping[column.name] = header
    return mapping


def read_table(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = content.decode("utf-16")
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ImportProblem("This file isn't UTF-8 or UTF-16 text.") from None
    first = text.split("\n", 1)[0]
    if not first.strip():
        raise ImportProblem("This file has no header row.")
    delimiter = max(",;\t", key=first.count)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
        headers = [h.strip() for h in reader.fieldnames or []]
        reader.fieldnames = headers
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ImportProblem(f"This file has more than {MAX_ROWS:,} rows. Split it and upload the parts.")
    except csv.Error as exc:
        raise ImportProblem(f"This file can't be read as CSV: {exc}") from None
    if len(set(headers)) != len(headers):
        raise ImportProblem("Two columns in this file have the same name.")
    return headers, rows


def _zone(name: str | None):
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ImportProblem(f"{name} isn't a known time zone.") from None


def convert_row(kind: FileKind, row: dict[str, str], mapping: dict[str, str], zone) -> dict:
    values: dict[str, Any] = {}
    for column in kind.columns:
        header = mapping.get(column.name)
        raw = (row.get(header) or "").strip() if header else ""
        if raw:
            values[column.name] = column.convert(raw, zone)
        elif column.required:
            raise Reject(f"{column.label} is empty")
        else:
            values[column.name] = column.default
    if kind.key == "endpoint_events":
        values["event"] = "detection" if values["event"] in ("detection", "alert") else "telemetry_batch"
        if values["event"] == "detection" and not values["severity"]:
            raise Reject("A detection has no severity")
    if kind.key == "windows_logons" and values.pop("event_id") not in (None, "4624"):
        raise Reject("This event isn't a successful logon (4624)")
    if kind.key == "change_tickets" and not values["hostnames"]:
        raise Reject("Hosts is empty")
    return values


def parse(file: ImportFile) -> tuple[list[dict], dict]:
    """Every readable row of a file, and the report shown before anything is committed."""
    kind = KINDS.get(file.kind or "")
    headers, rows = read_table(file.content)
    report: dict[str, Any] = {
        "columns": headers,
        "preview": [{h: (row.get(h) or "")[:80] for h in headers} for row in rows[:PREVIEW_ROWS]],
        "total_rows": len(rows),
        "accepted": 0,
        "rejected": 0,
        "reasons": [],
        "samples": [],
        "missing": [],
        "notes": [],
    }
    if kind is None:
        return [], report
    report["missing"] = [c.label for c in kind.columns if c.required and c.name not in file.mapping]
    if report["missing"]:
        return [], report
    zone = _zone(file.timezone)
    accepted, reasons, samples = [], Counter(), []
    for number, row in enumerate(rows, start=2):
        try:
            values = convert_row(kind, row, file.mapping, zone)
        except Reject as exc:
            reasons[str(exc)] += 1
            if len(samples) < SAMPLE_REJECTIONS:
                samples.append({"row": number, "reason": str(exc)})
            continue
        values["source_row"] = number
        accepted.append(values)
    report |= {
        "accepted": len(accepted),
        "rejected": sum(reasons.values()),
        "reasons": [{"reason": r, "count": c} for r, c in reasons.most_common()],
        "samples": samples,
    }
    if kind.key in ("windows_logons", "vpn_sessions") and "idp_session_id" not in file.mapping:
        report["notes"].append(
            f"No session column is mapped, so each logon will be matched to the same user's sign-in in the "
            f"{int(SESSION_MATCH_WINDOW.total_seconds() // 60)} minutes before it."
        )
    if kind.key == "network_flows":
        report["notes"].append("Rows for the same host and hour are added together.")
    return accepted, report


def add_file(db: Session, dataset: Dataset, name: str, content: bytes) -> ImportFile:
    if dataset.status != "draft":
        raise ImportProblem("This upload is already committed. Start a new one to add files.")
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalars(select(ImportFile).where(ImportFile.dataset_key == dataset.key)).all()
    if any(f.sha256 == digest for f in existing):
        raise ImportProblem("This file is already in this upload.")
    headers, _ = read_table(content)
    kind, mapping = suggest(headers)
    file = ImportFile(
        dataset_key=dataset.key, name=name[:255], sha256=digest, content=content, kind=kind, mapping=mapping
    )
    _, file.report = parse(file)
    db.add(file)
    return file


def update_file(file: ImportFile, kind: str | None, mapping: dict[str, str], timezone: str | None) -> None:
    if kind is not None and kind not in KINDS:
        raise ImportProblem("Unknown file type.")
    headers, _ = read_table(file.content)
    known = {c.name for c in KINDS[kind].columns} if kind else set()
    file.kind = kind
    file.mapping = {k: v for k, v in mapping.items() if k in known and v in headers}
    file.timezone = timezone or None
    _, file.report = parse(file)


def file_out(file: ImportFile) -> dict:
    kind = KINDS.get(file.kind or "")
    report = file.report or {}
    return {
        "id": file.id,
        "name": file.name,
        "size": len(file.content),
        "kind": file.kind,
        "kind_label": kind.label if kind else None,
        "source": kind.source if kind else None,
        "mapping": file.mapping,
        "timezone": file.timezone,
        **report,
        "ready": bool(kind and not report.get("missing") and report.get("accepted")),
    }


def options() -> list[dict]:
    return [
        {
            "key": kind.key,
            "label": kind.label,
            "source": kind.source,
            "columns": [{"name": c.name, "label": c.label, "required": c.required} for c in kind.columns],
        }
        for kind in KINDS.values()
    ]


def _merge_flows(rows: list[dict]) -> list[dict]:
    """The tests read one row per host per hour, while a flow export holds one row per connection."""
    merged: dict[tuple, dict] = {}
    for row in rows:
        hour = row["ts"].replace(minute=0, second=0, microsecond=0)
        current = merged.get((row["hostname"], hour))
        if current is None:
            merged[(row["hostname"], hour)] = {**row, "ts": hour}
        else:
            current["bytes_out"] += row["bytes_out"]
            if row["flows"] is not None:
                current["flows"] = (current["flows"] or 0) + row["flows"]
            current["merged_rows"] = current.get("merged_rows", 1) + 1
    return list(merged.values())


def _match_sessions(logons: list[dict], signins: list[dict]) -> int:
    """Attribute logons to a sign-in when the export has no session column. Each match is marked as inferred."""
    by_user: dict[str, list[tuple[datetime, str]]] = {}
    for row in signins:
        if row["result"] == "success":
            by_user.setdefault(row["user"], []).append((row["ts"], row["session_id"]))
    for times in by_user.values():
        times.sort()
    matched = 0
    for row in logons:
        times = by_user.get(row["user"], [])
        index = bisect_right(times, (row["ts"], chr(0x10FFFF)))
        if index and row["ts"] - times[index - 1][0] <= SESSION_MATCH_WINDOW:
            row["idp_session_id"] = times[index - 1][1]
            row["session_match"] = "inferred"
            matched += 1
    return matched


def _period_end(parsed: list[tuple], dated: list[datetime]) -> datetime:
    """The end of the last hour every continuous log reaches, so one late record can't invent an empty hour."""
    lasts = [max(row["ts"] for row in rows) for _, kind, rows in parsed if kind.continuous]
    last = min(lasts) if lasts else max(dated)
    return last.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def commit(db: Session, dataset: Dataset, user: User, accept_rejected: bool) -> dict:
    """Write every accepted row as evidence in one transaction. The records can't change afterwards."""
    if dataset.status != "draft":
        raise ImportProblem("This upload is already committed.")
    files = db.scalars(select(ImportFile).where(ImportFile.dataset_key == dataset.key)).all()
    if not files:
        raise ImportProblem("Add at least one file first.")
    parsed: list[tuple[ImportFile, FileKind, list[dict]]] = []
    for file in files:
        rows, report = parse(file)
        kind = KINDS.get(file.kind or "")
        if kind is None:
            raise ImportProblem(f"Choose a file type for {file.name}.")
        if report["missing"]:
            raise ImportProblem(f"{file.name} still needs: {', '.join(report['missing'])}.")
        if not rows:
            raise ImportProblem(f"No row in {file.name} could be read.")
        if report["rejected"] and not accept_rejected:
            raise ImportProblem("Some rows were rejected. Confirm you want to continue without them.")
        parsed.append((file, kind, _merge_flows(rows) if kind.key == "network_flows" else rows))

    signins = [row for _, kind, rows in parsed if kind.key == "signin_logs" for row in rows]
    matched = sum(
        _match_sessions(rows, signins)
        for file, kind, rows in parsed
        if kind.key in ("windows_logons", "vpn_sessions") and "idp_session_id" not in file.mapping
    )
    series = [row["ts"] for _, kind, rows in parsed if kind.series for row in rows]
    dated = series + [row["ts"] for _, kind, rows in parsed if not kind.series for row in rows if row["ts"]]
    if not dated:
        raise ImportProblem("No file has timestamps, so NULL can't tell what period this covers.")
    end = _period_end(parsed, dated)
    start = min(series or dated).replace(minute=0, second=0, microsecond=0)

    counts: Counter = Counter()
    connection = db.connection().connection
    with connection.cursor() as cursor:
        columns = "(dataset, source_key, ts, entity, payload)"
        with cursor.copy(f"COPY evidence_records {columns} FROM STDIN") as copy:
            for file, kind, rows in parsed:
                for row in rows:
                    recorded = row.pop("ts")
                    ts = recorded or end
                    payload = {**row, **kind.static, "source_file": file.name}
                    if recorded is None:
                        payload["assumed_time"] = True
                    entity = str(payload.get(kind.entity) or "")
                    copy.write_row((dataset.key, kind.source, ts, entity, json.dumps(payload, default=str)))
                    counts[kind.source] += 1
    dataset.status = "ready"
    dataset.window_start, dataset.window_end = start, end
    dataset.summary = {
        **dataset.summary,
        "records": dict(counts),
        "total": sum(counts.values()),
        "sessions_inferred": matched,
        "missing_sources": [key for key in ALL_SOURCE_KEYS if key not in counts],
    }
    return dataset.summary


def new_key() -> str:
    return f"up-{token_hex(6)}"
