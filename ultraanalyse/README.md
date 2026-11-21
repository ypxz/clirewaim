# ultraanalyse

One dashboard that answers, for every settled Game and every Line Item: what did we submit,
what was the Fair Value, what did every other team do, and how much did it make or cost us.

```bash
python3 -m ultraanalyse.refresh                      # pull the public record, rebuild
python3 -m ultraanalyse.refresh --drive FOLDER_URL   # also pull our logs from Google Drive (needs gdown)
python3 -m ultraanalyse.refresh --var var            # use the runner's own var/ directory
open ultraanalyse/out/dashboard.html                 # one self-contained file, no server
```

`pixi run ultra` runs the first form against the repository's `var/`.

## Pipeline

| Step | Reads | Writes |
| --- | --- | --- |
| `fetch.py` | the public leaderboard API | `data/raw/` |
| `build.py` | `data/raw/` and a private `var/` (`decisions/`, `ai_log/`, `run_logs/runner/`, `cases/`) | `data/dataset.json` |
| `render.py` | `data/dataset.json`, `template.html` | `out/dashboard.html` |

`data/` and `out/` are gitignored. The dashboard embeds our Charges, Limits and model
output, and this repository is public.

## What is exact and what is inferred

| Quantity | Source | Exact? |
| --- | --- | --- |
| Our Charge `a` and Limit `b` | last post that landed in the run log | exact |
| Our estimate, coverage probability, evidence channels | Strategy 2 decision log | exact |
| Model clauses | `ai_log` replies | exact |
| Fraud flag and lock | run log | exact |
| Money per team and Line Item | Transactions | exact, reproduces the published nets to the cent |
| Another team's Charge | Transactions | exact when anyone paid it; unseen when it was an Overcharge nobody accepted |
| Another team's Limit | Transactions | a range: at least the largest Charge it accepted, below the smallest it rejected |
| Fair Value `t` | Transactions | a bracket: largest Charge proven fair to smallest proven Overcharge |
| Another team's estimate of `t` | its Charge divided by its typical `a / t` | inferred |
| Topic and Line Item category | keyword rules in `topics.py` | rule-based labels |

## How the Transactions are read

`amount` is the money that moved from the Reviewer to the Issuer:

- accepted: `min(a, c)`
- rejected with `amount > 0`: `1.5 * a`, so the Charge was fair and the Issuer keeps the whole 1.5x
- rejected with `amount = 0`: the Charge was an Overcharge

This was checked against the published income and costs of all twelve teams. Note the
difference from the first tournament's record, where `amount` on a wrongful rejection was `a`.

## The two "avoidable" numbers

- **Reviewer:** the 0.5x penalty on every fair claim we rejected, plus every Overcharge we
  accepted. A Limit of exactly `t` would have paid neither.
- **Issuer:** income had we charged the largest Charge the record proves fair, minus what we
  earned. That Charge is a floor on the best one, so the gap is conservative.

Both hold every other team's numbers fixed. They are hindsight, not a strategy.
