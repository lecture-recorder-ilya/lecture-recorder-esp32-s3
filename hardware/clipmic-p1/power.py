"""Battery-side budgets. See README for duty cycles, sources and missing measurements."""

import json
from pathlib import Path

usable_mah = 400 * 0.80
bat_v, efficiency = 3.8, 0.90
led_ma = (3.3 - 2.0) / 1.0  # 1 kOhm, assumed red LED Vf
led_at_bat = led_ma * 3.3 / (bat_v * efficiency)
modes = {
    "deep_sleep": 3.0,
    "light_sleep": 5.0,
    "modem_sleep": 44.0,
    "record_sd_led": 64.5 + led_at_bat,
    "sync_wifi_sd_read_led": 110 + 15 + led_at_bat,
    "sync_ble_sd_read_led": 102 + 15 + led_at_bat,
}
mixed = sum(
    modes[k] * f
    for k, f in [
        ("deep_sleep", 0.35),
        ("record_sd_led", 0.60),
        ("sync_wifi_sd_read_led", 0.05),
    ]
)
resistance = 0.30  # scenario for total battery + PCM + connector and wires in ohms
result = {
    "capacity_min_mAh": 400,
    "usable_assumption_mAh": usable_mah,
    "led_bat_mA": led_at_bat,
    "steady_modes": {k: {"mA": v, "h": usable_mah / v} for k, v in modes.items()},
    "duty_35sleep_60rec_5wifi": {"mA": mixed, "h": usable_mah / mixed},
    "sd_record_peak_from_seeed_plus_led_mA": 109.3 + led_at_bat,
    "tx_sensitivity": [],
}
# Loaded-terminal operating point solves Vbat = Voc - I*R, I = Pout/(eta*Vbat).
out_w = 3.3 * (0.340 + 0.025 + led_ma / 1000)
for ocv in (4.2, 3.8, 3.3, 3.0):
    vload = (ocv + (ocv**2 - 4 * resistance * out_w / 0.85) ** 0.5) / 2
    current = out_w / (0.85 * vload)
    result["tx_sensitivity"].append(
        {
            "open_V": ocv,
            "loaded_V": vload,
            "I_A": current,
            "sag_V": ocv - vload,
            "loaded_above_3V3": vload > 3.3,
        }
    )
result["dropout_current_load_scenario_A"] = 0.340 + 0.025 + led_ma / 1000
result["dropout_sag_scenario_V"] = (
    resistance * result["dropout_current_load_scenario_A"]
)
result["charge_setpoint_nominal_mA"] = 24000 / 220
p = Path(__file__).parent / "checks" / "power.json"
p.write_text(json.dumps(result, indent=2) + "\n")
