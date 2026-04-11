"""Read settings and real-time data from a GivEnergy inverter over local Modbus TCP.

Uses givenergy-modbus-async which supports Gen3 inverters (firmware 912+).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from givenergy_modbus_async.client.client import Client

from .config import InverterConfig

log = logging.getLogger(__name__)

# Gen3 supports up to 10 charge/discharge slots
MAX_SLOTS = 10


@dataclass
class TimeSlot:
    index: int
    start: str = "00:00"
    end: str = "00:00"

    @property
    def is_active(self) -> bool:
        return not (self.start == "00:00" and self.end == "00:00")


@dataclass
class BatterySnapshot:
    """Point-in-time snapshot of a single battery pack."""

    index: int
    serial_number: str = ""
    bms_firmware: str = ""
    state_of_charge: int = 0            # %
    cap_design_ah: float = 0.0          # Ah
    cap_calibrated_ah: float = 0.0      # Ah
    cap_remaining_ah: float = 0.0       # Ah
    num_cycles: int = 0
    num_cells: int = 0
    temp_max_c: float = 0.0
    temp_min_c: float = 0.0
    temp_mos_c: float = 0.0
    cell_voltages_mv: list[float] = field(default_factory=list)
    v_out: float = 0.0
    e_charge_total_kwh: float = 0.0
    e_discharge_total_kwh: float = 0.0


@dataclass
class InverterSnapshot:
    """Complete point-in-time snapshot of an inverter and its batteries."""

    # --- Device identity ---
    serial_number: str = ""
    model: str = ""
    firmware_version: str = ""
    dsp_firmware_version: str = ""
    arm_firmware_version: str = ""
    system_time: Optional[datetime] = None

    # --- Real-time power (W) ---
    p_pv1_w: float = 0.0
    p_pv2_w: float = 0.0
    p_battery_w: float = 0.0       # positive = discharging, negative = charging
    p_grid_w: float = 0.0          # positive = export, negative = import
    p_load_w: float = 0.0
    p_inverter_out_w: float = 0.0
    p_eps_backup_w: float = 0.0

    # --- Real-time voltage / current ---
    v_pv1: float = 0.0
    v_pv2: float = 0.0
    v_ac1: float = 0.0
    v_battery: float = 0.0
    i_battery: float = 0.0
    i_pv1: float = 0.0
    i_pv2: float = 0.0
    i_ac1: float = 0.0
    f_ac1: float = 0.0             # Hz
    v_p_bus: float = 0.0
    v_n_bus: float = 0.0

    # --- Temperatures (°C) ---
    temp_inverter_c: float = 0.0
    temp_charger_c: float = 0.0
    temp_battery_c: float = 0.0

    # --- Battery settings ---
    battery_soc_pct: int = 0
    charge_enabled: bool = False
    discharge_enabled: bool = False
    charge_target_soc: int = 100
    eco_mode: bool = False
    battery_pause_mode: str = ""
    enable_ups_mode: bool = False
    pv_power_setting: int = 0

    # --- Charge / discharge slots (up to 10 each for Gen3) ---
    charge_slots: list[TimeSlot] = field(default_factory=list)
    discharge_slots: list[TimeSlot] = field(default_factory=list)

    # --- Charge target SOC per slot ---
    charge_target_socs: list[int] = field(default_factory=list)
    discharge_target_socs: list[int] = field(default_factory=list)

    # --- Export slots (up to 3, EMS inverters) ---
    export_slots: list[TimeSlot] = field(default_factory=list)
    export_floor_socs: list[int] = field(default_factory=list)

    # --- Cumulative energy ---
    e_pv_total_kwh: float = 0.0
    e_pv1_day_kwh: float = 0.0
    e_pv2_day_kwh: float = 0.0
    e_grid_in_day_kwh: float = 0.0
    e_grid_out_day_kwh: float = 0.0
    e_battery_charge_today_kwh: float = 0.0
    e_battery_discharge_today_kwh: float = 0.0
    e_battery_charge_total_kwh: float = 0.0
    e_battery_discharge_total_kwh: float = 0.0
    e_inverter_export_total_kwh: float = 0.0

    # --- Status ---
    num_batteries: int = 0

    # --- Batteries ---
    batteries: list[BatterySnapshot] = field(default_factory=list)


def _get(obj, *attrs, default=None):
    """Try multiple attribute names in order, return first non-None value."""
    for attr in attrs:
        try:
            # Try dict-style get() first (register lookup table objects)
            if hasattr(obj, "get"):
                v = obj.get(attr)
                if v is not None:
                    return v
            # Fall back to direct attribute
            v = getattr(obj, attr, None)
            if v is not None:
                return v
        except Exception:
            continue
    return default


def _float(obj, *attrs, default: float = 0.0) -> float:
    v = _get(obj, *attrs, default=default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(obj, *attrs, default: int = 0) -> int:
    v = _get(obj, *attrs, default=default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _bool(obj, *attrs, default: bool = False) -> bool:
    v = _get(obj, *attrs, default=default)
    if isinstance(v, bool):
        return v
    try:
        return bool(int(v))
    except (TypeError, ValueError):
        return default


def _str(obj, *attrs, default: str = "") -> str:
    v = _get(obj, *attrs, default=default)
    return str(v) if v is not None else default


def _time_str(t) -> str:
    if t is None:
        return "00:00"
    if isinstance(t, str):
        # Handle "HHMM" format
        if len(t) == 4 and t.isdigit():
            return f"{t[:2]}:{t[2:]}"
        return t
    try:
        return t.strftime("%H:%M")
    except AttributeError:
        return str(t)


def _slot_times(obj, attr: str) -> tuple[str, str]:
    """Extract start/end times from a slot attribute."""
    slot = _get(obj, attr)
    if slot is None:
        return "00:00", "00:00"
    if isinstance(slot, (tuple, list)) and len(slot) >= 2:
        return _time_str(slot[0]), _time_str(slot[1])
    # Some implementations store as a single object with start/end
    start = _get(slot, "start", default=None)
    end = _get(slot, "end", default=None)
    if start is not None:
        return _time_str(start), _time_str(end)
    return "00:00", "00:00"


def _battery_snapshot(index: int, bat) -> BatterySnapshot:
    snap = BatterySnapshot(index=index)
    snap.serial_number = _str(bat, "serial_number")
    snap.bms_firmware = _str(bat, "bms_firmware_version")
    snap.state_of_charge = _int(bat, "soc")
    snap.cap_design_ah = _float(bat, "cap_design", "cap_design2")
    snap.cap_calibrated_ah = _float(bat, "cap_calibrated")
    snap.cap_remaining_ah = _float(bat, "cap_remaining")
    snap.num_cycles = _int(bat, "num_cycles")
    snap.num_cells = _int(bat, "num_cells")
    snap.temp_max_c = _float(bat, "t_max")
    snap.temp_min_c = _float(bat, "t_min")
    snap.temp_mos_c = _float(bat, "t_bms_mosfet")
    snap.v_out = _float(bat, "v_out")
    snap.e_charge_total_kwh = _float(bat, "e_battery_charge_total")
    snap.e_discharge_total_kwh = _float(bat, "e_battery_discharge_total")

    voltages = []
    for n in range(1, 17):
        v = _get(bat, f"v_cell_{n:02d}")
        if v is not None:
            voltages.append(float(v))
    snap.cell_voltages_mv = voltages

    return snap


def _inverter_snapshot(plant) -> InverterSnapshot:
    snap = InverterSnapshot()
    inv = plant.inverter
    if inv is None:
        return snap

    # Identity
    snap.serial_number = _str(inv, "serial_number", "inverter_serial_number")
    snap.model = _str(inv, "model", "device_type_code")
    snap.firmware_version = _str(inv, "firmware_version", "inverter_firmware_version")
    snap.dsp_firmware_version = _str(inv, "dsp_firmware_version")
    snap.arm_firmware_version = _str(inv, "arm_firmware_version")
    snap.system_time = _get(inv, "system_time")

    # Real-time power
    snap.p_pv1_w = _float(inv, "p_pv1")
    snap.p_pv2_w = _float(inv, "p_pv2")
    snap.p_battery_w = _float(inv, "p_battery")
    snap.p_grid_w = _float(inv, "p_grid_out")
    snap.p_load_w = _float(inv, "p_load_demand")
    snap.p_inverter_out_w = _float(inv, "p_inverter_out")
    snap.p_eps_backup_w = _float(inv, "p_eps_backup")

    # Voltage / current
    snap.v_pv1 = _float(inv, "v_pv1")
    snap.v_pv2 = _float(inv, "v_pv2")
    snap.v_ac1 = _float(inv, "v_ac1")
    snap.v_battery = _float(inv, "v_battery")
    snap.i_battery = _float(inv, "i_battery")
    snap.i_pv1 = _float(inv, "i_pv1")
    snap.i_pv2 = _float(inv, "i_pv2")
    snap.i_ac1 = _float(inv, "i_ac1")
    snap.f_ac1 = _float(inv, "f_ac1")
    snap.v_p_bus = _float(inv, "v_p_bus")
    snap.v_n_bus = _float(inv, "v_n_bus")

    # Temperatures
    snap.temp_inverter_c = _float(inv, "temp_inverter_heatsink")
    snap.temp_charger_c = _float(inv, "temp_charger")
    snap.temp_battery_c = _float(inv, "temp_battery")

    # Battery settings
    snap.battery_soc_pct = _int(inv, "battery_percent", "soc_bmu")
    snap.charge_enabled = _bool(inv, "enable_charge")
    snap.discharge_enabled = _bool(inv, "enable_discharge")
    snap.charge_target_soc = _int(inv, "charge_target_soc", default=100)
    snap.eco_mode = _bool(inv, "eco_mode")
    snap.battery_pause_mode = _str(inv, "battery_pause_mode")
    snap.enable_ups_mode = _bool(inv, "enable_ups_mode")
    snap.pv_power_setting = _int(inv, "pv_power_setting")

    # Time slots (Gen3 supports up to 10)
    for i in range(1, MAX_SLOTS + 1):
        start, end = _slot_times(inv, f"charge_slot_{i}")
        snap.charge_slots.append(TimeSlot(index=i, start=start, end=end))

        start, end = _slot_times(inv, f"discharge_slot_{i}")
        snap.discharge_slots.append(TimeSlot(index=i, start=start, end=end))

        snap.charge_target_socs.append(_int(inv, f"charge_target_soc_{i}", default=100))
        snap.discharge_target_socs.append(_int(inv, f"discharge_target_soc_{i}", default=0))

    # Export slots (EMS inverters; silently empty on other models)
    for i in range(1, 4):
        start, end = _slot_times(inv, f"export_slot_{i}")
        snap.export_slots.append(TimeSlot(index=i, start=start, end=end))
        snap.export_floor_socs.append(_int(inv, f"export_target_{i}", default=4))

    # Energy totals
    snap.e_pv_total_kwh = _float(inv, "e_pv_total")
    snap.e_pv1_day_kwh = _float(inv, "e_pv1_day")
    snap.e_pv2_day_kwh = _float(inv, "e_pv2_day")
    snap.e_grid_in_day_kwh = _float(inv, "e_grid_in_day")
    snap.e_grid_out_day_kwh = _float(inv, "e_grid_out_day")
    snap.e_battery_charge_today_kwh = _float(inv, "e_battery_charge_today")
    snap.e_battery_discharge_today_kwh = _float(inv, "e_battery_discharge_today")
    snap.e_battery_charge_total_kwh = _float(inv, "e_battery_charge_total", "e_battery_charge_total3")
    snap.e_battery_discharge_total_kwh = _float(inv, "e_battery_discharge_total", "e_battery_discharge_total3")
    snap.e_inverter_export_total_kwh = _float(inv, "e_inverter_export_total")

    # Batteries
    snap.num_batteries = plant.number_batteries
    try:
        for i, bat in enumerate(plant.batteries):
            snap.batteries.append(_battery_snapshot(i + 1, bat))
    except Exception as exc:
        log.debug("Could not read battery data: %s", exc)

    return snap


async def _read_async(config: InverterConfig) -> InverterSnapshot:
    """Async implementation of the inverter read."""
    client = Client(host=config.host, port=config.port, connect_timeout=config.timeout)

    for attempt in range(1, config.retries + 1):
        try:
            log.debug("Connection attempt %d/%d to %s:%d", attempt, config.retries, config.host, config.port)
            await client.connect()

            log.debug("Detecting plant …")
            await client.detect_plant()

            log.debug("Refreshing all registers …")
            await client.refresh_plant(
                full_refresh=True,
                number_batteries=client.plant.number_batteries,
                meter_list=getattr(client.plant, "meter_list", []),
            )

            return _inverter_snapshot(client.plant)

        except Exception as exc:
            log.warning("Attempt %d failed: %s", attempt, exc)
            if attempt == config.retries:
                raise
            await asyncio.sleep(config.retry_delay)
        finally:
            try:
                await client.close()
            except BaseException:
                pass

    raise RuntimeError("All connection attempts failed")  # unreachable


class InverterReader:
    """High-level reader that connects to a GivEnergy inverter and retrieves all settings."""

    def __init__(self, config: InverterConfig) -> None:
        self._config = config

    def read_all(self) -> InverterSnapshot:
        """
        Connect to the inverter, read all registers, and return a snapshot.

        Raises:
            ConnectionError: If the inverter cannot be reached.
            Exception: On any Modbus communication failure.
        """
        log.info(
            "Connecting to inverter at %s:%d …",
            self._config.host,
            self._config.port,
        )
        return asyncio.run(_read_async(self._config))
