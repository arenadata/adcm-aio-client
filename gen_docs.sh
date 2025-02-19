#!/bin/bash

poetry run sphinx-apidoc --ext-viewcode --ext-autodoc --separate --private --module-first -o docs/api adcm_aio_client
poetry run sphinx-build docs docs-out
