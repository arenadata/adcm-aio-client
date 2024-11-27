from typing import Self
import socket

from docker.errors import DockerException
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.waiting_utils import wait_container_is_ready, wait_for_logs
from testcontainers.postgres import PostgresContainer

postgres_image_name = "postgres:latest"
adcm_image_name = "hub.adsw.io/adcm/adcm:develop"
adcm_port_range = (8000, 8010)
postgres_port_range = (5432, 5442)
adcm_container_name = "test_adcm"
postgres_name = "test_pg_db"
db_user = "adcm"
db_name = "adcm"
db_password = "password"  # noqa: S105


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
        self.adcm_env_kwargs = {"STATISTICS_ENABLED": 0}
        self.network = network

    def setup_postgres(self: Self, username: str, password: str, adcm_db_name: str) -> None:
        postgres_port = find_free_port(postgres_port_range[0], postgres_port_range[1])

        self.adcm_env_kwargs = self.adcm_env_kwargs | {
            "DB_HOST": f"{postgres_name}_{postgres_port}",
            "DB_USER": db_user,
            "DB_NAME": db_name,
            "DB_PASS": db_password,
            "DB_PORT": str(postgres_port),
        }

        self.with_name(f"{postgres_name}_{postgres_port}")
        self.password = password
        self.with_network(self.network)
        self.with_bind_ports(postgres_port, postgres_port)

        self.start()
        wait_container_is_ready(self)

        self.exec(
            f"psql --username test --dbname postgres "
            f"-c \"CREATE USER {username} WITH ENCRYPTED PASSWORD '{db_password}';\""
        )
        self.exec(f"psql --username test --dbname postgres " f'-c "CREATE DATABASE {adcm_db_name} OWNER {username};"')

        wait_for_logs(self, "database system is ready to accept connections")


class ADCMContainer(DockerContainer):
    url: str

    def __init__(self: Self, image: str, network: Network, env_kwargs: dict) -> None:
        super().__init__(image)
        self.postgres_env_kwargs = {}
        self.network = network
        self.adcm_env_kwarg = env_kwargs

    def setup_container(self: Self) -> None:
        adcm_port = find_free_port(adcm_port_range[0], adcm_port_range[1])
        self.with_name(f"{adcm_container_name}_{adcm_port}")
        self.with_network(self.network)
        self.with_bind_ports(adcm_port, adcm_port)

        for key, value in self.postgres_env_kwargs.items():
            self.with_env(key, value)

        self.start()

        wait_container_is_ready(self)
        wait_for_logs(self, "Run Nginx ...")

        self.url = f"http://{self.get_container_host_ip()}:{self.get_exposed_port(adcm_port)}"


class DockerContainerError(DockerException):
    pass
