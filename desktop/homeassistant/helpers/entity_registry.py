class _Registry:
    """No entities on the desktop (the panel then shows no preview image)."""

    def async_get_entity_id(self, domain, platform, unique_id):
        return None


def async_get(hass) -> _Registry:
    return _Registry()
