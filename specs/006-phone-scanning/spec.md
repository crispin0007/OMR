# Feature Specification: Scan with a phone

**Feature Branch**: `006-phone-scanning`

**Created**: 2026-10-14

**Status**: Draft

**Input**: An institute without a scanner, or with a busy one, photographs sheets with a phone on the
same Wi-Fi, quickly and without touching the screen for each sheet.

## The model

- **The PC serves the phone.** "Scan with a phone…" on the Scan tab lets the phone in (the
  several-PCs server, specs/005-several-pcs) and shows a QR code. The link carries a token for that
  exam and operator; Other PCs lists it as "Phone" and can take it out.
- **Secure link for the live camera.** Browsers only give a page the camera on a secure address, so
  the PC makes its own certificate for its addresses (kept beside its data, made again when the address
  changes) and serves the phone page securely on the next port. The phone warns once; the guide
  says what to tap. A plain link without the live camera uses the phone's own camera through an
  upload button.
- **Targets on the corner marks.** The camera view draws a target where each of the sheet's corner marks
  should be, the shape of the exam's own marks (square or ring), with the page fitted in the picture.
  The page finds the dark mark-sized blob near each target. A mark found but out of its target shows
  amber, with a hint (closer, back, left, right, up, down, more light); all four in their targets turn
  green. The photo is taken when all four are in, their edges are sharp and the picture is still; the
  next waits until the marks leave the targets. "Auto: any" keeps the earlier way (any bright, sharp,
  still picture) for a sheet whose marks aren't found; "Take now" takes one at once.
- **Read on the PC, at once.** Each photo is read with the exam's sheet. One that can't be read is not
  saved and the phone shows "Retake" and why; one that reads is saved and the phone shows the roll
  number and how many marks are left to check.
- **Nothing lost or doubled.** Each photo carries its own id and is resent until the PC answers; the
  PC saves an id once, and the same sheet taken twice in a row once.

## Out of scope

- Reading on the phone: the phone only finds the corner marks; the PC reads the sheet.
- Keeping photos on the phone after its page is closed.
