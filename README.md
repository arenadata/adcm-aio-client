# ADCM AIO Client

Asynchronous Client for ADCM (Arenadata Cluster Manager).

> The client supports the minimum version of ADCM `2.5.0`.

## Introduction

Install `adcm-aio-client` using `pip`.

> `adcm-aio-client` requires Python 3.12+.

```shell
pip install adcm-aio-client
```

## QuickStarts

To work with clusters, you need to connect to the backend of an existing ADCM.

First, set up your credentials:

```python
from adcm_aio_client import ADCMSession, Credentials

credentials = Credentials(username="admin", password="admin")
```

Second, you need to get session with ADCM backend:

```python
async with ADCMSession(url="http://127.0.0.1:8000", credentials=credentials) as client:
    clusters = await client.clusters.all()
```

The full list of available APIs can be found in the [Guides](#guides) section.

## Guides

- Examples of the available API for the `Bundle` entity can be found [here](/tests/integration/examples/test_bundle.py)
- Examples of the available API for the `Cluster` entity can be
  found [here](/tests/integration/examples/test_cluster.py)
- Examples of the available API for the `Service` entity can be
  found [here](/tests/integration/examples/test_service.py)
- Examples of the available API for the `Hostprovider` entity can be
  found [here](/tests/integration/examples/test_hostprovider.py)
- Examples of the available API for the `Host` entity can be found [here](/tests/integration/examples/test_host.py)
- Examples of the available API for the `Host Group` entity can be
  found [here](/tests/integration/examples/test_host_groups.py)

## Contributing

### Development

To start developing ADCM AIO Client create a fork of
the [ADCM AIO Client repository](https://github.com/arenadata/adcm-aio-client) on GitHub.

Then clone your fork with the following command replacing YOUR-USERNAME with your GitHub username:

```shell
git clone https://github.com/<YOUR-USERNAME>/adcm-aio-client.git
```

We use [Poetry](https://python-poetry.org/) to automate testing and linting. You
need [installed](https://python-poetry.org/docs/#installation) Poetry version at least 2.0.0.

You can now install the project and its dependencies using:

```shell
poetry install
```

### Linting

The project uses the [ruff](https://github.com/astral-sh/ruff) formatter to preserve the source code
style. [Pyright](https://github.com/microsoft/pyright) is used for static type checking.

To install the dependencies, run:

```shell
poetry install --with dev
```

To check the code style, run:

```shell
poetry run ruff check
```

To check the types, run:

```shell
poetry run pyright
```

To run the code auto-formatting:

```shell
poetry run ruff format
poetry run ruff check --fix
```

### Testing

For testing, we use [pytest](https://docs.pytest.org/en/stable/index.html).

To install the dependencies, run:

```shell
poetry install --with test
```

To run the unit tests:

```shell
poetry run pytest tests/unit
```

To run the integration tests:

```shell
poetry run pytest/integration
```
