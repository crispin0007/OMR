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

- Server, port, and security (STARTTLS on 587 or SSL on 465), with presets for Gmail, Google
  Workspace, Outlook, Zoho and the bulk services, or any other SMTP server.
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

- One connection, one email at a time, at the **sending rate set in Settings**: emails per minute,
  per hour and per day. Presets fill these in; the institute can change them.

  | Preset | Per day (about) | Notes |
  |---|---|---|
  | Gmail (personal) | 500 | Google blocks the account for a day if it is passed |
  | Google Workspace | 2,000 | A custom-domain address hosted by Google |
  | Microsoft 365 / Outlook | 10,000 recipients | Lower for new accounts |
  | Zoho Mail | depends on the plan | Check the plan's limit |
  | Bulk service (Amazon SES, Brevo, Mailgun…) | what the account allows | Made for sending many emails |
  | Custom | typed in | Any other SMTP server |

  The app keeps a little under the limit, and counts emails sent earlier the same day.
- **Big batches carry over.** When the day's limit is reached the app stops, says how many are left
  and when it can go on, and **Resume** the next day sends only the rest. A batch of 1,500 on
  personal Gmail goes out over three days, or in one go through a bulk service.
- A **send log** per exam: student, address, time, result (sent / refused by the server / skipped,
  with the reason). It is saved after every email, so a power cut or a closed app never loses track.
- **Never sends twice** unless the institute picks "Send again" for chosen students (for example
  after a key change).

## Is a custom-domain email unlimited?

No. An address like `results@your-institute.edu.np` is still sent through whoever hosts that
domain's email (Google Workspace, Microsoft 365, Zoho, a web host's cPanel mail), and that provider
sets the limit. Many cheap web hosts allow only 100 to 500 emails an hour. For thousands of emails
at once, a bulk service (Amazon SES, Brevo, Mailgun and others) is the usual answer; the app works
with any of them because they all offer plain SMTP.

### Getting into the inbox, not spam: SPF, DKIM and DMARC

With your own domain, three settings in the domain's DNS tell other mail servers the email really
comes from you. Your email provider gives the exact values; you (or whoever manages the domain)
paste them in once.

- **SPF** lists which servers may send email for your domain. If you send through a bulk service,
  it must be added here too.
- **DKIM** signs each email so it can't be altered on the way. The provider gives a key to add.
- **DMARC** tells receivers what to do with an email that fails the other two (start with "report
  only", `p=none`).

Without them, scorecards are likely to land in spam or be refused. The app's **Send a test email**
can't check DNS, but the guide will link to free checkers.

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
- The limits in the table are what providers publish today and change from time to time; the
  presets are a starting point, and the institute can always type its own.
- Providers change their rules (Microsoft is phasing out passwords for SMTP in favour of OAuth).
  Supporting Outlook properly may later need an OAuth sign-in, which is more work.
- Emails from a school's Gmail can land in spam. A test send to a couple of parents first is advised.

## Size of the work

About a week: settings and keyring (1 day), the Email column and checks (1 day), the send loop, log
and resume (2 days), preview and confirm (1 day), tests with a local fake SMTP server and docs
(1 day).
