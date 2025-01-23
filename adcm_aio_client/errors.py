# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


class ADCMClientError(Exception):
    pass


class WaitTimeoutError(ADCMClientError):
    pass


# Session


class ClientInitError(ADCMClientError):
    pass


# Version


class NotSupportedVersionError(ADCMClientError):
    pass


# Requester


class RequesterError(ADCMClientError):
    pass


class NoCredentialsError(RequesterError):
    pass


class AuthenticationError(RequesterError):
    pass


class LoginError(RequesterError):
    pass


class LogoutError(RequesterError):
    pass


class RetryRequestError(RequesterError):
    pass


class ResponseDataConversionError(RequesterError):
    pass


class UnknownError(RequesterError):
    pass


# >=400
class BadRequestError(UnknownError):
    pass


class UnauthorizedError(UnknownError):
    pass


class PermissionDeniedError(UnknownError):
    pass


class NotFoundError(UnknownError):
    pass


class ConflictError(UnknownError):
    pass


# >=500
class ServerError(UnknownError):
    pass


class BadGatewayError(ServerError):
    pass


class ServiceUnavailableError(ServerError):
    pass


# Objects


class AccessorError(ADCMClientError):
    pass


class MultipleObjectsReturnedError(AccessorError):
    pass


class ObjectDoesNotExistError(AccessorError):
    pass


class OperationError(AccessorError):
    pass


class HostNotInClusterError(ADCMClientError): ...


# Config


class ConfigError(ADCMClientError): ...


class ConfigComparisonError(ConfigError): ...


class ConfigNoParameterError(ConfigError): ...


# Action


class NoMappingInActionError(ADCMClientError): ...


class NoConfigInActionError(ADCMClientError): ...


# Filtering


class FilterError(ADCMClientError): ...


class InvalidFilterError(FilterError): ...
