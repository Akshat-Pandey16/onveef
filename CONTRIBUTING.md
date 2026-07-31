# Contributing to onveef

Thanks for helping out. The most valuable contribution to this project is **recorded
responses from real devices** — see [Contributing fixtures](#contributing-fixtures) below.

## Development setup

```bash
uv sync --extra dev
uv run ruff check src tests
uv run ruff format src tests
uv run mypy
uv run pytest
```

All four must pass. `mypy` runs in `strict` mode over both `src` and `tests`, and the test
run enforces a coverage floor (see `[tool.pytest.ini_options]` in `pyproject.toml`).

Optionally install the git hooks: `uv run pre-commit install`.

## Design rules

- **The core is sans-IO.** `onveef.envelopes` builds request strings, `onveef.parsers`
  turns response strings into dicts, and neither ever touches the network. All I/O lives in
  `onveef.client` / `onveef.aclient`. Keep it that way — it is what makes the codec
  testable from recorded XML.
- **Two runtime dependencies.** `httpx` and `defusedxml`. A new runtime dependency needs a
  strong argument; test-only and docs-only dependencies are fine.
- **Sync and async stay in lockstep.** Every operation added to `OnvifClient` must be added
  to `AsyncOnvifClient` with the same name and signature. `tests/test_api_surface.py`
  fails the build if they diverge.
- **Never trust what a device says about itself.** Addresses a device reports (service
  XAddrs, subscription references, stream URIs) go through `onveef.urls.rewrite_host`.
- **Parsers must not raise.** A parser given empty, truncated or unexpected XML returns an
  empty result. `test_every_parser_tolerates_junk_input` enforces this over every parser.
- **Docstrings, not inline comments.** Explain intent in the docstring.

## Adding an operation

1. Add the request builder to `onveef/envelopes.py`.
2. Add the response parser to `onveef/parsers.py` (if the response carries data).
3. Add the method to **both** `onveef/client.py` and `onveef/aclient.py`.
4. Add a test asserting the envelope contains the right operation and that the parser
   returns what you expect.

`tests/test_api_surface.py` will automatically start exercising the new method. If it takes
arguments that cannot be guessed from their names or annotations, add an entry to the
`_BY_NAME` map there.

## Contributing fixtures

Recorded responses from real hardware are how this library stays compatible with the long
tail of firmware. To capture a set:

```bash
uv run onveef dump 192.168.1.64 -u admin -p secret -d tests/fixtures/<vendor>
```

Then add a test in `tests/test_fixtures.py` asserting the parsers extract sane values.

**Redact before committing.** Raw ONVIF responses routinely contain data you do not want in
a public repository:

| Redact | Where it appears |
|---|---|
| Serial numbers, hardware IDs | `GetDeviceInformation` |
| MAC addresses | `GetNetworkInterfaces` |
| Public/private IPs, hostnames | `GetNetworkInterfaces`, `GetServices`, `GetStreamUri` |
| Site or location names | `GetScopes`, recording configurations |
| Usernames | `GetUsers`, storage configurations |
| Passwords, credential tokens | storage configurations, `GetDot1XConfigurations` |

Replace them with obvious placeholders (`SN-REDACTED`, `00:11:22:33:44:55`, `192.168.1.64`)
rather than deleting the elements — the *shape* of the response is the thing being tested.
Keep the vendor's element ordering, namespace prefixes and quirks exactly as sent; those
quirks are the reason the fixture is worth having.

## Commits and releases

Commits follow [Conventional Commits](https://www.conventionalcommits.org/); `commitizen`
derives the version and changelog from them. Use `feat:`, `fix:`, `docs:`, `test:`,
`refactor:`, `build:`, `ci:`. Release steps live in [`PUBLISHING.md`](https://github.com/Akshat-Pandey16/onveef/blob/main/PUBLISHING.md).
