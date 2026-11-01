# NULL

**Question Deeper. Know Better.**

NULL is an evidence intelligence platform. Given a claim such as "no unauthorized access occurred", it tests whether the
evidence could ever have justified that conclusion, builds competing explanations, recommends the check that best
separates them, runs what a person approves, and tracks fixes until evidence shows they worked.

The included demonstration uses synthetic data for a fictional company. It touches no real infrastructure.

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

- **Not yet run against the live API.** The client is tested against a fake server that enforces the documented rules.
- Without a key, or if a call fails, rule-based roles take over. The investigation says so and records the failure.
- Model output is schema-validated. References to unknown evidence or observables are dropped, and the model can run only
  the read-only analyses already permitted. Checks that need approval are refused.
- `-contributor` model IDs may be used to train Meta's models, so they are blocked unless
  `NULL_ALLOW_CONTRIBUTOR_MODELS=true`.

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

- Live connectors don't exist. All sources are simulated, and `execute_simulated` writes records rather than changing
  systems. Connecting one means implementing a reader and an execution integration.
- Analysis runs in a thread inside the API process. A restart marks running investigations as failed. Use a real queue
  before running several workers.
- Login throttling lives in memory, so it's per process.
- Raw evidence sits in PostgreSQL, unencrypted beyond whatever the database provides. There is no retention policy.
- Set `NULL_ENV=production` so the server requires a secret, marks cookies Secure and hides the API docs.
