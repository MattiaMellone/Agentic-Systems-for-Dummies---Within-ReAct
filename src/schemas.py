"""Schemas module.

This code is organized for readability, maintainability, and testability."""

DATE_MATH_SCHEMA = {'type': 'object', 'properties': {'operation': {'type': 'string', 'enum': ['add', 'sub', 'diff', 'range']}, 'date': {'type': 'string'}, 'days': {'type': 'integer'}, 'end_date': {'type': 'string'}}, 'required': ['operation'], 'additionalProperties': False}
TAVILY_SEARCH_SCHEMA = {'type': 'object', 'properties': {'query': {'type': 'string'}, 'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 10}}, 'required': ['query'], 'additionalProperties': False}
OPENMETEO_FORECAST_SCHEMA = {'type': 'object', 'properties': {'location': {'type': 'string'}, 'target_date': {'type': 'string'}, 'units': {'type': 'string', 'enum': ['metric', 'imperial'], 'default': 'metric'}, 'days': {'type': 'integer', 'minimum': 1, 'maximum': 16}}, 'required': ['location'], 'additionalProperties': False}
OPENMETEO_ARCHIVE_SCHEMA = {'type': 'object', 'properties': {'location': {'type': 'string'}, 'start_date': {'type': 'string'}, 'end_date': {'type': 'string'}, 'units': {'type': 'string', 'enum': ['metric', 'imperial'], 'default': 'metric'}}, 'required': ['location', 'start_date', 'end_date'], 'additionalProperties': False}
