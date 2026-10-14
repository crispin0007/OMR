# Proposal: email each student their scorecard (not built)

Status: **proposal only, waiting for a decision.** Nothing here is in the app yet.

## What it would do

After an exam, the institute presses **Email reports…** on Results. Each student whose email is in
the student list gets one email from the institute's own address with their report attached (the
HTML report, the PDF scorecard, or both). Nothing goes through any server of ours: the app talks
straight to the institute's mail provider (Gmail, Outlook, Zoho, the school's own server).

## Why it is worth doing, and why carefully

It saves printing and handing out a hundred scorecards. But an email can't be taken back: a wrong
address, a wrong attachment or a wrong score reaches a family the moment it is sent. So the design
puts most of its effort into stopping mistakes before the send, not into the sending.

## Settings (Settings → Email)

- Server, port, and security (STARTTLS on 587 or SSL on 465), with presets for Gmail, Outlook and
  Zoho.
- From name (defaults to the institute name) and from address.
- **Password: an app password, never the account password.** Gmail and Outlook need 2-step
  verification and an app password for this. It is kept in the Windows Credential Manager (through
  the `keyring` package, MIT licence), never in the database, a backup or a log.
- **Send a test email** to the institute's own address before anything else is allowed.

## Before a send

1. The student list needs an **Email** column (from Excel, like names). Rows without one, or with
   an address that doesn't look like an email, are listed and skipped.
2. **Nothing is sent while any sheet is still waiting for Review** or a mark is unconfirmed; the
   same rule the exports already follow.
3. A **preview** shows one real email (subject, body, attachment) and the total: "Send 142 emails,
   18 students have no address".
4. Two students sharing one address (siblings, a parent's address) are shown and must be confirmed.
5. The institute types the number of emails to confirm, so a slip of the mouse can't start it.

## While sending

- One connection, one email at a time, with a pause between emails. Gmail allows about **500 a day**
  from a normal account (2,000 for Workspace); the app stops before the limit and says when it can
  go on, rather than getting the account blocked.
- A **send log** per exam: student, address, time, result (sent / refused by the server / skipped,
  with the reason). It is saved after every email, so a power cut or a closed app never loses track.
- **Resume** sends only to students not marked sent. **Never sends twice** unless the institute picks
  "Send again" for chosen students (for example after a key change).

## After a key change

If the answer key changes after reports were emailed, the Results tab says how many sent reports
are now out of date and offers to send corrected ones to just those students, with a line saying
what changed.

## What it won't do

- No bulk-mail service, tracking pixels, read receipts or links to anything online. The report is
  attached, so it works offline and leaks nothing.
- No SMS or WhatsApp.

## Risks to accept

- An address typed wrong in the student list sends a student's marks to a stranger. The preview and
  the shared-address check reduce this; they can't remove it.
- Providers change their rules (Microsoft is phasing out passwords for SMTP in favour of OAuth).
  Supporting Outlook properly may later need an OAuth sign-in, which is more work.
- Emails from a school's Gmail can land in spam. A test send to a couple of parents first is advised.

## Size of the work

About a week: settings and keyring (1 day), the Email column and checks (1 day), the send loop, log
and resume (2 days), preview and confirm (1 day), tests with a local fake SMTP server and docs
(1 day).
