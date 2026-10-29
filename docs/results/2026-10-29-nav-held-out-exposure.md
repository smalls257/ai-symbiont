# Navigation extension and the held-out maps: what was seen (plays Freedoom via ViZDoom)

Date of the work: 2026-10-29. Claim tags: [measured] = observed in our own run, [established] = known from the code's own documented behavior, [hypothesis] = a guess.

## What happened

While the navigation graph was extended (doors worked by switches, lifts, teleports, walkover exits), a scripted walker was run in the engine to check that its routes really reach the exit. The walker calls `go_to(exit)`; it uses no model, no card and no lesson store, and wrote its output only to a temporary directory.

It was started on all 8 held-out maps (MAP04, MAP08, MAP12, MAP16, MAP20, MAP24, MAP28, MAP32) [measured]: a first batch and two full sweeps of the 32 maps, then single-map debug runs on MAP04, MAP08 and MAP12 that printed traces of positions and sector heights. The walker's author had not read the level split before the first run. From the commit that made the verifier call the level guard, it refuses a held-out map, and a test proves the refusal for each of the 8.

Results the walker showed [measured] (every key given to the player): MAP04, MAP16 and MAP24 reached the exit; MAP08, MAP12 and MAP28 stalled mid-route; MAP20 and MAP32 stopped at planning.

## Fixes those runs informed

In the order they were made: the pickup-height rule (the walker "reached" a skull on a 144-unit pedestal on MAP24); solid scenery blocking cells (a barrel in a corridor on MAP04); walkover exits crossed rather than pressed (MAP24); thin door slabs stealing a neighbor's cell, and the two-sector reach for a door's switch (a double door on MAP04); checking that a walkover line can really be crossed (MAP24); wall clearance from 12 to 16 units (stuck positions on MAP08 and a training map). MAP24 shaped three of these, MAP04 two or three, MAP08 one.

## What it means

- The held-out pass count rose from 2 to 7 of 8 (25% to 88% [measured]) while the training count rose from 5 to 10 of 24 (21% to 42% [measured]). Held-out maps shaped some fixes, so the held-out rise overstates what the extension would show on maps never seen. The 7 of 8 is not evidence that the navigation generalizes.
- The 7 passing held-out maps are the routable subset of the 8, within a pool in which 15 of 32 maps still fail the route check [measured]. A result on them covers routable Freedoom maps only.
- All arms of any comparison share the same navigation, fitness and cases, so this exposure cannot favor one arm over another. It can affect which maps pass and how routable they are.
- No model, no card and no lesson store has played a held-out map [measured: the level guard refuses one without a frozen prereg, and its tests].
