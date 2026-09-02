# Publish checklist (shell → GitHub)

Do this **after** you have a real empty repo URL.

1. **Set the URL** in:
   - `README.md` (replace every `GITHUB_REPO`)
   - `pyproject.toml` `[project.urls]`

2. **Remote**
   ```bash
   git remote add origin git@github.com:ORG/sopcontrol.git   # your URL
   git fetch origin  # if repo already exists
   ```

3. **Branch hygiene**
   - Prefer merging `zcode/living-project-batch1` (or current work) into `main`
   - Do **not** commit local dogfood churn under `.sopcontrol/tasks/` / ledger unless intentional
   - Fixtures: `candidates.yaml` under `corpus/fixtures/**/.sopcontrol/rules/` is gitignored

4. **Verify**
   ```bash
   pip install -e ".[dev]"
   pytest -q
   ./examples/minimal/run.sh
   ./scripts/vertical-check.sh
   ```

5. **Tag & push**
   ```bash
   git tag -a v0.2.0 -m "sopcontrol 0.2.0 experimental public shell"
   git push -u origin main
   git push origin v0.2.0
   ```

6. **Optional PyPI** (later)
   - Build with `python -m build` and upload; until then install via `pip install "git+URL"`

First public message suggestion:

> Experimental but real: a model-neutral control plane that lives in the project. v0.2 — see LIMITATIONS.md.
