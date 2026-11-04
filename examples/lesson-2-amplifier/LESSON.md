# Lesson 2: Your first amplifier

**Your goal:** reach at least 20 dB of gain while keeping at least 3 MHz of bandwidth. The gain is only about 6 dB now.

A transistor turns a small change in its input voltage into a change in current. That current flows through the load
resistor RL, which turns it back into a voltage. So a bigger RL usually means more gain:

```text
gain ≈ gm × RL
```

## What to do

1. Press **Run checks** and note the gain and the bandwidth.
2. Predict what a larger RL does to each one. Write it down.
3. Change `RL` in `design/amplifier.cir`, save and run the checks. Try a few values, including a very large one.

## The surprise

Past a certain point, a bigger RL makes the gain **worse**. Why? More current through a bigger resistor drops more
voltage, so the output sinks until the transistor can't work properly. Plots won't tell you this by themselves, so
ask the assistant in **Learn** mode to explain "saturation" using your own numbers.

**Next:** Lesson 3, a full op-amp, with several checks that pull against each other.
