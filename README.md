# NULL

**Question Deeper. Know Better.**

NULL is an evidence intelligence platform. Given a claim such as "no unauthorized access occurred", it tests whether the
evidence could ever have justified that conclusion, builds competing explanations, recommends the check that best
separates them, runs what a person approves, and tracks fixes until evidence shows they worked.

You can also upload exported logs as CSV files and investigate those, as described under [Uploading evidence](#uploading-evidence). The included demonstration uses synthetic data for a fictional company. It touches no real infrastructure.

## Run it

Needs Node 20+, [uv](https://docs.astral.sh/uv/) and PostgreSQL 14+.

```bash
cp .env.example .env     # set NULL_SECRET_KEY and NULL_DEMO_PASSWORD
createdb null_app
make setup
make seed
make dev                 # http://localhost:3000
```

Sign in as `ada@cobalt.example` with your `NULL_DEMO_PASSWORD`. If you left it empty, `make seed` prints a generated one.
Other accounts: `jonas@` (approver), `priya@` (investigator) and `mina@` (viewer), all at `cobalt.example`.

No local PostgreSQL? Run `docker compose up -d` and set
`NULL_DATABASE_URL=postgresql+psycopg://null:null_local_only@localhost/null_app`.

## The demonstration

Every investigation moves through seven stages: Claim, Evidence, Explanations, Tests, Findings, Actions, Verification.

1. Open **Security claim analysis** from Overview. Its claim is UNDERDETERMINED: EDR is silent, but 4 hosts aren't enrolled.
2. Open **Evidence** to see the coverage matrix, then **Explanations** to see which observations would separate them.
3. In **Tests**, select **Review Investigation**, then approve. Independent logs expose an unexplained logon and the claim
   becomes CONTRADICTED. In **Findings**, reveal the answer key to compare.
4. Open **Assurance**. Approve, execute and verify the agent enrollment. The first verification fails because one host
   never reported, so the action stays unresolved. Execute again and it passes.
5. Select **Simulate recurrence** and verify again to see the weakness caught.

Each snapshot has a different hidden outcome. The same claim on the same code gives a different conclusion:

| Snapshot | What actually happened | Conclusion |
|---|---|---|
| A | Intrusion on an unmonitored endpoint | CONTRADICTED |
| B | No intrusion, but two gateways have no evidence at all | PARTIALLY IDENTIFIED |
| C | No intrusion, complete coverage | SUPPORTED |
| D | Intrusion on a monitored endpoint, no EDR alert | CONTRADICTED |

## Uploading evidence

Open **Sources > Upload evidence**, say whether the data is real or synthetic, and add your CSV exports. NULL recognizes
each file type, shows how many rows it could read and why it rejected the rest, and only then writes evidence.

- **Formats:** sign-in logs, network flows, endpoint events and agents, asset register, Windows logons, VPN sessions,
  change tickets and log forwarding. Columns are matched by name and can be mapped by hand. Files must be UTF-8 or UTF-16
  and use ISO 8601 times.
- **Nothing is guessed.** A time with no time zone, an unknown status or a missing required value rejects the row until
  you pick a time zone or accept losing it. Files are kept as received, and each record names its file and row.
- **Records can't be changed once added.** The analysis engine reads them exactly as it reads the demo snapshots.
- **A missing source is reported, not passed.** Tests that need it are marked unavailable. So are comparisons with fewer
  than 24 hours of baseline before the period.
- **Real logs stay on your server by default.** They reach the Meta model only if you allow it for that upload, and never
  a Contributor model. Meta doesn't train on Standard model content, but its terms allow human review and name no fixed
  retention period. See its [data commitments](https://dev.meta.ai/legal/commitments).
- **NULL can't act on uploaded evidence.** It proposes corrective actions, but you make the change and upload a new export.
  Simulated execution is refused, so no made-up record can enter real evidence.

[docs/trying-real-logs.md](docs/trying-real-logs.md) walks through a first real export. Sample files are in
[docs/datasets/tallowmere-synthetic](docs/datasets/tallowmere-synthetic).

## How a conclusion is reached

The rule the system is built around: **a model can propose, but only deterministic code can decide.**

```
claim → compiler → realities (predictions over named observables)
                       ↓
raw records → analysis tools → observations → validator → assessment
                                                 ↓
                               information value ranks the next check → human approval
```

- **Observables** (`backend/app/analysis/observables.py`) are named questions answered from raw records with pandas,
  SciPy and statsmodels. Each result keeps its method, record IDs and a hash of those records.
- **Realities** (`analysis/templates.py`) declare what each explanation predicts for each observable.
- **The validator** (`analysis/validation.py`) compares predictions with observations and assigns the assessment.
- **Information value** is the mutual information between a check's outcome and the surviving realities, in bits. It uses
  a uniform prior and declared likelihoods, so it ranks checks and is not a probability of intrusion.
- **Remediations** (`services/remediation.py`) resolve only when a procedure finds the evidence in the records.
- **Lifecycle** (`services/lifecycle.py`) reads each stage's status, the key finding and the next action from stored rows.
- **Exhibits** (`services/exhibits.py`) compute charts from raw records through the same scoped reader as the engine. A
  restricted source stays closed in every chart until an approved test has read it.

### Reports

A report is an immutable, hashed snapshot in nine sections, numbered per investigation as version 1, 2, and so on. The PDF
(`services/report_pdf.py`) draws its exhibits as vectors from that snapshot alone, so it never reflects later changes.
Reports made before this structure still open, and sections they never captured say so.

The engine has no access to `dataset_ground_truth`, and a test enforces this.

### Supported claims

Absence of unauthorized access, monitoring completeness, and MFA enforcement. Any other claim concludes UNVERIFIED and
says NULL can't test it. To add a type, add observables, realities and a compiler rule.

## Meta Model API

Explorer, Worldbuilder and Challenger (`backend/app/reasoning/`) work on shared investigation state over Meta's Chat
Completions protocol. To turn them on, set `MODEL_API_KEY` and `META_MODEL_ID` in `.env`, or choose the model in
**Settings > AI**. Then confirm the integration against the real API:

```bash
make smoke-meta
```

- Without a key, or if a call fails, rule-based roles take over. The investigation says so and records the failure.
- Output that breaks a schema rule is sent back once for correction before NULL falls back.
- Model output is schema-validated. References to unknown evidence or observables are dropped, and the model can run only
  the read-only analyses already permitted. Checks that need approval are refused.
- `-contributor` model IDs may be used to train Meta's models, so they are blocked unless
  `NULL_ALLOW_CONTRIBUTOR_MODELS=true`. Real evidence never reaches them, even then.

## Layout

```
backend/app/analysis    Deterministic engine
backend/app/reasoning   Provider interface, Meta client, rule-based roles
backend/app/services    Orchestration, graph, remediation, reports
backend/app/api         FastAPI routers
backend/app/demo        Synthetic data and seed
backend/app/assets      Geist fonts for PDF export (SIL Open Font License)
frontend/src/app        Next.js pages
frontend/scripts        Logo generator (writes public/brand)
```

## Tests

```bash
make test    # Backend: ground truth, validator, Meta client, API, permissions
make e2e     # Browser: full demo. Needs `make api` and `make web`. WIPES the demo data before and after.
```

## Before real use

- Live connectors don't exist. Evidence comes from the simulated snapshots or uploaded files, and `execute_simulated`
  writes demo records rather than changing systems. A live connector means implementing a reader and an execution
  integration.
- The statistical thresholds and logon matching haven't been tested on real logs, so treat early results as a trial.
- Analysis runs in a thread inside the API process. A restart marks running investigations as failed. Use a real queue
  before running several workers.
- Login throttling lives in memory, so it's per process.
- Raw evidence sits in PostgreSQL, unencrypted beyond whatever the database provides. There is no retention policy.
- Set `NULL_ENV=production` so the server requires a secret, marks cookies Secure and hides the API docs.
