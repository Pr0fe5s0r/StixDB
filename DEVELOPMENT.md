# StixDB Development and Publishing

This guide is for maintainers and contributors who want to build, test, and publish StixDB.

## Environment Setup

### Install Development Dependencies
```bash
pip install -e ".[dev]"
```

### Running Tests
```bash
pytest tests/ -v
```

---

## Publishing to PyPI

### Prerequisites
1. **Create a PyPI account**: Register at [pypi.org](https://pypi.org).
2. **API Token**: Generate a token at `Account settings → API tokens`.
3. **Install build tools**:
   ```bash
   pip install build twine hatch
   ```

### Publishing `stixdb-engine`
From the repository root:
1. Update version in `pyproject.toml` and `stixdb/__init__.py`.
2. Build:
   ```bash
   python -m build
   ```
3. Upload:
   ```bash
   twine upload dist/*
   ```

### Publishing `stixdb-sdk`
From the `sdk/` directory:
1. Update version in `sdk/pyproject.toml` and `sdk/src/stixdb_sdk/__init__.py`.
2. Build:
   ```bash
   python -m build
   ```
3. Upload:
   ```bash
   twine upload dist/*
   ```

---

## Versioning Checklist
Before a release, ensure you:
- [ ] Update `version` in `pyproject.toml` (Engine)
- [ ] Update `version` in `sdk/pyproject.toml` (SDK)
- [ ] Update `__version__` in `stixdb/__init__.py`
- [ ] Update `__version__` in `sdk/src/stixdb_sdk/__init__.py`
- [ ] Update `CHANGELOG.md`
- [ ] Create a Git tag (e.g., `v0.1.1`)
- [ ] Push tags: `git push --tags`
