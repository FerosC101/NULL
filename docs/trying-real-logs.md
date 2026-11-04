# Trying NULL on real logs

This guide takes you from a test account to your first investigation on logs NULL did not generate. It takes about
an hour. A sign-in export alone is enough to start, and it tests one claim: whether MFA was enforced.

**Treat the result as a trial.** NULL's tests were built on simulated data, and these steps are how you find out what
needs changing.

## Before you start

- **Use logs you are allowed to use.** A developer test account you created is the safest place to begin. Don't upload
  your employer's or a client's logs without permission.
- **Leave the model off for the first run.** Real logs stay on your server unless you allow the Meta model for that
  upload. If you do, summaries containing hostnames, usernames and addresses go to Meta.
- **Know Meta's terms.** As of 9 October 2026, [Meta's terms](https://dev.meta.ai/legal/terms-of-service) say it doesn't
  train on Standard model content. They also allow automated and human review for compliance, and they name no fixed
  retention period. You must have the rights to submit the data. Personal data is banned on Contributor models, which
  NULL never uses for real evidence.

## 1. Create test activity

1. Create a test tenant with [Microsoft Entra](https://learn.microsoft.com/entra/) or
   [Okta](https://developer.okta.com/). Check their current sign-up options, because free plans change.
2. Add two or three test users and enable MFA for only some of them.
3. Sign in over several days, including a few failed attempts. NULL needs at least 24 hours of records before the period
   you investigate.

## 2. Export the sign-in logs

**Microsoft Entra:** open **Sign-in logs**, set the date range, select **Download**, then choose CSV.
[Microsoft's guide](https://learn.microsoft.com/entra/identity/monitoring-health/howto-download-logs) says a browser
download holds up to 100,000 sign-ins and its times are in UTC.

**Okta:** export from the **System Log**. Okta records every kind of event, so filter to sign-ins first.

## 3. Upload

1. Open **Sources > Upload evidence**.
2. Name the dataset, choose **Real logs**, and leave the model box off.
3. Add the CSV and check how it was read. If the file type isn't recognized, choose **Sign-in logs** and map the columns
   under **Columns and time zone**.
4. Read every rejection reason before you continue. Entra's **Interrupted** status is rejected on purpose, because it is
   neither a success nor a failure.
5. Select **Add to evidence**, then **Start an investigation**.

## 4. Investigate

Use the claim "MFA was enforced on every sign-in." Compare the result with what you set up in step 1.

Then try "No unauthorized access occurred." NULL should say it can't conclude this from sign-ins alone, and name the
missing sources. If it says SUPPORTED, that is a bug.

## What to watch for

| What you see | What it probably means |
| --- | --- |
| Columns aren't recognized | The export's headers differ from NULL's list. Map them by hand and note the names so they can be added |
| Many rejected rows | Note the reasons. A common one may need proper handling |
| Every logon looks unexplained | Windows and VPN logs have no sign-in session ID, so NULL matches them to a sign-in in the hour before. Service accounts and long-lived sessions won't match |
| Too many unusual hours or hosts | The thresholds are tuned to simulated data, and real activity is messier |
| Agents look stale, or joins fail | Hostnames differ between systems. NULL compares short upper-case names, which won't cover every naming scheme |

Write down anything surprising. Those notes decide what to fix before live connectors are worth building.
