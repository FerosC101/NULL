# Tallowmere Foods synthetic dataset

**This data is fictional.** Tallowmere Foods, Inc., its staff, hosts and incidents are invented. Nothing here comes
from a real organization, and it must never be presented as real evidence.

The dataset holds 135,105 rows of simulated security logs for a Philippine frozen-food distributor: 420 staff, 260
accounts and 210 hosts. The four snapshots each cover 29 to 30 October 2026, which is month-end close. Two contain an
intrusion and two do not.

The spec is in the [NULL Business Dataset Specification](https://claude.ai/artifact/D9Joqk4cpS4tG5oKAaLY4A).

## Files

| Path | Contents |
| --- | --- |
| `asset_register.csv` | The 210 in-scope hosts, shared by all snapshots |
| `snapshot-E/` | Payment data theft |
| `snapshot-F/` | Clean month-end |
| `snapshot-G/` | Cold-room blind spot |
| `snapshot-H/` | Silent ERP intrusion |
| `answer-key/` | What actually happened and the expected outcomes. Keep this away from any analysis |
| `generate.py` | Rebuilds every CSV from fixed seeds |

Each snapshot folder has the same files, except that `change_tickets.csv` exists only in E and G because F and H have
no approved changes. Each window runs from 09:00 UTC on 29 October to 09:00 UTC on 30 October, which is 17:00 to 17:00
PHT. Sign-ins and network flows also include baseline data from 09:00 UTC on 26 October. All times are UTC.

## Column formats

Columns are modelled on the usual exports from these systems. They are not exact copies of any vendor's format, so a
real export would still need its columns mapped. `IdP Session ID` and `Change Ref` would not appear in a raw Windows or
VPN log; they stand in for the correlation a log platform would add.

| File | Imitates | NULL source | Mapping notes |
| --- | --- | --- | --- |
| `signin_logs.csv` | Identity provider sign-in export | `idp_auth` | `Username` before the `@` is `user`. `Authentication Requirement` starting with "Multifactor" means `mfa` is true |
| `network_flows.csv` | Hourly flow summary | `network` | Direct mapping |
| `endpoint_events.csv` | EDR console events | `edr` | `Event Type` is `event`. `Event Count` is `events` |
| `endpoint_agents.csv` | EDR agent list | `coverage` | Direct mapping |
| `asset_register.csv` | Asset register | `inventory` | `In Scope` of Yes is true. `Site` is extra |
| `windows_logons.csv` | Windows event 4624 | `directory`, kind `dc_logon` | `LogonType` 2 is `interactive`. 10 is `remote_interactive` |
| `vpn_sessions.csv` | VPN concentrator log | `directory`, kind `vpn_session` | Direct mapping |
| `change_tickets.csv` | Change management export | `directory`, kind `change_record` | `Hosts` is separated by semicolons |
| `log_forwarding.csv` | Log forwarding status | `directory`, kind `log_coverage` | `Forwarding` of Yes is true |

## Verification

On 2026-11-01 all 135,105 rows were mapped to NULL's records in a temporary database. Each of the 4 claims in
`answer-key/expected_outcomes.csv` was then run on each snapshot through NULL's real analysis, approving every proposed
test.

All 16 results matched the expected assessment on the first run, with no tuning. This used rule-based reasoning, not
Muse Spark. The match shows the data behaves as designed. It does not measure accuracy on real logs, because the data
was written with knowledge of the tests that read it.

## Using it

NULL has no CSV import yet, so these files do not appear in the app. They are ready for that importer to be built and
tested against.

To rebuild the files, run this from the repository root:

```
backend/.venv/bin/python docs/datasets/tallowmere-synthetic/generate.py
```

The seeds are fixed, so the output is identical each time.
