# Minimal demo (throwaway copy)

Shows: **init → rule → audit → growth → gate** on a temp copy of the `jobflow-preview` fixture — no edits to the real fixture tree.

## Run

From the **sopcontrol repo root** (with `sopctl` on PATH, e.g. after `pip install -e .`):

```bash
./examples/minimal/run.sh
```

Or:

```bash
bash examples/minimal/run.sh
```

## What you should see

1. A temp project under `/tmp/sopcontrol-minimal-*`
2. `audit` reporting at least one **fail/gap** around legacy/redundant entry (expected)
3. `growth status` / `growth measure` printing an `ambiguity_index`
4. `gate` **exiting non-zero** when fails exist (expected for this fixture)

That is success: the control plane **observed** and **blocked**, it did not pretend the space was clean.

## Clean up

The script prints the temp path; delete when done:

```bash
rm -rf /tmp/sopcontrol-minimal-*
```
