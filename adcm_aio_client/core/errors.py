# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


class RequesterError(Exception):
    pass


class NoCredentialsError(RequesterError):
    pass


class LoginError(RequesterError):
    pass


class ReconnectError(RequesterError):
    pass


class ResponseError(RequesterError):
    pass


class RequesterResponseError(ResponseError):
    pass


class BadRequestError(ResponseError):
    pass


class UnauthorizedError(ResponseError):
    pass


class NotFoundError(ResponseError):
    pass


class ConflictError(ResponseError):
    pass


class ServerError(ResponseError):
    pass
