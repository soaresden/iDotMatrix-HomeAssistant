def async_remove_panel(hass, frontend_url_path, warn_if_unknown=True) -> None:
    hass.data.pop("panel", None)
