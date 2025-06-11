"""
Scan and count the native docker compose
"""

import json
import socket
import subprocess
from pathlib import Path
from typing import Dict, Optional
from typing import List

import yaml
from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import track
from rich.table import Table
from tnt.tools.constant import STORAGE_DIR

console = Console()

storage_dir = STORAGE_DIR


class Service(BaseModel):
    # == services configuration == #
    name: str = Field(description="Service name")
    image: str = Field(description="Image name")
    restart: str = Field(default="")
    container_name: str = Field(default="")
    networks: List[str] = Field(default_factory=list)
    env_file: List[str] = Field(default_factory=list)
    ports: List[int] = Field(default_factory=list)
    volumes: List[str] = Field(default_factory=list)
    is_depend_on_gpu: bool = Field(default=False)

    # == running info == #
    container_env: List[str] = Field(
        default_factory=list,
        description="Environment variables from running service via docker compose exec",
    )


class Composer(BaseModel):
    hostname: str = Field(default="default")
    name: str = Field(
        default="",
        description="If not specified, use the absolute path of docker-compose.yaml work_dir",
    )
    status: str
    config_files: Path
    services: List[Service] = Field(description="Services in docker-compose.yaml")


def run_command(command: str, cwd: Optional[str] = None) -> str:
    """Execute command and return output"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
        if result.returncode != 0:
            console.print(f"[red]Command execution failed:[/red] {command}")
            console.print(f"[red]Error message:[/red] {result.stderr}")
            return ""
        return result.stdout.strip()
    except Exception as e:
        console.print(f"[red]Error occurred while executing command:[/red] {e}")
        return ""


def get_running_composers() -> List[Dict]:
    """Get all running docker compose projects"""
    cmd = "docker compose ls --format json"
    output = run_command(cmd)
    if not output:
        return []

    try:
        composers = json.loads(output)
        return composers
    except json.JSONDecodeError:
        console.print("[red]Failed to parse docker compose ls output[/red]")
        return []


def get_running_services(project_name: str, work_dir: str) -> List[Dict]:
    """Get running services in specified project"""
    cmd = f"docker compose -p {project_name} ps --format json"
    output = run_command(cmd, cwd=work_dir)
    if not output:
        return []

    try:
        # Output might be multi-line JSON, one service per line
        services = []
        for line in output.strip().split("\n"):
            if line:
                services.append(json.loads(line))
        return services
    except json.JSONDecodeError:
        console.print(f"[red]Failed to parse service list for project {project_name}[/red]")
        return []


def parse_compose_file(file_path: Path) -> Dict:
    """Parse docker-compose.yaml file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        console.print(f"[red]Failed to parse compose file {file_path}:[/red] {e}")
        return {}


def get_container_env(container_name: str) -> List[str]:
    """Get container environment variables"""
    cmd = f"docker exec {container_name} env"
    output = run_command(cmd)
    if output:
        return output.strip().split("\n")
    return []


def extract_service_config(service_name: str, service_config: Dict, running_info: Dict) -> Service:
    """Extract service information from configuration"""
    service = Service(
        name=service_name,
        image=service_config.get("image", ""),
        restart=service_config.get("restart", ""),
        container_name=service_config.get("container_name", ""),
        networks=(
            list(service_config.get("networks", {}).keys())
            if isinstance(service_config.get("networks"), dict)
            else service_config.get("networks", [])
        ),
        env_file=(
            service_config.get("env_file", [])
            if isinstance(service_config.get("env_file"), list)
            else [service_config.get("env_file")] if service_config.get("env_file") else []
        ),
        ports=[],
        volumes=service_config.get("volumes", []),
        is_depend_on_gpu=False,
    )

    # Parse port mapping
    ports_config = service_config.get("ports", [])
    for port in ports_config:
        if isinstance(port, str):
            # Format might be "8080:80" or "80"
            port_parts = port.split(":")
            if len(port_parts) >= 2:
                try:
                    service.ports.append(int(port_parts[0]))
                except ValueError:
                    pass
            elif len(port_parts) == 1:
                try:
                    service.ports.append(int(port_parts[0]))
                except ValueError:
                    pass
        elif isinstance(port, dict):
            # New long format
            if "published" in port:
                try:
                    service.ports.append(int(port["published"]))
                except ValueError:
                    pass

    # Check if depends on GPU
    deploy_config = service_config.get("deploy", {})
    if "resources" in deploy_config:
        reservations = deploy_config["resources"].get("reservations", {})
        if "devices" in reservations:
            for device in reservations["devices"]:
                if device.get("driver") == "nvidia":
                    service.is_depend_on_gpu = True
                    break

    # Get container environment variables
    container_name = running_info.get("Name", "")
    if container_name:
        service.container_env = get_container_env(container_name)

    return service


def scan_docker_composes() -> List[Composer]:
    """Scan all running docker compose projects"""
    composers = []
    running_composers = get_running_composers()

    for composer_info in track(
        running_composers, description="Scanning docker compose projects..."
    ):
        project_name = composer_info.get("Name", "")
        config_files = composer_info.get("ConfigFiles", "").split(",")
        status = composer_info.get("Status", "")

        if not project_name or not config_files:
            continue

        # Use the first configuration file
        config_file = Path(config_files[0].strip())
        work_dir = config_file.parent

        # Create Composer object
        composer = Composer(
            hostname=socket.gethostname(),
            name=project_name,
            status=status,
            config_files=config_file,
            services=[],
        )

        # Get running services
        running_services = get_running_services(project_name, str(work_dir))
        if not running_services:
            continue

        # Parse compose file
        compose_config = parse_compose_file(config_file)
        services_config = compose_config.get("services", {})

        # Only process running services
        for running_service in running_services:
            service_name = running_service.get("Service", "")
            if service_name in services_config:
                service = extract_service_config(
                    service_name, services_config[service_name], running_service
                )
                composer.services.append(service)

        composers.append(composer)

    return composers


def save_to_json(composers: List[Composer], output_file: str = "docker_compose_stats.json"):
    """Save results to JSON file"""
    data = []
    for composer in composers:
        # Use mode='json' to automatically handle Path object serialization
        data.append(composer.model_dump(mode="json"))

    storage_path = storage_dir.joinpath(output_file)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    console.print(f"[green]Results saved to {output_file}[/green]")


def display_results(composers: List[Composer]):
    """Display scan results in a nice table format"""
    table = Table(title="Docker Compose Projects Scan Results")

    table.add_column("Project Name", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")
    table.add_column("Services Count", justify="right", style="green")
    table.add_column("GPU Services", justify="right", style="yellow")
    table.add_column("Total Ports", justify="right", style="blue")

    for composer in composers:
        gpu_services = sum(1 for service in composer.services if service.is_depend_on_gpu)
        total_ports = sum(len(service.ports) for service in composer.services)

        table.add_row(
            composer.name,
            composer.status,
            str(len(composer.services)),
            str(gpu_services),
            str(total_ports),
        )

    console.print(table)


def main(is_to_excel: bool = False, is_visualize: bool = False):
    """Main function"""
    console.print("[bold blue]Starting Docker Compose services scan...[/bold blue]")
    composers = scan_docker_composes()

    if not composers:
        console.print("[yellow]No running Docker Compose projects found[/yellow]")
        return

    console.print(f"[green]Found {len(composers)} running projects[/green]")

    display_results(composers)

    for composer in composers:
        console.print(
            f"  - [cyan]{composer.name}[/cyan]: [green]{len(composer.services)}[/green] services"
        )

    save_to_json(composers, output_file=f"docker_compose_stats_{composers[0].hostname}.json")


if __name__ == "__main__":
    main()
