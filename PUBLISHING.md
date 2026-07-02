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

Single source of truth is `pyproject.toml` (`[project].version`). Keep
`src/onveef/__init__.py::__version__` and `DEFAULT_USER_AGENT` in sync.

- `0.x.y` while the API is stabilising (this is where we are).
- Follow [SemVer](https://semver.org/): breaking change → major, feature → minor,
  fix → patch. Record changes in `CHANGELOG.md`.
- Never re-upload a version that already exists on PyPI — **PyPI rejects
  re-uploads of the same version**. Bump, then build.

```bash
# after editing the version in pyproject.toml + __init__.py
git commit -am "release: v0.2.0"
git tag v0.2.0
```

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

Recommended: **PyPI Trusted Publishing** — no tokens stored anywhere. Configure it
once at <https://pypi.org/manage/account/publishing/> (bind repo + workflow +
environment), then use:

```yaml
# .github/workflows/release.yml
name: release
on:
  push:
    tags: ["v*"]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra dev
      - run: uv run ruff check src tests && uv run mypy && uv run pytest -q
      - run: uv build
      - uses: actions/upload-artifact@v4
        with: { name: dist, path: dist/ }
  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write            # required for Trusted Publishing (OIDC)
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Tag `vX.Y.Z` → CI builds, tests, and publishes. No secrets required.

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
