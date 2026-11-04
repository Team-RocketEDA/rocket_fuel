# Lesson 1: Your first filter

**Your goal:** make this filter's corner frequency land between 1.5 and 1.7 kHz. It's at about 159 Hz now.

A low-pass filter lets low frequencies through and weakens high ones. The **corner frequency** is where the signal has
dropped by 3 dB, to about 70% of its size. For a resistor R and a capacitor C:

```text
corner frequency = 1 / (2 × π × R × C)
```

## What to do

1. Press **Run checks**. Some checks fail, and that's the point: you can see what the simulator measured.
2. Open **Plots** and find the corner on the curve.
3. Work out on paper which value to change, and whether it should go up or down.
4. Open `design/rc_filter.cir` under **Files**, change the value and save.
5. Press **Run checks** again. Did the result match your prediction?

## Stuck?

Ask the assistant in **Learn** mode. Try "Why did the corner check fail?" or "What happens if I make C bigger?" It explains
and asks questions back, but you make the changes. Only the simulator decides whether you pass.

**Next:** Lesson 2, where one change improves one number and worsens another.
