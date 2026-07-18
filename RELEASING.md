# Releasing bhajan

GitHub installation is the default distribution path and does not require a
package-registry account:

```powershell
uv tool install --force https://github.com/rithamnatani/bhajan/archive/refs/heads/main.zip
```

## Publishing to PyPI

The `bhajan` project name was unclaimed on PyPI when this release process was
written. Publishing it requires a PyPI account and either:

- an API token exported as `UV_PUBLISH_TOKEN`, or
- a trusted publisher configured for this GitHub repository.

Build and inspect the distributions:

```bash
uv build
uvx twine check dist/*
```

Publish with an API token:

```bash
export UV_PUBLISH_TOKEN=pypi-...
uv publish
```

PowerShell:

```powershell
$env:UV_PUBLISH_TOKEN = "pypi-..."
uv publish
```

Once the first release exists on PyPI, users can install it with:

```bash
uv tool install bhajan
```

Do not commit or paste a PyPI token into an issue, pull request, or terminal log.
