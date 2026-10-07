# Contributing to WAMBLE

Thanks for taking the time to help with WAMBLE. Every kind of contribution is
welcome, and you do not need to be a Bluetooth expert to make a useful one.

This is a small, best-effort project maintained in spare time. Please read the
[Code of Conduct](CODE_OF_CONDUCT.md) and the [Security Policy](SECURITY.md)
before you start. The short version of the security policy: only use WAMBLE on
devices you own or have written permission to test.

## Ways to contribute

You do not have to write code to be helpful.

- **Report a bug.** Open an issue with what you did, what you expected, and what
  happened instead.
- **Report device compatibility.** WAMBLE is developed on macOS. If you run it on
  Windows, or against a device that behaves oddly, a short report helps a lot.
  There is a device report template for this.
- **Improve the docs.** Fixing a confusing sentence in the README or the
  cheatsheet is a real contribution.
- **Add or improve a utility.** New `gatttool`-style tools and better handling of
  real-world devices are both welcome.
- **Add tests.** More coverage of the GATT helpers is always useful.

Good first tasks are labelled `good first issue` in the issue tracker.

## Setting up a development environment

You need Python 3.11 or newer and a machine with Bluetooth.

```bash
git clone <your-fork-url>
cd WAMBLE
python3 -m venv .venv
source .venv/bin/activate      # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .               # editable install: wamble-* commands + importable package
```

The toolkit is the `wamble` package under `src/`. The tests find it via
`pythonpath = src` (see `pytest.ini`), so they run without an install, but an
editable install is the easiest way to also get the `wamble-*` commands.

## Running the tests

The test suite is fast and does not need a real Bluetooth device. It uses fake
clients, so you can run it anywhere.

```bash
python -m pytest -q
```

Before you open a pull request, run the same checks CI runs. Installing the
requirements installs all of the tools:

```bash
python -m pytest -q                                   # tests
ruff check .                                           # redundancy, slow patterns, complexity
ruff format --check .                                  # formatting
vulture src/wamble --min-confidence 80                 # dead code
pylint --disable=all --enable=duplicate-code src/wamble # duplicate logic
```

CI runs these on every push and pull request, so a change that adds dead code,
duplicated logic, an unused import, or a slow pattern will fail the build. Run
`ruff check --fix .` and `ruff format .` to fix most findings automatically.

If your change could affect a real device, say so in the pull request and
describe what you tested it against. Testing on hardware is appreciated but not
required, because not everyone has the same devices.

## Coding style

- Match the style of the code around your change. Keep functions small and give
  them clear names.
- Write comments that explain why something is done, not what the line does.
- Shared Bluetooth logic belongs in `wamble/common.py` or `wamble/gatt.py` so
  the front-end tools stay thin. Please do not copy a helper into several files.
- Keep user-facing text plain and friendly.

## Submitting a change

1. Fork the repository and create a branch for your change.
2. Make the change, run the tests, and keep commits focused.
3. Open a pull request using the template. Reference any related issue, and
   describe what you changed and how you checked it.
4. Add a `Signed-off-by` line to your commits to confirm you have the right to
   contribute the code (see below). `git commit -s` adds it for you.

A maintainer will try to respond within about a week. If a change does not fit
the scope of the project, you will get a clear reason why, and a suggestion for
what to do instead where possible.

## Sign-off (Developer Certificate of Origin)

WAMBLE uses the [Developer Certificate of Origin](https://developercertificate.org/).
It is a lightweight way to confirm that you wrote the contribution, or otherwise
have the right to submit it under the project's license. There is no separate
agreement to sign. You add one line to each commit:

```
Signed-off-by: Your Name <your.email@example.com>
```

Run `git commit -s` and git adds it from your configured name and email.

## Questions

If you are unsure about anything, open an issue or see [SUPPORT.md](SUPPORT.md).
Asking is welcome.
