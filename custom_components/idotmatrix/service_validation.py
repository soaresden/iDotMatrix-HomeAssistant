"""Validate display inputs before changing the active mode."""
import math

import voluptuous as vol
from homeassistant.helpers import config_validation as cv


def finite_number(value):
    """Reject NaN and infinity as well as non-numeric input."""
    value = vol.Coerce(float)(value)
    if not math.isfinite(value):
        raise vol.Invalid("Expected a finite number")
    return value


def service_schema(name):
    """Build the schema shared by the animated display services."""
    fields = {
        vol.Optional("pixel_size"): vol.All(vol.Coerce(int), vol.In((32, 64))),
        vol.Optional("follow"): cv.boolean,
        vol.Optional("hour24"): cv.boolean,
        vol.Optional("show_date"): cv.boolean,
        vol.Optional("rainbow"): cv.boolean,
        vol.Optional("color"): vol.All(
            list, vol.Length(min=3, max=3), [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))]
        ),
    }
    for key in ("weather", "condition", "temperature", "humidity", "wind", "high", "low", "price", "change", "co2", "power", "heat", "cool"):
        fields[vol.Optional(f"{key}_entity")] = cv.entity_id
    if name == "show_color":
        return vol.Schema({vol.Required("color"): fields[vol.Optional("color")]})
    if name == "display_gif":
        return vol.Schema({
            vol.Required("path"): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional("rotation_interval", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
        })
    if name == "convert_media":
        fraction = vol.All(finite_number, vol.Range(min=0, max=1))
        factor = vol.All(finite_number, vol.Range(min=0, max=3))
        return vol.Schema({
            vol.Required("source"): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional("output"): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional("pixel_size"): vol.All(vol.Coerce(int), vol.In((16, 32, 64))),
            vol.Optional("fit"): vol.In(("crop", "fit", "stretch")),
            vol.Optional("crop"): vol.All(list, vol.Length(min=4, max=4), [fraction]),
            vol.Optional("start"): vol.All(finite_number, vol.Range(min=0)),
            vol.Optional("end"): vol.All(finite_number, vol.Range(min=0)),
            vol.Optional("max_seconds"): vol.All(finite_number, vol.Range(min=0.1, max=60)),
            vol.Optional("fps"): vol.All(finite_number, vol.Range(min=1, max=30)),
            vol.Optional("max_kb"): vol.All(vol.Coerce(int), vol.Range(min=4, max=1024)),
            vol.Optional("brightness"): factor,
            vol.Optional("contrast"): factor,
            vol.Optional("saturation"): factor,
            vol.Optional("gamma"): vol.All(finite_number, vol.Range(min=0.2, max=5)),
            vol.Optional("black_level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
            vol.Optional("dither"): cv.boolean,
            vol.Optional("boomerang"): cv.boolean,
            vol.Optional("display", default=False): cv.boolean,
        })
    if name in ("show_co2", "show_power"):
        key = "co2_entity" if name == "show_co2" else "power_entity"
        del fields[vol.Optional(key)]
        fields[vol.Required(key)] = cv.entity_id
    if name == "show_message":
        fields.update({
            vol.Required("message"): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional("style"): vol.In(("card", "marquee", "typewriter", "alert", "party")),
            vol.Optional("icon"): cv.string,
            vol.Optional("font"): cv.string,
            vol.Optional("duration"): vol.All(finite_number, vol.Range(min=0)),
        })
    if name == "show_clock":
        fields[vol.Optional("face")] = vol.Any("pixel", "analog", vol.All(vol.Coerce(int), vol.Range(min=0, max=7)))
    if name == "show_bitcoin":
        fields[vol.Optional("logo")] = vol.All(cv.string, vol.Length(min=0, max=128))
    schema = vol.Schema(fields)
    if name == "show_thermostat":
        return vol.All(schema, cv.has_at_least_one_key("heat_entity", "cool_entity"))
    return schema
