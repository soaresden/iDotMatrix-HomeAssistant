async def async_register_panel(hass, **panel) -> None:
    """The desktop page loads the panel itself: only remember how."""
    hass.data["panel"] = panel
