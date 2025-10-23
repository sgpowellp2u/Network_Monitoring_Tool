import time
import socket
import threading
from datetime import datetime
import ipaddress
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, List
from rich.table import Table
from rich.console import Console
from rich.live import Live
from ping3 import ping


class HostResult:
    """Stores the monitoring results for a single host."""

    def __init__(self, host: str, name: str = "", history_size: int = 10):
        self.host: str = host
        self.name: str = name  # Friendly name
        self.response: str = "unavailable"
        self.history: deque = deque(maxlen=history_size)
        self.avg_latency: float = 0.0
        self.latency_change: str = ""
        self.host_name: str = host
        self.success_rate: float = 0.0
        self.test_count: int = 0
        self.last_update: datetime = datetime.now()
        self.jitter: float = 0.0

    def update(self, latency: Optional[float]):
        self.test_count += 1
        self.last_update = datetime.now()

        if latency is None:
            self.response = "unavailable"
            self.history.append(None)
        else:
            latency_ms = latency * 1000
            self.response = f"{latency_ms:.2f} ms"
            self.history.append(latency_ms)

        self.calculate_metrics()

    def calculate_metrics(self):
        non_none_history = [lat for lat in self.history if lat is not None]

        if non_none_history:
            new_avg = sum(non_none_history) / len(non_none_history)
            if self.avg_latency:
                if new_avg > self.avg_latency:
                    self.latency_change = "[red]↑[/]"
                elif new_avg < self.avg_latency:
                    self.latency_change = "[green]↓[/]"
                else:
                    self.latency_change = "-"
            self.avg_latency = new_avg
            self.jitter = max(non_none_history) - min(non_none_history)
            self.success_rate = (len(non_none_history) / len(self.history)) * 100
        else:
            self.avg_latency = 0.0
            self.jitter = 0.0
            self.success_rate = 0.0
            self.latency_change = "-"


class NetworkMonitor:
    """Monitors multiple hosts and displays a live table."""

    def __init__(self, hosts_file: str = "hosts.txt", ping_interval: float = 1.0, history_size: int = 10):
        self.hosts_file = hosts_file
        self.ping_interval = ping_interval
        self.history_size = history_size
        self.results: Dict[str, HostResult] = {}
        self.console = Console()
        self._load_hosts()

    def _load_hosts(self) -> List[str]:
        """Loads hosts from file, supporting optional friendly names."""
        try:
            with open(self.hosts_file, "r") as file:
                raw_hosts = [line.strip() for line in file if line.strip()]

            expanded_hosts = []
            for line in raw_hosts:
                if ',' in line:
                    ip_part, name_part = line.split(',', 1)
                    ip_part = ip_part.strip()
                    name_part = name_part.strip()
                else:
                    ip_part = line.strip()
                    name_part = ""

                hosts_from_line = self._expand_hosts([ip_part])
                for host in hosts_from_line:
                    self.results[host] = HostResult(host, name_part, self.history_size)
                    expanded_hosts.append(host)

            return expanded_hosts
        except FileNotFoundError:
            self.console.print(f"[bold red]Error:[/] '{self.hosts_file}' file not found.")
            raise

    def _expand_hosts(self, hosts: List[str]) -> List[str]:
        expanded = []
        for host in hosts:
            if '/' in host:
                try:
                    network = ipaddress.IPv4Network(host, strict=False)
                    expanded.extend([str(ip) for ip in network.hosts()])
                except ValueError:
                    self.console.print(f"[yellow]Warning:[/] Invalid CIDR: {host}")
            elif '-' in host:
                try:
                    start_ip_str, end_ip_str = host.split('-')
                    start_ip = ipaddress.IPv4Address(start_ip_str.strip())
                    end_ip = ipaddress.IPv4Address(end_ip_str.strip())
                    if start_ip > end_ip:
                        self.console.print(f"[yellow]Warning:[/] Start IP > End IP: {host}")
                        continue
                    current_ip = start_ip
                    while current_ip <= end_ip:
                        expanded.append(str(current_ip))
                        current_ip += 1
                except ValueError:
                    self.console.print(f"[yellow]Warning:[/] Invalid range: {host}")
            else:
                expanded.append(host)
        return expanded

    def _resolve_hostname(self, host: str) -> str:
        try:
            return socket.gethostbyaddr(host)[0]
        except socket.herror:
            return host

    def _ping_host(self, host: str):
        host_result = self.results[host]
        host_result.host_name = self._resolve_hostname(host)

        while True:
            try:
                latency = ping(host, timeout=2)
            except Exception as e:
                self.console.print(f"[red]Error pinging {host}: {e}[/]")
                latency = None

            host_result.update(latency)
            time.sleep(self.ping_interval)

    def _start_pinging(self, hosts: List[str]):
        with ThreadPoolExecutor(max_workers=len(hosts)) as executor:
            for host in hosts:
                executor.submit(self._ping_host, host)

    def _create_table(self) -> Table:
        table = Table(show_header=True, header_style="bold magenta")
        # Add columns with no_wrap to shrink
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Host", no_wrap=True)
        table.add_column("Name", no_wrap=True)
        table.add_column("Hostname", no_wrap=True)
        table.add_column("Ping Response", no_wrap=True)
        table.add_column("Avg Latency", no_wrap=True)
        table.add_column("Change", no_wrap=True)
        table.add_column("Success %", no_wrap=True)
        table.add_column("Count", no_wrap=True)
        table.add_column("Last Update", no_wrap=True)
        table.add_column("Jitter", no_wrap=True)

        low_latency = 50
        medium_latency = 150

        for idx, host in enumerate(self.results.keys(), start=1):
            result = self.results[host]

            row_style = "on red" if result.response == "unavailable" else ""

            if result.response == "unavailable" or result.avg_latency == 0:
                avg_latency_display = "N/A"
                avg_latency_style = "on red"
            else:
                avg_latency_display = f"{result.avg_latency:.2f} ms"
                if result.avg_latency <= low_latency:
                    avg_latency_style = "on green"
                elif result.avg_latency <= medium_latency:
                    avg_latency_style = "on yellow"
                else:
                    avg_latency_style = "on red"

            ping_response_style = "on red" if result.response == "unavailable" else ""

            table.add_row(
                str(idx),
                result.host,
                result.name,
                result.host_name,
                (f"[{ping_response_style}]{result.response}[/{ping_response_style}]" if ping_response_style else result.response),
                (f"[{avg_latency_style}]{avg_latency_display}[/{avg_latency_style}]" if avg_latency_style else avg_latency_display),
                result.latency_change or "-",
                f"{result.success_rate:.2f} %" if result.history else "0.00 %",
                str(result.test_count),
                result.last_update.strftime('%H:%M:%S'),
                f"{result.jitter:.2f} ms" if result.jitter else "0.00 ms",
                style=row_style
            )

        return table

    def display(self):
        with Live(self._create_table(), refresh_per_second=1, console=self.console) as live:
            while True:
                live.update(self._create_table())
                time.sleep(1)

    def run(self):
        try:
            hosts = list(self.results.keys())
            if not hosts:
                self.console.print("[bold yellow]No hosts to monitor.[/]")
                return

            threading.Thread(target=self._start_pinging, args=(hosts,), daemon=True).start()
            self.display()
        except KeyboardInterrupt:
            self.console.print("\n[bold red]Monitoring stopped by user.[/]")


def main():
    monitor = NetworkMonitor(hosts_file="hosts.txt", ping_interval=1.0, history_size=10)
    monitor.run()


if __name__ == "__main__":
    main()
