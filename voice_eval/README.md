# voice_eval: speech-to-text model comparison

Standalone harness for the voice model evaluation. Nothing in `app/` imports it.
It only reads `data/activity_taxonomy.csv` and `data/conditions.csv` to build
keyterm hints.

## Setup (once)

1. `copy voice_eval\.env.example voice_eval\.env` and add the API keys.
2. `copy voice_eval\references.example.csv voice_eval\references.csv`, then
   replace the example rows with your real clips.
3. Put the audio files in `voice_eval/recordings/`. Any format works if
   ffmpeg is installed (`scoop install ffmpeg`): every non-WAV clip is
   converted once to 16 kHz mono WAV in `recordings/_converted/`, so all
   models get identical audio. Phone recorders' raw `.aac` files are rejected
   by Sarvam unless converted.

`recordings/`, `references.csv` and `results/` are gitignored because they hold
team members' voices.

## references.csv columns

| Column | Meaning |
| --- | --- |
| clip | File name inside `recordings/` |
| group | `logging`, `chatbot`, `exercise_name` or `warning` (warning misses rule a model out) |
| speaker | Who recorded it |
| reference | What was actually said, typed exactly |
| key_terms | Words that must come through, separated by `\|`. Give alternative spellings with `/`, e.g. `dard/दर्द` |

## Run

From the repo root, with the venv active:

```
python -m voice_eval.run_eval --limit 2                 # cheap smoke test
python -m voice_eval.run_eval                           # everything
python -m voice_eval.run_eval --providers sarvam-v4,sarvam-v4-keyterms
python -m voice_eval.run_eval --language hi-IN          # force Hindi instead of auto-detect
python -m voice_eval.keyterms                           # show the hint list sent to v4
```

Results go to `voice_eval/results/`: one CSV with a row for each clip and
provider, and one summary CSV.

## Adding a vendor

Add a module to `providers/` that turns an audio file into text, then add an
entry in `providers/__init__.py`.
