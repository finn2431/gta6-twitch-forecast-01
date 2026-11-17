# GTA VI launch-day Twitch viewers — hour by hour

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/finn2431/gta6-twitch-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/finn2431/gta6-twitch-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

An entry for the **gta6-twitch-ccu-forecast-01** bounty. Given one case — hour 1's viewers
in a Twitch category and 42 past launch comparables with their hourly counts — it writes
five quantiles (5%, 25%, 50%, 75%, 95%) for each of hours 2 to 24 of release day.

## How it works

1. Every comparable launch becomes a *shape*: for each hour 2..24 of its own release day,
   `ln(viewers_h / viewers_1)`. Hours with no sample or zero viewers are skipped.
2. Each comparable gets one weight: `exp(-|ln(comp_hour1) - ln(case_hour1)|)` (similar-size
   launches count most) times `exp(-(ref_year - comp_year) / 8)` (recency), times `0.35`
   when the comparable is the case's own game (an extended-look premiere is not a launch).
3. Per hour, the weighted median of the shapes is the centre. The weighted 5/25/50/75/95%
   residual quantiles around it are scaled by `0.75`, and a random-walk widening
   `z * 0.05 * sqrt(hour - 1)` is added.
4. Hour `h` quantiles are hour 1's print times `exp(centre + spread + widening)`.
   If fewer than 4 comparables cover an hour, hour 1 is held flat with a
   `0.15 * sqrt(hour - 1)` log spread instead.
5. Timestamps are parsed by hand (no `zoneinfo`, no `dateutil`), all arithmetic is
   standard-library Python, and there is no randomness, so two runs are byte identical.

## Run it

```sh
mkdir -p /tmp/out
MAKEFUN_INPUT_DIR=/path/to/input MAKEFUN_OUTPUT_DIR=/tmp/out python3 main.py
```

Reads every `*.in` in the input directory (default `/input`) and writes `<id>.out` to the
output directory (default `/output`), one JSON object `{"hours": [...]}` with exactly 23
rows. Python 3.13, standard library only, no network.

## License

0BSD — see [LICENSE](LICENSE).
