"""CLI entry point for GivLocally."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict

import click
from rich.console import Console

from .config import InverterConfig
from .display import print_snapshot
from .forecast import fetch_forecast, required_overnight_soc
from .reader import InverterReader
from .settings import (
    default_host, default_port, default_batteries, default_inv_type,
    load as load_settings, save as save_settings, config_path, DEFAULTS,
)
from .writer import InverterWriter

err = Console(stderr=True)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """GivLocally — local control of GivEnergy inverters without the cloud."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command("read")
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--batteries",
    default=default_batteries,
    show_default="1",
    envvar="GIVENERGY_BATTERIES",
    help="Number of battery packs connected.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--output",
    type=click.Choice(["pretty", "json"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_read(
    host: str,
    port: int,
    batteries: int,
    retries: int,
    output: str,
    verbose: bool,
) -> None:
    """Read all settings and real-time data from the inverter."""

    _setup_logging(verbose)

    config = InverterConfig(
        host=host,
        port=port,
        number_batteries=batteries,
        retries=retries,
    )

    try:
        reader = InverterReader(config)
        snapshot = reader.read_all()
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    if output == "json":
        data = asdict(snapshot)
        # Convert datetime to ISO string for JSON serialisation
        if data.get("system_time") is not None:
            data["system_time"] = str(data["system_time"])
        click.echo(json.dumps(data, indent=2))
    else:
        print_snapshot(snapshot)


@cli.command("summary")
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_summary(host: str, port: int, retries: int, verbose: bool) -> None:
    """Print a one-line summary of current inverter state."""
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        snap = InverterReader(config).read_all()
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    Console().print(_summary_text(snap))


def _summary_text(snap) -> str:
    """Return a Rich markup string summarising the inverter state."""
    solar_kw = (snap.p_pv1_w + snap.p_pv2_w) / 1000
    load_kw = snap.p_load_w / 1000
    bat_kw = abs(snap.p_battery_w) / 1000
    grid_kw = abs(snap.p_grid_w) / 1000
    soc = snap.battery_soc_pct

    if snap.p_battery_w > 50:
        bat_status = f"[cyan]discharging {bat_kw:.2f} kW[/cyan]"
    elif snap.p_battery_w < -50:
        bat_status = f"[yellow]charging {bat_kw:.2f} kW[/yellow]"
    else:
        bat_status = "[dim]idle[/dim]"

    if snap.p_grid_w > 50:
        grid_status = f"exporting [green]{grid_kw:.2f} kW[/green]"
    elif snap.p_grid_w < -50:
        grid_status = f"importing [red]{grid_kw:.2f} kW[/red]"
    else:
        grid_status = "[dim]idle[/dim]"

    return (
        f"Solar [green]{solar_kw:.2f} kW[/green]  "
        f"Load [red]{load_kw:.2f} kW[/red]  "
        f"Grid {grid_status}  "
        f"Battery {bat_status} @ [bold]{soc}%[/bold]"
    )


@cli.command("monitor")
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--interval",
    default=60,
    show_default=True,
    type=click.IntRange(1, 300),
    help="Seconds between updates.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_monitor(host: str, port: int, retries: int, interval: int, verbose: bool) -> None:
    """Live-updating summary that refreshes every interval seconds. Press Ctrl+C to exit."""
    import asyncio
    import time
    from datetime import datetime
    from rich.live import Live
    from rich.text import Text
    from givlocally.reader import _read_async

    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)

    console = Console()
    console.print(f"[dim]Monitoring — updates every {interval}s. Press Ctrl+C to exit.[/dim]\n")

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                try:
                    snap = asyncio.run(_read_async(config))
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    text = Text.from_markup(f"[dim]{timestamp}[/dim]  {_summary_text(snap)}")
                except KeyboardInterrupt:
                    raise
                except (Exception, asyncio.CancelledError) as exc:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    text = Text.from_markup(
                        f"[dim]{timestamp}[/dim]  [bold red]Error:[/bold red] {exc}  "
                        f"[dim](retrying in {interval}s)[/dim]"
                    )
                live.update(text)
                time.sleep(interval)
    except KeyboardInterrupt:
        pass


@cli.group("charge-slot")
def charge_slot_group() -> None:
    """Manage timed charge slots on the inverter."""


@charge_slot_group.command("set")
@click.argument("slot", type=click.IntRange(1, 10))
@click.argument("start")
@click.argument("end")
@click.argument("target_soc", metavar="SOC", type=click.IntRange(4, 100))
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_charge_slot_set(
    slot: int,
    start: str,
    end: str,
    target_soc: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Configure a timed charge slot.

    \b
    Arguments:
      SLOT   Slot number to configure (1–10).
      START  Time to start charging, in HH:MM format.
      END    Time to stop charging, in HH:MM format.
      SOC    Target state of charge in percent (4–100). The inverter stops
             charging early if the battery reaches this level before END.

    \b
    Examples:
      givlocally charge-slot set 1 01:00 05:00 100
          Slot 1: charge from 01:00 to 05:00, fill to 100%.
      givlocally charge-slot set 2 23:30 06:00 80
          Slot 2: charge from 23:30 to 06:00, stop at 80%.
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).set_charge_slot(slot, start, end, target_soc)
        err.print(f"[green]Charge slot {slot} set to {start} → {end} @ {target_soc}%[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@charge_slot_group.command("clear")
@click.argument("slot", type=click.IntRange(1, 10))
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_charge_slot_clear(
    slot: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Disable charge SLOT by resetting its times to 00:00.

    SLOT is 1–10.

    Example: givlocally charge-slot clear 1
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).clear_charge_slot(slot)
        err.print(f"[green]Charge slot {slot} cleared[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@cli.group("discharge-slot")
def discharge_slot_group() -> None:
    """Manage timed discharge slots on the inverter."""


@discharge_slot_group.command("set")
@click.argument("slot", type=click.IntRange(1, 10))
@click.argument("start")
@click.argument("end")
@click.argument("floor_soc", metavar="SOC", type=click.IntRange(4, 100))
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_discharge_slot_set(
    slot: int,
    start: str,
    end: str,
    floor_soc: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Configure a timed discharge slot.

    \b
    Arguments:
      SLOT   Slot number to configure (1–10).
      START  Time to start discharging, in HH:MM format.
      END    Time to stop discharging, in HH:MM format.
      SOC    Floor state of charge in percent (4–100). The inverter stops
             discharging early if the battery reaches this level before END.

    \b
    Examples:
      givlocally discharge-slot set 1 16:00 20:00 10
          Slot 1: discharge from 16:00 to 20:00, stop at 10%.
      givlocally discharge-slot set 2 07:00 09:00 20
          Slot 2: discharge from 07:00 to 09:00, stop at 20%.
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).set_discharge_slot(slot, start, end, floor_soc)
        err.print(f"[green]Discharge slot {slot} set to {start} → {end}, floor {floor_soc}%[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@discharge_slot_group.command("clear")
@click.argument("slot", type=click.IntRange(1, 10))
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_discharge_slot_clear(
    slot: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Disable discharge SLOT by resetting its times to 00:00.

    SLOT is 1–10.

    Example: givlocally discharge-slot clear 1
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).clear_discharge_slot(slot)
        err.print(f"[green]Discharge slot {slot} cleared[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@cli.group("export-slot")
def export_slot_group() -> None:
    """Manage timed export slots on the inverter (EMS inverters only)."""


@export_slot_group.command("set")
@click.argument("slot", type=click.IntRange(1, 3))
@click.argument("start")
@click.argument("end")
@click.argument("floor_soc", metavar="SOC", type=click.IntRange(4, 100))
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_export_slot_set(
    slot: int,
    start: str,
    end: str,
    floor_soc: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Configure a timed export slot.

    \b
    Arguments:
      SLOT   Slot number to configure (1–3).
      START  Time to start exporting, in HH:MM format.
      END    Time to stop exporting, in HH:MM format.
      SOC    Floor state of charge in percent (4–100). The inverter stops
             exporting early if the battery drops to this level before END.

    \b
    Examples:
      givlocally export-slot set 1 10:00 15:00 20
          Slot 1: export from 10:00 to 15:00, stop at 20%.
      givlocally export-slot set 2 06:00 11:00 10
          Slot 2: export from 06:00 to 11:00, stop at 10%.
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).set_export_slot(slot, start, end, floor_soc)
        err.print(f"[green]Export slot {slot} set to {start} → {end}, floor {floor_soc}%[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@export_slot_group.command("clear")
@click.argument("slot", type=click.IntRange(1, 3))
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_export_slot_clear(
    slot: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Disable export SLOT by resetting its times to 00:00.

    SLOT is 1–3.

    Example: givlocally export-slot clear 1
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).clear_export_slot(slot)
        err.print(f"[green]Export slot {slot} cleared[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


def _battery_connection_options(fn):
    """Shared host/port/retries/inv-type/verbose options for battery commands."""
    for decorator in reversed([
        click.option("--host", default=default_host, show_default="192.168.0.100",
                     envvar="GIVENERGY_HOST",
                     help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle."),
        click.option("--port", default=default_port, show_default="8899",
                     envvar="GIVENERGY_PORT", help="Modbus TCP port on the inverter."),
        click.option("--retries", default=3, show_default=True,
                     help="Number of connection attempts before giving up."),
        click.option("--inv-type", default=default_inv_type, show_default="standard",
                     envvar="GIVENERGY_INV_TYPE",
                     type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
                     help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS."),
        click.option("--verbose", "-v", is_flag=True, help="Enable debug logging."),
    ]):
        fn = decorator(fn)
    return fn


@cli.group("battery")
def battery_group() -> None:
    """Immediately control battery charge/discharge behaviour."""


@battery_group.command("charge")
@_battery_connection_options
def cmd_battery_charge(host: str, port: int, retries: int, inv_type: str, verbose: bool) -> None:
    """Charge the battery from the mains at full power right now.

    Enables charging and AC (grid) charging and disables discharging.
    The inverter will draw from the grid until you run 'battery normal'.

    Example: givlocally battery charge
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).force_charge()
        err.print("[green]Battery charging from mains at full power.[/green]  "
                  "Run [bold]givlocally battery normal[/bold] to return to automatic mode.")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@battery_group.command("export")
@_battery_connection_options
def cmd_battery_export(host: str, port: int, retries: int, inv_type: str, verbose: bool) -> None:
    """Discharge the battery at full power, exporting surplus to the grid.

    Sets discharge mode to max power (ECO_MODE off) and enables discharging.
    Any battery or solar output above your load demand will be exported.
    Run 'battery normal' to return to automatic mode.

    Example: givlocally battery export
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    settings = load_settings()
    min_soc = settings.get("battery", {}).get("min_soc", 4)
    try:
        InverterWriter(config, inv_type=inv_type).force_export(min_soc=min_soc)
        err.print("[green]Battery discharging at full power — surplus exported to grid.[/green]  "
                  "Run [bold]givlocally battery normal[/bold] to return to automatic mode.")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@battery_group.command("normal")
@_battery_connection_options
def cmd_battery_normal(host: str, port: int, retries: int, inv_type: str, verbose: bool) -> None:
    """Return the battery to normal automatic (dynamic/eco) operation.

    Restores demand-matching discharge mode, re-enables charging and AC charging,
    and restores the battery SOC reserve to the minimum configured in setup.

    Example: givlocally battery normal
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    settings = load_settings()
    min_soc = settings.get("battery", {}).get("min_soc", 4)
    try:
        InverterWriter(config, inv_type=inv_type).set_normal_mode(min_soc=min_soc)
        err.print(f"[green]Battery returned to normal automatic mode (SOC reserve restored to {min_soc}%).[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("predict")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_predict(verbose: bool) -> None:
    """Predict the overnight charge target based on tomorrow's solar forecast.

    Uses the forecast.solar API to estimate tomorrow's solar generation, then
    calculates what SOC the battery needs to reach overnight so that solar +
    battery together cover the expected daily household consumption.

    Requires givlocally setup to have been run with solar panel, usage, and
    battery settings filled in.
    """
    _setup_logging(verbose)
    console = Console()
    settings = load_settings()

    solar = settings.get("solar", {})
    usage = settings.get("usage", {})
    battery = settings.get("battery", {})

    # ── Validate settings ─────────────────────────────────────────────────────
    missing = []
    if not solar.get("capacity_kwp"):
        missing.append("solar › capacity_kwp")
    if not solar.get("latitude") and solar.get("latitude") != 0.0:
        missing.append("solar › latitude")
    if not solar.get("longitude") and solar.get("longitude") != 0.0:
        missing.append("solar › longitude")
    if not usage.get("daily_kwh"):
        missing.append("usage › daily_kwh")
    if not battery.get("capacity_kwh"):
        missing.append("battery › capacity_kwh")

    if missing:
        err.print("[bold red]Error:[/bold red] The following settings are missing. Run [bold]givlocally setup[/bold] to configure them:")
        for m in missing:
            err.print(f"  [dim]•[/dim] {m}")
        sys.exit(1)

    # ── Fetch forecast ────────────────────────────────────────────────────────
    console.print("\nFetching solar forecast from forecast.solar …")
    try:
        forecasts = fetch_forecast(
            latitude=solar["latitude"],
            longitude=solar["longitude"],
            tilt_deg=solar.get("tilt_deg", 35),
            azimuth_deg=solar.get("azimuth_deg", 180),
            capacity_kwp=solar["capacity_kwp"],
            efficiency=solar.get("efficiency", 0.8),
            days=2,
        )
    except RuntimeError as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    tomorrow_forecast = forecasts[1] if len(forecasts) > 1 else forecasts[0]
    today_forecast = forecasts[0]

    daily_kwh = usage["daily_kwh"]
    capacity_kwh = battery["capacity_kwh"]
    min_soc = battery.get("min_soc", 10)

    recommended_soc, shortfall_kwh = required_overnight_soc(
        forecast_kwh=tomorrow_forecast.generation_kwh,
        daily_usage_kwh=daily_kwh,
        battery_capacity_kwh=capacity_kwh,
        min_soc=min_soc,
    )

    # ── Display ───────────────────────────────────────────────────────────────
    console.print()
    from rich.table import Table
    from rich import box

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("Label", style="dim", min_width=34)
    t.add_column("Value", style="bold white")

    t.add_row("Today's predicted generation",
              f"[green]{today_forecast.generation_kwh:.1f} kWh[/green]"
              f" [dim](raw {today_forecast.raw_kwh:.1f} kWh × {solar.get('efficiency', 0.8):.0%} efficiency)[/dim]")
    t.add_row("Tomorrow's predicted generation",
              f"[green]{tomorrow_forecast.generation_kwh:.1f} kWh[/green]"
              f" [dim](raw {tomorrow_forecast.raw_kwh:.1f} kWh × {solar.get('efficiency', 0.8):.0%} efficiency)[/dim]")
    t.add_row("Expected daily consumption", f"{daily_kwh:.1f} kWh")

    if shortfall_kwh > 0:
        t.add_row("Shortfall solar cannot cover", f"[yellow]{shortfall_kwh:.1f} kWh[/yellow]")
    else:
        surplus = tomorrow_forecast.generation_kwh - daily_kwh
        t.add_row("Solar surplus", f"[green]{surplus:.1f} kWh[/green] — solar alone should cover the day")

    t.add_row("Battery capacity", f"{capacity_kwh:.1f} kWh")
    t.add_row("Minimum SOC reserve", f"{min_soc}%")

    console.print(t)

    soc_color = "green" if recommended_soc <= 60 else "yellow" if recommended_soc <= 85 else "red"
    console.print(
        f"  [bold]Recommended overnight charge target:[/bold] "
        f"[{soc_color} bold]{recommended_soc}%[/{soc_color} bold]\n"
    )


@cli.command("time-sync")
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_time_sync(host: str, port: int, retries: int, inv_type: str, verbose: bool) -> None:
    """Set the inverter clock to the current computer date and time."""
    import datetime as dt_mod
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    now = dt_mod.datetime.now()
    try:
        InverterWriter(config, inv_type=inv_type).sync_time(now)
        err.print(f"[green]Inverter time set to {now.strftime('%Y-%m-%d %H:%M:%S')}[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("auto")
@click.option("--dry-run", is_flag=True, help="Show what would be set without writing to the inverter.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_auto(dry_run: bool, verbose: bool) -> None:
    """Predict overnight charge need and set the charge slot automatically.

    Fetches tomorrow's solar forecast, calculates the required overnight charge
    target, then programs the configured charge slot on the inverter to that SOC.

    Configure the slot number and times with: givlocally setup
    """
    _setup_logging(verbose)
    console = Console()
    settings = load_settings()

    solar = settings.get("solar", {})
    usage = settings.get("usage", {})
    battery = settings.get("battery", {})
    auto = settings.get("auto", DEFAULTS["auto"])
    conn = settings.get("connection", DEFAULTS["connection"])

    # ── Validate ──────────────────────────────────────────────────────────────
    missing = []
    if not solar.get("capacity_kwp"):
        missing.append("solar › capacity_kwp")
    if not usage.get("daily_kwh"):
        missing.append("usage › daily_kwh")
    if not battery.get("capacity_kwh"):
        missing.append("battery › capacity_kwh")
    if missing:
        err.print("[bold red]Error:[/bold red] Missing settings — run [bold]givlocally setup[/bold]:")
        for m in missing:
            err.print(f"  [dim]•[/dim] {m}")
        sys.exit(1)

    # ── Fetch forecast ────────────────────────────────────────────────────────
    console.print("Fetching solar forecast …")
    try:
        forecasts = fetch_forecast(
            latitude=solar["latitude"],
            longitude=solar["longitude"],
            tilt_deg=solar.get("tilt_deg", 35),
            azimuth_deg=solar.get("azimuth_deg", 180),
            capacity_kwp=solar["capacity_kwp"],
            efficiency=solar.get("efficiency", 0.8),
            days=2,
        )
    except RuntimeError as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    tomorrow = forecasts[1] if len(forecasts) > 1 else forecasts[0]
    daily_kwh = usage["daily_kwh"]
    capacity_kwh = battery["capacity_kwh"]
    min_soc = battery.get("min_soc", 10)

    recommended_soc, shortfall_kwh = required_overnight_soc(
        forecast_kwh=tomorrow.generation_kwh,
        daily_usage_kwh=daily_kwh,
        battery_capacity_kwh=capacity_kwh,
        min_soc=min_soc,
    )

    slot = auto["charge_slot"]
    start = auto["charge_start"]
    end = auto["charge_end"]

    console.print(
        f"  Tomorrow's forecast: [green]{tomorrow.generation_kwh:.1f} kWh[/green]  "
        f"Daily usage: {daily_kwh:.1f} kWh  "
        f"Shortfall: [yellow]{shortfall_kwh:.1f} kWh[/yellow]"
    )
    console.print(
        f"  Charge slot {slot} ({start} → {end})  →  "
        f"target [bold]{recommended_soc}%[/bold]"
    )

    if dry_run:
        console.print("\n[dim]Dry run — inverter not updated.[/dim]")
        return

    # ── Apply ─────────────────────────────────────────────────────────────────
    config = InverterConfig(
        host=conn["host"],
        port=conn["port"],
        retries=conn.get("retries", 3),
    )
    try:
        InverterWriter(config, inv_type=conn.get("inv_type", "")).set_charge_slot(
            slot, start, end, recommended_soc
        )
        console.print(f"\n[green]Charge slot {slot} set to {start} → {end} @ {recommended_soc}%[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error writing to inverter:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("setup")
def cmd_setup() -> None:
    """Interactively configure GivLocally and save settings to disk."""
    existing = load_settings()
    conn = existing.get("connection", DEFAULTS["connection"])
    solar = existing.get("solar", DEFAULTS["solar"])
    usage = existing.get("usage", DEFAULTS["usage"])
    battery = existing.get("battery", DEFAULTS["battery"])
    auto = existing.get("auto", DEFAULTS["auto"])

    console = Console()
    console.print("\n[bold cyan]GivLocally Setup[/bold cyan]\n")

    if existing:
        console.print(f"[dim]Existing config found at {config_path()}. Press Enter to keep current values.[/dim]\n")

    # ── Connection ────────────────────────────────────────────────────────────
    console.print("[bold]Connection[/bold]")

    host = click.prompt("  Inverter IP address", default=conn["host"])
    port = click.prompt("  Modbus port", default=conn["port"], type=int)
    batteries = click.prompt("  Number of battery packs", default=conn["batteries"], type=int)
    inv_type_choice = click.prompt(
        "  Inverter type",
        default=conn["inv_type"] or "standard",
        type=click.Choice(["standard", "3ph", "ems"]),
    )
    inv_type = "" if inv_type_choice == "standard" else inv_type_choice

    # ── Solar panels ──────────────────────────────────────────────────────────
    console.print("\n[bold]Solar Panels[/bold]")
    console.print("[dim]  This information will be used to calculate solar forecasts.[/dim]\n")

    capacity_kwp = click.prompt(
        "  Total panel capacity (kWp)",
        default=solar["capacity_kwp"],
        type=float,
    )
    tilt_deg = click.prompt(
        "  Panel tilt in degrees (0 = flat, 90 = vertical)",
        default=solar["tilt_deg"],
        type=click.IntRange(0, 90),
    )
    console.print("  [dim]Azimuth: 0/360 = North, 90 = East, 180 = South, 270 = West[/dim]")
    azimuth_deg = click.prompt(
        "  Panel azimuth in degrees",
        default=solar["azimuth_deg"],
        type=click.IntRange(0, 360),
    )
    latitude = click.prompt(
        "  Latitude (decimal degrees, e.g. 51.5 for London)",
        default=solar["latitude"],
        type=float,
    )
    longitude = click.prompt(
        "  Longitude (decimal degrees, e.g. -0.1 for London)",
        default=solar["longitude"],
        type=float,
    )
    efficiency = click.prompt(
        "  System efficiency factor (0.0–1.0, accounting for inverter losses, temperature and soiling)",
        default=solar["efficiency"],
        type=click.FloatRange(0.1, 1.0),
    )

    # ── Usage ─────────────────────────────────────────────────────────────────
    console.print("\n[bold]Household Usage[/bold]")
    console.print("[dim]  Used to calculate how much overnight charge is needed.[/dim]\n")

    daily_kwh = click.prompt(
        "  Expected daily household consumption (kWh)",
        default=usage["daily_kwh"],
        type=click.FloatRange(0.0),
    )

    # ── Battery ───────────────────────────────────────────────────────────────
    console.print("\n[bold]Battery[/bold]\n")

    capacity_kwh = click.prompt(
        "  Usable battery capacity (kWh)",
        default=battery["capacity_kwh"],
        type=click.FloatRange(0.0),
    )
    min_soc = click.prompt(
        "  Minimum SOC to keep in reserve (%)",
        default=battery["min_soc"],
        type=click.IntRange(0, 50),
    )

    # ── Auto charge ───────────────────────────────────────────────────────────
    console.print("\n[bold]Auto Charge[/bold]")
    console.print("[dim]  The charge slot used by the 'givlocally auto' command.[/dim]\n")

    charge_slot = click.prompt(
        "  Charge slot number",
        default=auto["charge_slot"],
        type=click.IntRange(1, 10),
    )
    charge_start = click.prompt(
        "  Charge slot start time (HH:MM)",
        default=auto["charge_start"],
    )
    charge_end = click.prompt(
        "  Charge slot end time (HH:MM)",
        default=auto["charge_end"],
    )

    # ── Save ──────────────────────────────────────────────────────────────────
    data = {
        "connection": {
            "host": host,
            "port": port,
            "batteries": batteries,
            "inv_type": inv_type,
        },
        "solar": {
            "capacity_kwp": capacity_kwp,
            "tilt_deg": tilt_deg,
            "azimuth_deg": azimuth_deg,
            "latitude": latitude,
            "longitude": longitude,
            "efficiency": efficiency,
        },
        "usage": {
            "daily_kwh": daily_kwh,
        },
        "battery": {
            "capacity_kwh": capacity_kwh,
            "min_soc": min_soc,
        },
        "auto": {
            "charge_slot": charge_slot,
            "charge_start": charge_start,
            "charge_end": charge_end,
        },
    }

    path = save_settings(data)
    console.print(f"\n[green]Settings saved to {path}[/green]")
    console.print("[dim]These will be used as defaults for all commands.[/dim]\n")


@cli.command("server")
@click.option(
    "--listen",
    default="0.0.0.0",
    show_default=True,
    help="Address for the web server to listen on.",
)
@click.option(
    "--web-port",
    default=5000,
    show_default=True,
    type=int,
    help="Port for the web server.",
)
@click.option(
    "--host",
    default=default_host,
    show_default="192.168.0.100",
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=default_port,
    show_default="8899",
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default=default_inv_type,
    show_default="standard",
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_server(
    listen: str,
    web_port: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Start the GivLocally web server.

    Serves a browser-based dashboard showing live inverter data and controls
    for all commands. Reads inverter connection details from setup config by
    default; options override saved values.

    Example: givlocally server --web-port 8080
    """
    import logging as _logging
    _setup_logging(verbose)
    # Suppress Flask/werkzeug noise unless verbose
    if not verbose:
        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

    settings = load_settings()
    battery = settings.get("battery", {})
    min_soc = battery.get("min_soc", 4)

    config = InverterConfig(host=host, port=port, retries=retries)

    from .server import create_app
    app = create_app(config, inv_type=inv_type, min_soc=min_soc)

    Console().print(
        f"[bold green]GivLocally web server[/bold green] → "
        f"http://{'localhost' if listen == '0.0.0.0' else listen}:{web_port}\n"
        f"[dim]Inverter: {host}:{port}  Press Ctrl+C to stop.[/dim]"
    )
    app.run(host=listen, port=web_port, threaded=True)


if __name__ == "__main__":
    cli()
