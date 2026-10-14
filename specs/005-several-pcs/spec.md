# Feature Specification: Several PCs on one exam

**Feature Branch**: `005-several-pcs`

**Created**: 2026-10-14

**Status**: Draft

**Input**: A big institute scans a few thousand sheets after a mock test on two or three scanners at
once, on different PCs, into one exam. Operators log in, and every scan and correction says who did it.

## The model

- **Main PC.** One PC holds the exams, as today. Under Settings it lets other PCs in: it shows its
  address and a join code. Nothing else is installed; the app itself answers on the office network.
- **Scanning PC.** Another PC with the app joins with the main PC's address, the join code and an
  operator's name and PIN, then picks one of the main PC's open exams. It gets a copy of that exam (its
  sheet, answer key, marks and student list) and scans into the copy exactly as into any exam: every
  page is read and saved on the scanning PC at once, then sent to the main PC. A page stays waiting on the
  scanning PC until the main PC has saved it, so a dropped network, a closed laptop or a main PC that is
  switched off loses nothing; the pages go when it is back. A page is never saved twice on the main PC,
  however often it is sent.
- **Operators.** The main PC keeps operators: a name, a PIN and a role. An **admin** can do everything.
  An **operator** can scan, review and look at results, but can't change the answer key or marks, delete
  sheets or exams, or manage operators. With no operators, nobody logs in, as today. Once there is one,
  the main PC asks who is using it when it opens, and the first operator must be an admin.
- **Who did it.** A page sent from a scanning PC is in a batch named after that PC and operator.
  Corrections and key changes made on the main PC are logged under the operator logged in.

## User Scenarios

### US1 - Scan on two PCs into one exam (P1)

The coordinator turns on "Let other PCs scan into this PC" and reads out the join code. On the
second PC, "Scan into another PC's exam" asks for the address, code, name and PIN, lists the exams and
opens the chosen one. Its Scan tab works as usual and says how many pages are sent and waiting. The
main PC shows the pages as they arrive.

### US2 - Logins (P1)

The coordinator adds operators with PINs. From then on the app asks who is using it; an operator can't
change the key or delete anything. A scanning PC's operator signs in on the main PC's list.

### US3 - Taking a PC out (P2)

The main PC lists the PCs that joined, and removing one stops it sending. A new join code stops new
PCs joining; PCs already joined keep working.

## Edge cases

- The main PC refuses pages for an exam that is deleted or archived, a page that isn't a valid page
  row (bad JSON, image not a PNG or JPEG) and requests without a joined PC's token.
- The answer key changed on the main PC after a scanning PC joined: the scanning PC fetches the exam
  again each time it opens it. Scores on the main PC are always its own.
- Review and corrections are done on the main PC. A correction made on a scanning PC stays there and
  is not sent (its Scan tab says to check sheets on the main PC).

## Out of scope

- Reviewing from scanning PCs, and syncing their corrections back.
- Encryption on the network: the join code and PINs keep strangers out of an office network, not a
  determined attacker on it. Use it on a network you trust.
- Working across the internet.
