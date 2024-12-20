from dataclasses import dataclass
from typing import Self
import socket

from docker.errors import DockerException
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.waiting_utils import wait_container_is_ready, wait_for_logs
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


def find_free_port(start: int, end: int) -> int:
    """Try to find a free port in the given range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:  # Port is free
                return port
    raise DockerContainerError(f"No free ports found in the range {start} to {end}")


class ADCMPostgresContainer(PostgresContainer):
    def __init__(self: Self, image: str, network: Network) -> None:
        super().__init__(image)
        self.name = postgres_name
        self.with_name(self.name)
        self.with_network(network)

    def execute_statement(self: Self, statement: str) -> None:
        exit_code, out = self.exec(f'psql --username test --dbname test -c "{statement}"')
        if exit_code != 0:
            output = out.decode("utf-8")
            message = f"Failed to execute psql statement: {output}"
            raise RuntimeError(message)

    def start(self: Self) -> DbContainer:
        super().start()

        wait_container_is_ready(self)
        wait_for_logs(self, "database system is ready to accept connections")

        self.execute_statement(f"CREATE USER {DB_USER} WITH ENCRYPTED PASSWORD '{DB_PASSWORD}'")

        return self


class ADCMContainer(DockerContainer):
    url: str

    def __init__(self: Self, image: str, network: Network, db: DatabaseInfo) -> None:
        super().__init__(image)
        self._db = db

        self.with_network(network)

        self.with_env("STATISTICS_ENABLED", "0")
        self.with_env("DB_USER", DB_USER)
        self.with_env("DB_PASS", DB_PASSWORD)
        self.with_env("DB_NAME", self._db.name)
        self.with_env("DB_HOST", self._db.host)
        self.with_env("DB_PORT", str(self._db.port))

    def start(self: Self) -> Self:
        adcm_port = find_free_port(start=8000, end=8080)
        self.with_bind_ports(8000, adcm_port)

        self.with_name(f"{adcm_container_name}_{adcm_port}")

        super().start()

        wait_container_is_ready(self)
        wait_for_logs(self, "Run Nginx ...")

        ip = self.get_container_host_ip()
        port = self.get_exposed_port(8000)
        self.url = f"http://{ip}:{port}"

        return self


class DockerContainerError(DockerException):
    pass
