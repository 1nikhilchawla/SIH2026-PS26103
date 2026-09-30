# ANUMAAN launch video: plan

Made with the `/brag-slim` method from https://github.com/latent-spaces/brag
(commit c893c5e): story, visuals, sound and render built on this machine, with
no bundled assets. 1920×1080, 30 fps, 23 s, H.264 + AAC, −14.4 LUFS.

## Angle

Start with one real project from the Flash Reports: the Raipur–Simga highway
(NHAI, Chhattisgarh). It was promised for April 2018 and shows 100 % physical
progress, yet each monthly report since March 2026 has moved its stated
completion one month later. ANUMAAN had ranked it the #1 risk in June, the
July report moved the date again, and the model gives 93 % for another move.
The case shows what the product does and that the forecasts hold up.

- **Hook:** a stated-completion card flips May → Jun → Jul → Aug 2026 beside "Promised: Apr 2018 · Built: 100 %".
- **Highlights:** the real Early Warning Alerts screen; 125 of the 141 highest-risk June flags moved in July (18 % base rate); offline, ministry-scoped, no foreign AI APIs.
- **Punchline:** "Next report? 93 % it moves again."
- **Tone:** default, punchy and clean, in ANUMAAN's own navy, blue, orange and green and its Calibri type.

## Where every number comes from

`work/build_data.py` reads the live API responses (`/api/status`,
`/api/projects`, `/api/metrics`, `/api/project/619103`, `/api/snapshot`).
`comp.html` only formats values from `work/data.js`; no number on screen is
typed by hand.

| On screen | Source |
|---|---|
| Promised Apr 2018, Built 100 % | `/api/project/619103` → `original_doc`, `behaviour.physical_progress_pct` |
| Apr → May → Jun → Jul → Aug 2026, Mar–Jul reports | same → `evidence[]` (stated date moved, report by report) |
| Flagged in Jun 2026: 0.92, #1 of 1,404 | same → `risk_series`, `reference_class.rank / of_projects` |
| July report: moved to Aug 2026 | same → `stated_doc` from the July 2026 row |
| 125 / 141, 89 %, 18 % | `/api/metrics` → top reliability decile (n = 141, mean_y × n = 125), `base_rate_test` |
| PR-AUC 0.68 | `/api/metrics` → `models.lightgbm.pr_auc` (walk-forward, test month 2026-06) |
| 104 KB for all 1,775 projects | measured gzip size of `/api/snapshot`; `n_projects` |
| 11 reports · 2,195 projects · 17,010 project-months | `/api/status` → `provenance` |
| 93 % | `/api/snapshot` → live July-2026 forecast `p` for 619103 (outcome not yet known) |

## Storyboard (23 s; every cut on a beat at 120 BPM)

| # | Time | Scene |
|---|---|---|
| 1 | 0.0–4.0 | **Hook.** Raipur–Simga highway: Promised Apr 2018, Built 100 %. The stated-completion card flips once per report, each move marked "+1 month". "Every report since March: done next month." |
| 2 | 4.0–7.0 | **Reveal.** Navy wipe on the beat. ANUMAAN · अनुमान · estimate. "Predicts which completion dates slip next." |
| 3 | 7.0–11.5 | **Product.** The real Early Warning Alerts screen for June 2026; rows land, the #1 row is highlighted. Callout "Flagged in Jun 2026: 0.92", then a stamp "July report: moved to Aug 2026". |
| 4 | 11.5–15.0 | **Proof.** Counter 0 → 125 / 141: "of its top 141 June flags slipped in July". Bars: 89 % against 18 % for all projects. |
| 5 | 15.0–18.5 | **Government.** Works offline, Ministry-scoped, Stays in India. |
| 6 | 18.5–23.0 | **Punchline and outro.** The Aug 2026 card: "Next report? 93 % it moves again." Then ANUMAAN, "Audit the stated completion date.", the team and the repository. |

## Sound

`work/music.py` synthesises every sound. There is no third-party audio,
because the licence for brag's bundled music is not documented. The track is
Am–F–C–G at 120 BPM. The hook has a pad, plucks and a muted pulse; the kit
comes in on the reveal, and the clap and hats come in with the proof. The kit
drops out for the punchline and returns under the outro, which ends on a bell
chord. The date flips, row ticks, stamp and cards are all tuned to C major
pentatonic and sent to the same reverb as the music. The kick side-chains
the music. The mix is EQ'd and loudness-normalised at encode.

## Rebuild

```
python work/build_data.py          # needs the brag-data/ API dumps next to work/
node   work/render.mjs frames      # headless Chrome -> frames/
python work/music.py               # -> audio.wav (numpy)
ffmpeg -framerate 30 -i frames/%05d.jpg -i audio.wav \
  -af "highpass=f=30,lowshelf=f=90:g=-3,highshelf=f=3000:g=2,loudnorm=I=-15:TP=-1.5:LRA=7" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -movflags +faststart \
  -c:a aac -b:a 192k -shortest brag.mp4
```

Poster: the settled hook frame (3.4 s), used as `brag.jpg` and written over frame 0.
