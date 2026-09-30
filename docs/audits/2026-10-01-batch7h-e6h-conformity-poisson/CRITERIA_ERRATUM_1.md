# Criteria erratum 1 (written before any DEVSIM run; no result of the affected check had been seen)

`CRITERIA.md` section B states the presence counts of the one-sided and two-sided families as if the number of base rows were 2 for
every n. The families use n/4 rows (square base cells in a fixed 2 um x 0.5 um domain), and apex triangles are one per 3-triangle
sub-cell, so the counts scale with the row number. Derived by hand from the strip layout (not from any builder output):
- one-sided family (center 1.0 um, rings [h, h/2]): one-sided strips are [c-2h, c-h] (depth 0, 1 sub-row per row), [c-h, c-h/2] (depth 1,
  2 per row), [c+h/2, c+h] (depth 1, 2 per row), [c+h, c+2h] (depth 0, 1 per row) = 6 sub-cells per row, so the apex count is
  6 * (n/4) = 1.5 n (12 for n = 8, the number quoted in CRITERIA.md, which is only correct for n = 8).
- two-sided family (centers 2h, 5h, ring [h]): one-sided strips [0, h] and [6h, 7h], 1 per row each, so the apex count is
  2 * (n/4) = n/2 (4 for n = 8, as quoted).
The other presence checks (n triangles in [3h, 4h], the interior edge (3h, h/2)-(4h, h/2)) and every acceptance item 1-6 are unchanged.
