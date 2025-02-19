#!/bin/bash

poetry run sphinx-apidoc --ext-viewcode --ext-autodoc --separate --private -o docs/api adcm_aio_client
poetry run sphinx-build docs docs-out
