from adcm_aio_client.core.errors import ADCMClientError


class ConfigError(ADCMClientError): ...


class ParameterNotFoundError(ConfigError): ...


class ParameterTypeError(ConfigError): ...
