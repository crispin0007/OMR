# Troubleshooting

[Guide home](index.md) · Previous: [Backup, restore and settings](backup-and-settings.md) · Next: [FAQ](faq.md)

## The scanner isn't found

The Scan tab says **No scanner found through Windows**.

1. Check the scanner is plugged in and switched on, then press **Find scanners**.
2. Check Windows can scan with it: try the Windows **Scan** app or **Windows Fax and Scan**. If
   Windows can't, install the scanner's driver from the maker's website (look for a "WIA" or
   "TWAIN/WIA" driver). The list shows each scanner's WIA driver by its name and its TWAIN driver
   as "name (TWAIN)"; if one doesn't work, try the other.
3. Still not listed? Scan with the scanner's own software into a folder, and on the Scan tab pick
   **A folder my scanner software saves into**. See [From a folder](scanning.md#2-from-a-folder).

## Pages "couldn't be read"

The app finds a sheet by its **four corner circles**. The reason shows on the live view, on Scanned
sheets and in Review. A page can't be read when:

- **"a corner mark is cut off at the edge of the scan"**: the sheet went into the scanner crooked, or
  the scan was cropped, and part of a corner circle is missing. Scan it again, straight, with a little
  space around the paper;
- **"the bubbles don't line up with the corner marks"**: a corner is folded, torn or covered, so the
  circles were found in the wrong place. Unfold it and scan again;
- a corner circle is **covered or missing**: rescan it flat and straight;
- the page is **upside down or the wrong page**, for example the back of the sheet;
- students filled **a different sheet** from the exam's: map that sheet
  ([Use a sheet you already print](map-printed-sheet.md)), then **Exam settings** >
  **Change sheet…**;
- the scan is very dark, very light or blurry: scan again at 200 DPI.

The page is kept either way, so nothing is lost. Fix the cause and scan or import it again. The app
refuses such a page on purpose: read with a corner in the wrong place, every answer would be shifted.

## Too many marks go to Review

- Students used a **light pencil** or didn't fill bubbles fully. Ask for a dark pen or soft pencil
  and fully filled bubbles.
- The scan is too light: check the scanner isn't set to a "lighten" or "remove background" mode.
- Sheets were printed too pale: print darker.

Review is there on purpose. It is quicker to press a key than to correct a wrong mark later.

## A paper jam or double feed

Scanning stops. Every sheet read before it is saved. Clear the jam, put the sheets that didn't go
through back in the feeder, and press **Start scanning** again. If a sheet ends up scanned twice,
delete one copy on **Scanned sheets** (the **Same roll number** count and Review will point to it).

## A sheet was scanned into the wrong exam

On **Scanned sheets**, select its rows and press **Move to exam…**. Only exams that use the same
sheet are offered.

## Scores look wrong

- Check the **answer key**, especially the **set** chosen in **Key for**.
- Check **Marks and sections**: a wrong mark of 0.25 means 0.25 is *taken off*.
- Check a student's sheet on **Scanned sheets** to see what was read.

## A sheet number shows as "?"

The barcode couldn't be read (a smudge or fold). It doesn't change the student's marks. The
number is listed above Scanned sheets so you can check that sheet by hand.

## The printed sheet doesn't read

Use **Check a printed copy…** on the Print sheet tab. Make sure the printer prints all four corner
circles: turn off "borderless" printing and check the paper size matches.

## The window is too big for the screen

The app fits small and scaled screens; if part of a screen is hidden, scroll it. Settings > **Text
size** Small and **Density** Compact fit more.

[Guide home](index.md) · Next: [FAQ](faq.md)
