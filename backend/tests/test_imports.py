"""CSV import: rows are read or rejected with a reason, and uploaded evidence is never altered or invented."""

import csv
import io
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import EvidenceRecord
from app.services import imports
from tests.test_api import login, wait

DATA = Path(__file__).parents[2] / "docs" / "datasets" / "tallowmere-synthetic"

SIGNINS = """Date (UTC),Request ID,Username,Application,Status,Authentication Requirement
2026-03-02T10:00:00Z,r1,Ana@corp.example,ERP,Success,Multifactor authentication
2026-03-02T11:00:00Z,r2,ben@corp.example,ERP,Interrupted,Multifactor authentication
2026-03-02 12:00:00,r3,cal@corp.example,ERP,Success,Multifactor authentication
03/02/2026 12:30,r4,dee@corp.example,ERP,Success,Multifactor authentication
2026-03-02T13:00:00+08:00,,eli@corp.example,ERP,Success,Multifactor authentication
"""


def create(client, label="Test upload", data_class="real"):
    response = client.post("/api/v1/imports", json={"label": label, "data_class": data_class})
    assert response.status_code == 201, response.text
    return response.json()["key"]


def upload(client, key, name, content):
    body = content if isinstance(content, bytes) else content.encode()
    return client.post(f"/api/v1/imports/{key}/files?name={name}", content=body)


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_kind_and_columns_are_recognized_from_the_header():
    kind, mapping = imports.suggest(["Date (UTC)", "Request ID", "Username", "Application", "Status", "MFA"])
    assert kind == "signin_logs"
    assert mapping["user"] == "Username"
    assert imports.suggest(["Colour", "Shape"]) == (None, {})


def test_unreadable_rows_are_rejected_with_a_reason_and_never_guessed(client):
    login(client)
    key = create(client)
    file = upload(client, key, "signins.csv", SIGNINS).json()
    assert file["kind"] == "signin_logs"
    assert file["total_rows"] == 5
    assert file["accepted"] == 1
    reasons = {r["reason"] for r in file["reasons"]}
    assert 'Status "Interrupted" isn\'t recognized' in reasons
    assert "A timestamp has no time zone, and none was chosen for this file" in reasons
    assert "A timestamp isn't in ISO 8601 format" in reasons
    assert "Session ID is empty" in reasons
    assert file["samples"][0]["row"] == 3


def test_choosing_a_time_zone_reads_local_timestamps_in_that_zone(client):
    login(client)
    key = create(client)
    file = upload(client, key, "signins.csv", SIGNINS).json()
    updated = client.put(
        f"/api/v1/imports/{key}/files/{file['id']}",
        json={"kind": file["kind"], "mapping": file["mapping"], "timezone": "Asia/Manila"},
    ).json()
    assert updated["accepted"] == 2
    converted = imports.convert_row(
        imports.KINDS["signin_logs"], rows(SIGNINS)[2], updated["mapping"], imports._zone("Asia/Manila")
    )
    assert converted["ts"].isoformat() == "2026-03-02T04:00:00+00:00"


def test_commit_needs_consent_to_drop_rejected_rows_and_keeps_provenance(client, db):
    login(client)
    key = create(client)
    upload(client, key, "signins.csv", SIGNINS)
    refused = client.post(f"/api/v1/imports/{key}/commit", json={})
    assert refused.status_code == 422
    assert "rejected" in refused.json()["detail"]
    done = client.post(f"/api/v1/imports/{key}/commit", json={"accept_rejected": True}).json()
    assert done["status"] == "ready"
    assert done["summary"]["records"] == {"idp_auth": 1}
    assert set(done["summary"]["missing_sources"]) == {"edr", "network", "inventory", "coverage", "directory"}
    record = db.scalar(select(EvidenceRecord).where(EvidenceRecord.dataset == key))
    assert record.payload["user"] == "ana"
    assert record.payload["source_file"] == "signins.csv"
    assert record.payload["source_row"] == 2
    assert client.post(f"/api/v1/imports/{key}/files?name=more.csv", content=SIGNINS).status_code == 422
    assert client.delete(f"/api/v1/imports/{key}").status_code == 409


def test_the_same_file_cannot_be_added_twice_and_bad_files_are_refused(client):
    login(client)
    key = create(client)
    assert upload(client, key, "a.csv", SIGNINS).status_code == 201
    assert upload(client, key, "b.csv", SIGNINS).status_code == 422
    assert upload(client, key, "binary.csv", b"\x89PNG\xff\xfe\x00\x00").status_code == 422
    assert upload(client, key, "dupes.csv", "a,a\n1,2\n").status_code == 422
    assert upload(client, key, "empty.csv", b"").status_code == 422


def test_uploads_are_limited_to_managers_and_their_workspace(client):
    login(client, "mina@cobalt.example")
    assert client.post("/api/v1/imports", json={"label": "No", "data_class": "real"}).status_code == 403
    assert client.get("/api/v1/imports/options").status_code == 403
    login(client)
    assert client.get("/api/v1/imports/missing").status_code == 404


def test_flow_rows_for_one_host_and_hour_are_added_together(client, db):
    login(client)
    key = create(client)
    text = (
        "Timestamp,Hostname,Subnet,Bytes Out\n"
        "2026-03-02T10:05:00Z,web01.corp.example,DMZ,100\n"
        "2026-03-02T10:45:00Z,WEB01,DMZ,50\n"
        "2026-03-02T11:05:00Z,web01,DMZ,25\n"
    )
    upload(client, key, "flows.csv", text)
    client.post(f"/api/v1/imports/{key}/commit", json={})
    records = db.scalars(select(EvidenceRecord).where(EvidenceRecord.dataset == key).order_by(EvidenceRecord.ts)).all()
    assert [r.payload["bytes_out"] for r in records] == [150, 25]
    assert records[0].payload["hostname"] == "WEB01"
    assert records[0].payload["merged_rows"] == 2


def test_logons_without_a_session_column_are_matched_and_marked_as_inferred(client, db):
    login(client)
    key = create(client)
    upload(
        client,
        key,
        "signins.csv",
        "Date (UTC),Request ID,Username,Application,Status,MFA\n2026-03-02T10:00:00Z,r1,ana,erp,Success,true\n",
    )
    upload(
        client,
        key,
        "logons.csv",
        "TimeCreated,Computer,TargetUserName,LogonType\n"
        "2026-03-02T10:20:00Z,HOST1,CORP\\ana,2\n"
        "2026-03-02T12:00:00Z,HOST1,ana,2\n"
        "2026-03-02T10:20:00Z,HOST1,zed,10\n",
    )
    done = client.post(f"/api/v1/imports/{key}/commit", json={}).json()
    assert done["summary"]["sessions_inferred"] == 1
    logons = db.scalars(
        select(EvidenceRecord).where(EvidenceRecord.dataset == key, EvidenceRecord.source_key == "directory")
    ).all()
    matched = [r for r in logons if r.payload.get("idp_session_id")]
    assert len(matched) == 1
    assert matched[0].payload == {**matched[0].payload, "idp_session_id": "r1", "session_match": "inferred"}


def test_a_blank_value_in_a_mapped_session_column_stays_blank(client, db):
    login(client)
    key = create(client)
    upload(
        client,
        key,
        "signins.csv",
        "Date (UTC),Request ID,Username,Application,Status,MFA\n2026-03-02T10:00:00Z,r1,ana,erp,Success,true\n",
    )
    upload(
        client,
        key,
        "logons.csv",
        "TimeCreated,Computer,TargetUserName,LogonType,IdP Session ID\n2026-03-02T10:20:00Z,HOST1,ana,2,\n",
    )
    client.post(f"/api/v1/imports/{key}/commit", json={})
    logon = db.scalar(
        select(EvidenceRecord).where(EvidenceRecord.dataset == key, EvidenceRecord.source_key == "directory")
    )
    assert logon.payload["idp_session_id"] is None


def begin(client, key, claim="No unauthorized access occurred during the period.", **extra):
    sources = [s["key"] for s in client.get("/api/v1/investigations/options").json()["sources"]]
    body = {"claim": claim, "name": "Upload check", "dataset": key, "source_keys": sources[:6], **extra}
    return client.post("/api/v1/investigations", json=body)


def test_a_partial_upload_says_what_it_cannot_test_instead_of_passing(client):
    login(client)
    key = create(client)
    upload(
        client,
        key,
        "signins.csv",
        "Date (UTC),Request ID,Username,Application,Status,MFA\n2026-03-02T10:00:00Z,r1,ana,erp,Success,true\n",
    )
    client.post(f"/api/v1/imports/{key}/commit", json={})
    response = begin(client, key, window_hours=24)
    assert response.status_code == 201, response.text
    detail = wait(client, response.json()["id"])
    assert detail["status"] != "failed", detail["error"]
    assert detail["assessment"] != "SUPPORTED"
    assert detail["scope"]["window_label"] == "All 1 hour of the dataset"
    assert any("no records from this source" in text for text in detail["limitations"])


def test_investigation_periods_must_fit_the_dataset_on_whole_hours(client):
    login(client)
    period = {"window_start": "2026-10-29T10:00:00Z", "window_end": "2026-10-29T14:00:00Z"}
    created = begin(client, "A", **period)
    assert created.status_code == 201, created.text
    assert wait(client, created.json()["id"])["scope"]["window_label"] == "Custom period"
    assert begin(client, "A", window_start="2026-10-29T10:30:00Z", window_end="2026-10-29T14:00:00Z").status_code == 422
    assert begin(client, "A", window_start="2020-01-01T00:00:00Z", window_end="2020-01-02T00:00:00Z").status_code == 422
    assert begin(client, "A", window_start="2026-10-29T14:00:00Z", window_end="2026-10-29T10:00:00Z").status_code == 422
    assert begin(client, "A", window_start="2026-10-29T10:00:00Z").status_code == 422
    assert begin(client, "missing").status_code == 422


def load_snapshot(client, letter):
    key = create(client, f"Tallowmere {letter}", "synthetic")
    folder = DATA / f"snapshot-{letter}"
    for path in [DATA / "asset_register.csv", *sorted(folder.glob("*.csv"))]:
        file = upload(client, key, path.name, path.read_bytes())
        assert file.status_code == 201, file.text
        body = file.json()
        assert body["ready"], (path.name, body["missing"])
        assert body["rejected"] == 0, (path.name, body["reasons"])
    done = client.post(f"/api/v1/imports/{key}/commit", json={})
    assert done.status_code == 200, done.text
    return key, done.json()


def test_tallowmere_files_are_recognized_and_cover_the_expected_period(client, db):
    login(client)
    key, done = load_snapshot(client, "G")
    assert done["summary"]["missing_sources"] == []
    assert done["summary"]["sessions_inferred"] == 0
    assert done["window_start"].startswith("2026-10-26T09:00:00")
    assert done["window_end"].startswith("2026-10-30T09:00:00")
    assert db.scalar(select(func.count()).where(EvidenceRecord.dataset == key)) == done["summary"]["total"]


@pytest.mark.parametrize(
    ("letter", "claim", "expected"),
    [
        ("E", "No unauthorized access occurred during the month-end close.", "CONTRADICTED"),
        ("F", "No unauthorized access occurred during the month-end close.", "SUPPORTED"),
    ],
)
def test_uploaded_evidence_reaches_the_same_conclusion(client, letter, claim, expected):
    login(client)
    key, _ = load_snapshot(client, letter)
    detail = wait(client, begin(client, key, claim).json()["id"])
    while detail["status"] == "awaiting_approval":
        ids = [c["id"] for c in detail["checks"] if c["status"] == "proposed"]
        client.post(
            f"/api/v1/investigations/{detail['id']}/checks/approve", json={"check_ids": ids, "acknowledged": True}
        )
        detail = wait(client, detail["id"])
    assert detail["assessment"] == expected
    assert detail["dataset_origin"] == "upload"
    assert detail["data_class"] == "synthetic"


def test_uploaded_evidence_cannot_receive_simulated_records(client, db):
    login(client)
    key, _ = load_snapshot(client, "E")
    detail = wait(client, begin(client, key).json()["id"])
    while detail["status"] == "awaiting_approval":
        ids = [c["id"] for c in detail["checks"] if c["status"] == "proposed"]
        client.post(
            f"/api/v1/investigations/{detail['id']}/checks/approve", json={"check_ids": ids, "acknowledged": True}
        )
        detail = wait(client, detail["id"])
    remediation = detail["remediations"][0]
    assert remediation["can_execute"] is False
    assert remediation["can_simulate_recurrence"] is False
    assert client.post(f"/api/v1/assurance/remediations/{remediation['id']}/approve", json={}).status_code == 200
    before = db.scalar(select(func.count()).where(EvidenceRecord.dataset == key))
    refused = client.post(f"/api/v1/assurance/remediations/{remediation['id']}/execute", json={"confirmed": True})
    assert refused.status_code == 409
    assert "upload a new export" in refused.json()["detail"]
    assert db.scalar(select(func.count()).where(EvidenceRecord.dataset == key)) == before


def test_a_report_on_real_evidence_does_not_claim_to_be_synthetic(client):
    login(client)
    key = create(client, "Real export", "real")
    upload(
        client,
        key,
        "signins.csv",
        "Date (UTC),Request ID,Username,Application,Status,MFA\n2026-03-02T10:00:00Z,r1,ana,erp,Success,true\n",
    )
    client.post(f"/api/v1/imports/{key}/commit", json={})
    detail = wait(client, begin(client, key).json()["id"])
    assert detail["data_class"] == "real"
    while detail["status"] == "awaiting_approval":
        ids = [c["id"] for c in detail["checks"] if c["status"] == "proposed"]
        if not ids:
            break
        client.post(
            f"/api/v1/investigations/{detail['id']}/checks/approve", json={"check_ids": ids, "acknowledged": True}
        )
        detail = wait(client, detail["id"])
    report = client.post("/api/v1/reports", json={"investigation_id": detail["id"]})
    assert report.status_code == 201, report.text
    snapshot = client.get(f"/api/v1/reports/{report.json()['id']}").json()["snapshot"]
    assert "ynthetic" not in snapshot["demo_notice"]
    assert snapshot["scope"]["data_class"] == "real"


def test_real_evidence_stays_off_the_model_without_consent():
    from app.reasoning.factory import ProviderChoice, for_evidence

    live = ProviderChoice(object(), "meta:muse-spark-1.3", "ran on the model")
    assert for_evidence(live, "synthetic", True, "muse-spark-1.3") is live
    assert for_evidence(live, "real", True, "muse-spark-1.3") is live
    assert for_evidence(live, "real", False, "muse-spark-1.3").mode == "deterministic"
    contributor = for_evidence(live, "real", True, "muse-spark-1.3-contributor")
    assert contributor.mode == "deterministic"
    assert "never sent" in contributor.note


def test_one_late_record_does_not_invent_an_empty_hour(client):
    login(client)
    key = create(client)
    upload(
        client,
        key,
        "signins.csv",
        "Date (UTC),Request ID,Username,Application,Status,MFA\n2026-03-02T10:30:00Z,r1,ana,erp,Success,true\n",
    )
    upload(client, key, "flows.csv", "Timestamp,Hostname,Subnet,Bytes Out\n2026-03-02T10:00:00Z,WEB01,DMZ,100\n")
    upload(
        client,
        key,
        "logons.csv",
        "TimeCreated,Computer,TargetUserName,LogonType,IdP Session ID\n2026-03-02T11:00:04Z,WEB01,ana,2,r1\n",
    )
    done = client.post(f"/api/v1/imports/{key}/commit", json={}).json()
    assert done["window_end"].startswith("2026-03-02T11:00:00")


def test_simultaneous_requests_get_different_references(seeded):
    from concurrent.futures import ThreadPoolExecutor

    from app.db import SessionLocal
    from app.models import Investigation, User
    from app.services.refs import next_ref

    def create(number):
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.role == "admin"))
            investigation = Investigation(
                workspace_id=user.workspace_id,
                ref=next_ref(db, Investigation, "INV"),
                name=f"Race {number}",
                claim_text="No unauthorized access occurred.",
                dataset="A",
                scope={"window_start": "2026-10-29T09:00:00+00:00", "window_end": "2026-10-30T09:00:00+00:00"},
                source_keys=[],
                created_by_id=user.id,
                assignee_id=user.id,
            )
            db.add(investigation)
            db.commit()
            return investigation.ref

    with ThreadPoolExecutor(max_workers=6) as pool:
        created = list(pool.map(create, range(12)))
    assert len(set(created)) == 12


def test_missing_baselines_are_reported_instead_of_flagging_every_hour(client):
    login(client)
    key = create(client)
    lines = ["Date (UTC),Request ID,Username,Application,Status,MFA"]
    for hour in range(10, 22):
        lines.append(f"2026-03-02T{hour}:00:00Z,r{hour},ana,erp,Failure,true")
    upload(client, key, "signins.csv", "\n".join(lines) + "\n")
    client.post(f"/api/v1/imports/{key}/commit", json={})
    detail = wait(client, begin(client, key, window_hours=6).json()["id"])
    anomaly = next((e for e in detail["evidence"] if e.get("observable") == "idp_auth_anomaly"), None)
    assert anomaly is None or "no baseline" in anomaly["observation"]
