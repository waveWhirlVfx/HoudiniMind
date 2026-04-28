# Contributing to HoudiniMind

First off, thank you for considering contributing to HoudiniMind! It's people like you that make HoudiniMind such a great tool for the VFX community.

## Where do I go from here?

If you've noticed a bug or have a feature request, make sure to check our [Issues](https://github.com/waveWhirlVfx/houdinimind/issues) page to see if someone else in the community has already created a ticket. If not, go ahead and make one!

## Development Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/waveWhirlVfx/houdinimind.git
   cd houdinimind
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. Setup pre-commit hooks:
   ```bash
   pre-commit install
   ```

## Testing

The test suite does **not** require a Houdini install. A stub `hou` module (`tests/fake_hou.py`) is used for testing logic outside of Houdini.

To run tests:
```bash
pytest
```

## Pull Requests

1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints (via `ruff`).
6. Issue that pull request!

## Code Style

This project uses `ruff` and `mypy` for linting and type checking, and `black` for formatting.

Run `ruff check .` to check for linting errors.
Run `mypy src/houdinimind` to check for type errors.

## Community

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in all interactions with the project.
