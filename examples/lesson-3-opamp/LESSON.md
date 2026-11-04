# Lesson 3: A real op-amp

**Your goal:** make every check pass on this two-stage op-amp. It starts out failing on gain.

This is what real analog design feels like: several targets at once, and each change helps one and can hurt another.

- `L2` is the channel length of the second stage. Longer usually means more gain and less speed.
- `CC` is the compensation capacitor. It trades speed for stability, which shows up as **phase margin**.

## What to do

1. Press **Run checks** and read each measured value against its target in `constraints.yaml`.
2. Pick the one check you want to fix first, and predict what a change to `L2` or `CC` will do.
3. Change `design/opamp.cir`, save and run the checks. Compare with your prediction.
4. Repeat until everything passes. Then press **Second opinion**, and Muse Wonder will question your design.

Ask the assistant in **Learn** mode whenever a number surprises you. It teaches from your circuit and leaves the changes to you.
