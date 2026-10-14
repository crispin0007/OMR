# Scan with a phone

[Guide home](index.md) · Previous: [Several PCs on one exam](several-pcs.md) · Next: [The answer key](answer-key.md)

No scanner? A phone on the same Wi-Fi as the PC photographs the sheets one after another. It needs no
app and no internet: the phone opens a page the PC itself serves.

## Start

1. Open the exam and go to the **Scan** tab.
2. Press **Scan with a phone…**. The PC shows a QR code.
3. On the phone (connected to the same Wi-Fi), point the camera at the QR code and open the link.
4. The phone warns that the connection isn't private. That's expected: the address belongs to your PC,
   not a website, so nobody on the internet vouches for it. Tap **Advanced**, then **Proceed** (on an
   iPhone, **Show details**, then **visit this website**). It asks once per phone.
5. Allow the camera.

![The PC's QR code for the phone, with the steps](images/phone-dialog.png)

## Photograph the sheets

![Left: the sheet too far away, its marks amber outside the targets. Right: lined up, the targets green, and the sheet read](images/phone-targets.png)

The camera view shows a target for each of the sheet's four corner marks, the same shape as the
marks printed on the exam's sheet (squares or rings).

1. Put a sheet down flat and hold the phone over it. Room light is enough; a shadow across the sheet,
   a lamp's glare or the phone tipped a little is fine.
2. Bring the sheet's corner marks near their targets. They don't have to sit exactly in them: each
   mark turns green once it's roughly in place. A mark found but still well off shows amber, and the
   line under the picture says what to do: **Move the phone closer**, **Move the phone back a
   little**, left, right, up or down, or **Need more light**.
3. When all four are green, hold the phone steady for a moment. It takes the photo by itself, usually
   within half a second, and shows **✓ Read: roll 00195**, or **Retake** and why.
4. Put down the next sheet. It waits for the marks to leave the targets, then takes the next one.

The phone takes photos readily; the PC is the check. A photo that is blurred, cut off or can't be
read isn't saved, and the phone asks for a retake.

The **Auto** button changes how photos are taken:

- **Auto: marks** (the default): as above.
- **Auto: any**: takes any picture that is bright, sharp and still, without the targets, for a sheet
  whose marks the phone doesn't find.
- **Auto: off**: press **Take now** for each sheet.

- Each photo is read on the PC straight away. A photo that can't be read isn't saved; the phone asks
  you to retake it.
- The same sheet taken twice in a row is saved once.
- The sheets appear on **Scanned sheets** as they arrive, in a batch named **Phone** with the
  operator's name and the date, and unclear marks go to **Review** as with a scanner.
- If the Wi-Fi drops, the phone keeps the photos and sends them when the PC is back. Keep the page
  open until the count stops going up.

## Without the warning: Photos…

If you'd rather not accept the warning, open the plain link shown under the QR code. The live camera
doesn't work there (browsers only allow it on secure addresses), but **Photos…** opens the phone's
own camera for each sheet, and each photo is read the same way.

## Good to know

- The PC lets the phone in while the app is open. Under **Settings**, **Other PCs…** lists each phone
  as **Phone**; **Take out** stops it.
- With logins, the phone scans as the operator logged in on the PC.
- A scanner's feeder is still the fastest way for a few thousand sheets. A phone suits a class or
  two, or a scanner that's busy.
- Like several PCs, this is for your institute's own network, not public Wi-Fi.

## When it doesn't take the photo: Details

Press **Details** at the top of the phone page to see what the camera sees, over the picture. It stays on
for that phone until you press it again.

![Details on: each corner mark found and in place, and each check's number against what it needs](images/phone-details.png)

- **camera**: the camera's picture size, and how many times a second it checks. Under about 3 a
  second, the phone is slow; close other apps.
- **light**: how bright the picture is (0 to 255). Under about 60, add light.
- One line per corner mark: **✓ in** (found, in place), **~ off** (found, too far from its target) or
  **✗** and why not (**too faint**, **too dark here**, **uneven around it**, which is usually the
  sheet's edge or the table in the target). Then how far it is from its target, how dark it is
  against the paper (over 0.25 counts as a mark) and how sharp its edge is.
- **shape**: how far the four marks are from the sheet's shape (the phone tipped too much when it's
  over 0.3); **moved**: how far the marks moved since the last check (a steady hand is under the
  number shown); **sharp**: the blurriest mark's edge (over 0.15 is sharp enough).
- **steady**: how many checks running everything has passed; it takes the photo at 2.

If a sheet isn't taken on your phone, a screenshot with Details on shows which of these fails.

[Guide home](index.md) · Next: [The answer key](answer-key.md)
