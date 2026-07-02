# Publishing `onveef` to PyPI

End-to-end guide for building and releasing this package. It assumes
[`uv`](https://docs.astral.sh/uv/) is installed; every command also has a plain
`python -m build` / `twine` equivalent if you prefer stock tooling.

---

## 0. One-time prerequisites

1. **Accounts**
   - Register on [PyPI](https://pypi.org/account/register/) and
     [TestPyPI](https://test.pypi.org/account/register/) (separate accounts).
   - Enable 2FA on both (required to upload).

2. **Claim the name early.** Package names are first-come on PyPI. `onveef` is a
   placeholder — pick your final name and reserve it before writing more code
   (see [§7 Renaming](#7-renaming)). Do a quick availability check:
   ```bash
   pip index versions onveef        # or just open https://pypi.org/project/<name>/
   ```

3. **Credentials — use API tokens, never your password.**
   - Create a token at <https://pypi.org/manage/account/token/> (scope it to the
     project after the first upload; "entire account" is fine for the very first).
   - Do the same on TestPyPI.
   - Store them in `~/.pypirc` (mode `600`) or as environment variables — never in git:
     ```ini
     # ~/.pypirc
     [distutils]
     index-servers =
         pypi
         testpypi

     [pypi]
     username = __token__
     password = pypi-AgEIcHl...            # your PyPI token

     [testpypi]
     repository = https://test.pypi.org/legacy/
     username = __token__
     password = pypi-AgEIcHl...            # your TestPyPI token
     ```
   For CI, prefer **Trusted Publishing** (OIDC) instead of long-lived tokens — see [§6](#6-automated-release-github-actions).

---

## 1. Pre-flight checks (must be green)

```bash
cd onveef
uv sync --extra dev            # create .venv and install dev tooling
uv run ruff check src tests    # lint
uv run ruff format --check src tests
uv run mypy                    # strict type check
uv run pytest -q               # tests (no hardware needed — recorded/mocked)
```

Do not release unless all four pass.

---

## 2. Bump the version

The version is derived from `src/onveef/__init__.py::__version__` (hatchling reads
it via `[tool.hatch.version]`, so `pyproject.toml` carries `dynamic = ["version"]`).
[Commitizen](https://commitizen-tools.github.io/commitizen/) manages the bump: it
reads your [Conventional Commits](https://www.conventionalcommits.org) since the
last tag, picks the next [SemVer](https://semver.org/) number (`fix:` → patch,
`feat:` → minor, `feat!:`/`BREAKING CHANGE:` → major), updates `__init__.py` and
`CHANGELOG.md`, commits, and tags — all in one step:

```bash
uv run cz bump --yes            # auto-detects the increment from commits
# or force it:  uv run cz bump --yes --increment MINOR
git push --follow-tags
```

While the API is stabilising we stay on `0.x.y` (`major_version_zero = true`, so a
breaking change bumps the minor). Never re-upload a version that already exists —
**PyPI rejects re-uploads**. In practice you rarely run this by hand: the
**Bump version** GitHub Action (§6) does it for you.

---

## 3. Build the distributions

```bash
uv build                       # writes dist/onveef-<ver>.tar.gz (sdist) + .whl
# stock equivalent:  python -m build
```

You want **both** artifacts:
- `*.whl` — the wheel users install.
- `*.tar.gz` — the source distribution.

Always build from a clean tree (`rm -rf dist build *.egg-info` first) so stale
files never sneak into the archive.

---

## 4. Validate the artifacts

```bash
uv run twine check dist/*      # verifies metadata + that the README renders on PyPI
uv run python -m tarfile -l dist/onveef-*.tar.gz   # eyeball the file list
```

`twine check` catching README render errors here saves you from a broken project
page. Confirm the sdist contains `src/onveef/*.py`, `README.md`, `LICENSE`,
`pyproject.toml` and **not** `.venv/`, `dist/`, or caches.

Optional but recommended smoke test in a throwaway env:
```bash
uv run --isolated --with dist/onveef-*.whl python -c "import onveef; print(onveef.__version__)"
```

---

## 5. Upload

**Always rehearse on TestPyPI first:**
```bash
uv run twine upload --repository testpypi dist/*
# then install it back from TestPyPI in a fresh env:
uv run --isolated --with onveef \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  python -c "import onveef, onveef.wsdiscovery; print('ok', onveef.__version__)"
```
(The extra index lets deps like `httpx`/`defusedxml` resolve from real PyPI.)

**When TestPyPI looks right, push to real PyPI:**
```bash
uv run twine upload dist/*
git push && git push --tags
```

Verify at `https://pypi.org/project/<name>/`, then:
```bash
pip install <name>             # from a clean machine/venv
```

---

## 6. Automated release (GitHub Actions)

Three workflows in `.github/workflows/` implement the whole loop — **no tokens
stored anywhere**:

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | every push / PR to `main` | ruff + mypy + pytest on Python 3.11–3.13 |
| `bump.yml` | manual (**Actions → Bump version → Run**) | `cz bump` → updates `__init__.py` + `CHANGELOG.md`, commits, tags `vX.Y.Z`, pushes |
| `release.yml` | a pushed `vX.Y.Z` tag | build → `twine check` → publish to PyPI → GitHub Release |

So the normal release is: land Conventional Commits on `main` → click **Run** on
*Bump version* → the new tag triggers *Release* → PyPI + a GitHub Release appear.
You can still tag manually (`uv run cz bump --yes && git push --follow-tags`) to
trigger `release.yml`.

### One-time setup

**1. PyPI Trusted Publishing** (no API token). Enable once at
<https://pypi.org/manage/account/publishing/> → *Add a pending publisher*:

- **PyPI project name:** `onveef` (your final name)
- **Owner / Repository:** `Akshat-Pandey16` / `onveef`
- **Workflow name:** `release.yml`
- **Environment name:** `pypi`

That binding lets the `pypi-publish` job (which requests `id-token: write` in the
`pypi` environment) upload without secrets.

**2. Turn publishing on.** The publish job is gated on a repo **variable** so a tag
never publishes by accident. In *Settings → Secrets and variables → Actions →
Variables*, add `PUBLISH_ENABLED = true` when you are ready to ship. Until then,
pushing a tag just builds and checks — it never uploads.

**3. Let the bump tag trigger a release.** A tag pushed with the built-in
`GITHUB_TOKEN` does **not** start other workflows, so `bump.yml` would otherwise
never fire `release.yml`. Create a fine-grained **PAT** (contents: read/write on
this repo) and add it as the secret `RELEASE_PAT`; `bump.yml` uses it to push so
the new tag triggers `release.yml`. (Without it, push the tag yourself to release.)
If `main` is branch-protected, also allow this actor to push, or change `bump.yml`
to open a PR instead of pushing to `main`.

---

## 7. Renaming

`onveef` is a placeholder chosen to avoid leading with the ONVIF trademark. To
rename to `<newname>` before first publish:

```bash
git grep -l onveef | xargs sed -i 's/onveef/<newname>/g'
git mv src/onveef src/<newname>
uv run pytest -q               # re-verify
```

Then update `[project].name` in `pyproject.toml` and the `[tool.hatch.build...]`
`packages` path.

---

## 8. Trademark / naming reminders

- You may state the library is **"compatible with ONVIF Profile S/T/G/M devices."**
- Do **not** claim it is "ONVIF conformant" or "ONVIF certified", and do not use
  the ONVIF logo — those require paid ONVIF membership and the official test tool.
- Prefer a distribution name that does **not** lead with `onvif` to reduce
  squatting/endorsement confusion.

---

## Quick reference

| Step | Command |
|------|---------|
| Install dev env | `uv sync --extra dev` |
| Lint + types + tests | `uv run ruff check src tests && uv run mypy && uv run pytest -q` |
| Build | `uv build` |
| Validate | `uv run twine check dist/*` |
| Upload (TestPyPI) | `uv run twine upload --repository testpypi dist/*` |
| Upload (PyPI) | `uv run twine upload dist/*` |
