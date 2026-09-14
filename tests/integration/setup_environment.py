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

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Self
import ssl
import random
import socket
import string

from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.postgres import DbContainer, PostgresContainer

postgres_image_name = "postgres:latest"
adcm_image_name = "hub.adsw.io/adcm/adcm:develop"
adcm_container_name = "test_adcm"
postgres_name = "test_pg_db"

# for now runtime relies that those values are always used for their purpose
DB_USER = "adcm"
DB_PASSWORD = "password"  # noqa: S105


@dataclass(slots=True)
class DatabaseInfo:
    name: str

    host: str
    port: int = 5432


def wait_for_ssl_port_ready(host: str, port: int, timeout: float = 30.0, interval: float = 0.5) -> None:
    """
    `wait_for_logs` only proves the "starting nginx" log line was printed, not that nginx has
    actually bound the port and is serving valid TLS - e.g. if nginx can't read the SSL cert it
    crash-loops, reprinting that same log line on every retry while never becoming reachable.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    deadline = monotonic() + timeout
    last_err: Exception | None = None
    while monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval) as sock, context.wrap_socket(sock):
                return
        except OSError as e:
            last_err = e
            sleep(interval)

    message = f"ADCM did not start accepting TLS connections on {host}:{port} within {timeout}s"
    raise TimeoutError(message) from last_err


class ADCMPostgresContainer(PostgresContainer):
    def __init__(self: Self, image: str, network: Network) -> None:
        super().__init__(image)
        suffix = "".join(random.sample(string.ascii_letters, k=6)).lower()
        self.name = f"test_pg_db_{suffix}"
        self.with_name(self.name)
        self.with_network(network)

    def execute_statement(self: Self, statement: str, db_user: str = "test", db_name: str = "test") -> None:
        exit_code, out = self.exec(f'psql --username {db_user} --dbname {db_name} -c "{statement}"')
        if exit_code != 0:
            output = out.decode("utf-8")
            message = f"Failed to execute psql statement: {output}"
            raise RuntimeError(message)

    def start(self: Self) -> DbContainer:
        super().start()

        wait_for_logs(self, "database system is ready to accept connections")

        self.execute_statement(f"CREATE USER {DB_USER} WITH ENCRYPTED PASSWORD '{DB_PASSWORD}'")

        return self


class ADCMContainer(DockerContainer):
    url: str
    ssl_url: str

    def __init__(
        self: Self,
        image: str,
        network: Network,
        db: DatabaseInfo,
        *,
        migration_mode: bool = False,
        wait_for_ssl: bool = True,
    ) -> None:
        super().__init__(image)
        self._db = db
        self._migration_mode = migration_mode
        self._wait_for_ssl = wait_for_ssl

        self.with_network(network)

        self.with_env("MIGRATION_MODE", "1" if self._migration_mode else "0")
        self.with_env("STATISTICS_ENABLED", "0")
        self.with_env("DB_USER", DB_USER)
        self.with_env("DB_PASS", DB_PASSWORD)
        self.with_env("DB_NAME", self._db.name)
        self.with_env("DB_HOST", self._db.host)
        self.with_env("DB_PORT", str(self._db.port))

    def start(self: Self) -> Self:
        suffix = "".join(random.sample(string.ascii_letters, k=6)).lower()
        self.with_name(f"{adcm_container_name}_{suffix}")
        # Let Docker pick free host ports: probing for a free port in advance races with parallel workers
        self.with_exposed_ports(8000, 8443)

        super().start()

        ready_logs = "Run Nginx ..." if not self._migration_mode else "Run main wsgi application ..."
        wait_for_logs(self, ready_logs)

        ip = self.get_container_host_ip()
        port = self.get_exposed_port(8000)
        ssl_port = self.get_exposed_port(8443)
        self.url = f"http://{ip}:{port}"
        self.ssl_url = f"https://{ip}:{ssl_port}"

        if self._wait_for_ssl:
            wait_for_ssl_port_ready(ip, int(ssl_port))

        return self
