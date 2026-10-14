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
  The page finds each mark near its target as a mark-sized box darker than the even paper around it by
  a share of that paper's brightness, so dim light, shadow, glare and thin printed rings still show as
  marks, and the table at a sheet's corner doesn't. A mark found but well off its target shows amber,
  with a hint (closer, back, left, right, up, down, more light); each mark roughly in place (within
  about an eighth of the picture's width) turns green.
- **Taken readily; the PC checks.** The photo is taken once all four are green, their shape is the
  sheet's (allowing for a tipped phone), their edges aren't badly blurred and they have moved less than
  about 1% of the picture since the last check, for two checks running (about a third of a second).
  The next waits until the marks leave the targets. "Auto: any" keeps the earlier way (any bright,
  sharp, still picture) for a sheet whose marks aren't found; "Take now" takes one at once.
- **Details.** A button on the phone page shows, over the picture, each mark found or why not, and
  each check's number against what it needs, to tell why a sheet isn't taken on a real phone.
- **Read on the PC, at once.** Each photo is read with the exam's sheet. One that can't be read is not
  saved and the phone shows "Retake" and why; one that reads is saved and the phone shows the roll
  number and how many marks are left to check. A photo whose corner marks are blurred (blurred camera
  photos read wrong answers in tests) is not saved and gets "Retake" too.
- **Nothing lost or doubled.** Each photo carries its own id and is resent until the PC answers; the
  PC saves an id once, and the same sheet taken twice in a row once.

## Out of scope

- Reading on the phone: the phone only finds the corner marks; the PC reads the sheet.
- Keeping photos on the phone after its page is closed.
