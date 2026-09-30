"""Synthesise the soundtrack: 120 BPM, A minor / C major, music and effects as one mix.

Cue times match comp.html. Output: audio.wav (44.1 kHz, 16-bit stereo, 23 s).
"""
import wave
from pathlib import Path

import numpy as np

SR, DUR, BEAT = 44100, 23.0, 0.5
N = int(SR * DUR)
rng = np.random.default_rng(26103)
HERE = Path(__file__).resolve().parent


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


class Bus:
    def __init__(self):
        self.x = np.zeros((2, N))

    def add(self, t0, sig, pan=0.0, gain=1.0):
        i = int(round(t0 * SR))
        if i >= N:
            return
        sig = sig[: N - i] * gain
        l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        self.x[0, i:i + len(sig)] += sig * l * 1.414
        self.x[1, i:i + len(sig)] += sig * r * 1.414


def tt(sec):
    return np.arange(int(sec * SR)) / SR


def env_adsr(n, a, r):
    e = np.ones(n)
    na, nr = int(a * SR), int(r * SR)
    e[:na] = np.linspace(0, 1, na)
    e[n - nr:] *= np.linspace(1, 0, nr)
    return e


def soft_saw(f, sec, bright=4.0, harmonics=14):
    t = tt(sec)
    ph = rng.uniform(0, 2 * np.pi)
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        if f * k > 9000:
            break
        out += np.sin(2 * np.pi * f * k * t + ph * k) / k * np.exp(-k / bright)
    return out


def pluck(f, sec=0.6, tau=0.16):
    t = tt(sec)
    return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) * np.exp(-t / 0.05)) * np.exp(-t / tau)


def bell(f, sec=2.2):
    t = tt(sec)
    parts = [(1, 1.0, 1.2), (2.0, .35, .7), (2.76, .25, .45), (5.4, .12, .2)]
    return sum(a * np.sin(2 * np.pi * f * m * t) * np.exp(-t / d) for m, a, d in parts) * np.minimum(1, t / 0.004)


def noise(sec):
    return rng.standard_normal(int(sec * SR))


def lowpass(x, k):  # moving average over k samples
    c = np.cumsum(np.concatenate([np.zeros(k), x]))
    return (c[k:] - c[:-k]) / k


def highpass(x, k):
    return x - lowpass(x, k)


# ---------------------------------------------------------------- arrangement
CHORDS = {"Am": ([57, 60, 64], 33), "F": ([53, 57, 60], 29), "C": ([55, 60, 64], 36), "G": ([55, 59, 62], 31)}
BARS = ["Am", "F", "C", "G", "Am", "F", "C", "G", "Am", "F", "C", "C"]   # 2 s per bar
KICK_ON = [(4.0, 18.5), (20.5, 22.0)]
HATS_ON = [(7.0, 18.5)]
CLAP_ON = [(11.5, 18.5)]

music, drums, fx, send = Bus(), Bus(), Bus(), Bus()


def on(t, spans):
    return any(a <= t < b for a, b in spans)


kicks = [b * BEAT for b in range(int(DUR / BEAT)) if on(b * BEAT, KICK_ON)]

for bar, name in enumerate(BARS):
    t0 = bar * 2.0
    notes, root = CHORDS[name]
    last = bar == len(BARS) - 1
    length = 1.0 if last else 2.3
    hook = t0 < 4.0
    # pad: three detuned voices per note
    for m in notes:
        for det, pan in ((-0.07, -0.6), (0.0, 0.0), (0.07, 0.6)):
            s = soft_saw(hz(m + det), length, bright=5.0 if hook else 6.5) * env_adsr(int(length * SR), 0.25, 0.5 if last else 0.35)
            music.add(t0, s, pan, 0.034 if hook else 0.028)
            send.add(t0, s, pan, 0.024)
    # bass, from the reveal on
    if not hook:
        for off in ((0.0, 0.75, 1.0, 1.75) if not last else (0.0,)):
            sec = 0.9 if last else 0.45
            t = tt(sec)
            b = (np.sin(2 * np.pi * hz(root + 12) * t) + 0.3 * np.sin(4 * np.pi * hz(root + 12) * t)) * np.exp(-t / 0.35) * np.minimum(1, t / 0.005)
            music.add(t0 + off, b, 0, 0.17)
    # pluck arpeggio, eighth notes
    arp = [notes[0] + 12, notes[2] + 12, notes[1] + 24, notes[2] + 12]
    for i in range(4 if last else 8):
        s = pluck(hz(arp[i % 4] + 12 * (i // 4 % 2 == 1 and not hook)))
        g = 0.10 if hook else 0.11
        music.add(t0 + i * 0.25, s, -0.35 if i % 2 else 0.35, g)
        send.add(t0 + i * 0.25, s, -0.35 if i % 2 else 0.35, g * 0.8)

# drums; a soft muted pulse under the hook, full kit from the reveal
for b in range(8):
    t = tt(0.3)
    s = np.sin(2 * np.pi * np.cumsum(70 + 50 * np.exp(-t / 0.02)) / SR) * np.exp(-t / 0.09)
    drums.add(b * BEAT, s, 0, 0.16 if b % 2 == 0 else 0.09)
for k in kicks:
    t = tt(0.45)
    f = 46 + 95 * np.exp(-t / 0.035)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.22) + 0.15 * highpass(noise(0.45), 8) * np.exp(-t / 0.004)
    drums.add(k, s, 0, 0.36)
for b in range(int(DUR / BEAT)):
    t0 = b * BEAT + 0.25
    if on(t0, HATS_ON):
        t = tt(0.08)
        drums.add(t0, highpass(noise(0.08), 3) * np.exp(-t / 0.022), 0.3, 0.075)
    if on(b * BEAT, CLAP_ON) and b % 2 == 1:
        t = tt(0.3)
        n = lowpass(highpass(noise(0.3), 20), 3)
        e = np.exp(-t / 0.09) * (1 + 0.6 * (np.sin(2 * np.pi * 90 * t) > 0) * (t < 0.02))
        drums.add(b * BEAT, n * e, -0.1, 0.14)
        send.add(b * BEAT, n * e, -0.1, 0.05)

# sidechain: duck the music under each kick
duck = np.ones(N)
tk = np.arange(N) / SR
for k in kicks:
    i = int(k * SR)
    seg = tk[i:i + int(0.4 * SR)] - k
    duck[i:i + len(seg)] = np.minimum(duck[i:i + len(seg)], 1 - 0.38 * np.exp(-seg / 0.11))
music.x *= duck

# ---------------------------------------------------------------- effects, in key
PENTA = [72, 74, 76, 79, 81, 84, 86, 88]         # C major pentatonic from C5


def tick(t0, m, g=0.10, pan=0.0):
    t = tt(0.12)
    s = np.sin(2 * np.pi * hz(m) * t) * np.exp(-t / 0.025) + 0.2 * highpass(noise(0.12), 4) * np.exp(-t / 0.003)
    fx.add(t0, s, pan, g)
    send.add(t0, s, pan, g * 0.6)


def whoosh(t_peak, g=0.07, up=0.32, down=0.2):
    sec = up + down
    t = tt(sec)
    e = np.where(t < up, (t / up) ** 2, np.exp(-(t - up) / (down / 3)))
    n = lowpass(highpass(noise(sec), 6), 3)
    fx.add(t_peak - up, n * e, 0, g)
    send.add(t_peak - up, n * e, 0, g * 0.7)


def thud(t0, g=0.35):
    t = tt(0.3)
    f = 70 + 60 * np.exp(-t / 0.03)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.12) + 0.25 * lowpass(noise(0.3), 6) * np.exp(-t / 0.02)
    fx.add(t0, s, 0, g * 0.7)


def marimba(t0, m, g=0.16, pan=0.0):
    t = tt(0.7)
    f = hz(m)
    s = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.28) + 0.4 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.03)) * np.minimum(1, t / 0.002)
    fx.add(t0, s, pan, g)
    send.add(t0, s, pan, g * 0.8)


# S1: the stated date flips, once per report; "+1 month" pops
FLIPS = [0.35, 1.0, 1.6, 2.2, 2.8]
for i, f in enumerate(FLIPS):
    tick(f, 81 + (0, 2, 4, 5, 7)[i] - 12, 0.13, 0.25)
    if i:
        marimba(f + 0.02, 84, 0.06, 0.4)
# riser into the reveal, impact on it
sec = 1.15
t = tt(sec)
r = lowpass(highpass(noise(sec), 4), 2) * (t / sec) ** 2.5
sweep = np.sin(2 * np.pi * np.cumsum(220 * 2 ** (t / sec)) / SR) * (t / sec) ** 2
fx.add(4.0 - sec, r * 0.07 + sweep * 0.05)
send.add(4.0 - sec, r * 0.05)
t = tt(1.4)
boom = np.sin(2 * np.pi * np.cumsum(40 + 60 * np.exp(-t / 0.05)) / SR) * np.exp(-t / 0.5)
fx.add(4.0, boom, 0, 0.28)
fx.add(4.0, lowpass(noise(1.4), 12) * np.exp(-t / 0.25), 0, 0.12)
send.add(4.0, lowpass(noise(1.4), 12) * np.exp(-t / 0.25), 0, 0.1)
# scene wipes
for w in (7.0, 11.5, 15.0, 18.5):
    whoosh(w, 0.06)
# S3: rows land, callout, stamp
for i in range(5):
    tick(7.2 + i * 0.11 + 0.1, PENTA[i], 0.05, -0.3 + 0.15 * i)
marimba(8.45, 76, 0.12, -0.3)
marimba(8.52, 79, 0.10, -0.3)
thud(9.3, 0.38)
tick(9.3, 88, 0.06)
# S4: the counter climbs, bars grow
for i, tc in enumerate(11.75 + 1.0 * (1 - (1 - np.linspace(0.02, 0.9, 10)) ** (1 / 3))):
    tick(float(tc), PENTA[i % 8] - 12 * (i < 5) + 12, 0.045, 0.2)
marimba(12.6, 79, 0.10, 0.2)
marimba(12.9, 72, 0.08, -0.2)
# S5: three cards
for i, m in enumerate((72, 76, 79)):
    marimba(15.45 + i * 0.45 + 0.05, m, 0.15, (-0.4, 0, 0.4)[i])
# S6: punchline, then the name
tick(18.65, 81, 0.07)
thud(18.95, 0.28)
for m, d in ((84, 0.0), (88, 0.02), (91, 0.04)):
    s = bell(hz(m), 2.4)
    fx.add(20.5 + d, s, 0, 0.07)
    send.add(20.5 + d, s, 0, 0.09)
fx.add(20.5, boom, 0, 0.2)


# ---------------------------------------------------------------- reverb and master
def reverb(x, sec=1.8, decay=0.55):
    n = int(sec * SR)
    t = np.arange(n) / SR
    out = np.zeros_like(x)
    for ch in range(2):
        ir = lowpass(rng.standard_normal(n), 3) * np.exp(-t / decay)
        ir[: int(0.012 * SR)] = 0            # pre-delay
        ir /= np.sqrt(np.sum(ir ** 2))
        L = 1 << int(np.ceil(np.log2(len(x[ch]) + n)))
        out[ch] = np.fft.irfft(np.fft.rfft(x[ch], L) * np.fft.rfft(ir, L), L)[: len(x[ch])]
    return out


mix = music.x + drums.x + fx.x + 0.55 * reverb(send.x)
fade = np.ones(N)
fade[: int(0.01 * SR)] = np.linspace(0, 1, int(0.01 * SR))
tail = int(0.8 * SR)
fade[-tail:] = np.linspace(1, 0, tail) ** 1.5
mix *= fade
mix /= np.max(np.abs(mix)) / 0.95
mix = np.tanh(mix * 1.15) / np.tanh(1.15)
mix *= 0.89 / np.max(np.abs(mix))

pcm = (mix.T * 32767).astype("<i2")
with wave.open(str(HERE / "audio.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"audio.wav {DUR} s, peak {np.max(np.abs(mix)):.2f}")
