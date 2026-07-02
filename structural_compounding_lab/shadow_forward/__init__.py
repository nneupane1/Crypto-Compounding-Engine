from .shadow_forward_observer import (
    OUTPUT_FOLDER_NAME,
    ShadowForwardObserverConfig,
    write_shadow_forward_observer,
)

__all__ = [
    "OUTPUT_FOLDER_NAME",
    "ShadowForwardObserverConfig",
    "write_shadow_forward_observer",
    "WATCHTOWER_OUTPUT_FOLDER_NAME",
    "ShadowForwardWatchtowerConfig",
]


def __getattr__(name: str):
    if name in {"WATCHTOWER_OUTPUT_FOLDER_NAME", "ShadowForwardWatchtowerConfig"}:
        from .shadow_forward_watchtower import (
            OUTPUT_FOLDER_NAME as WATCHTOWER_OUTPUT_FOLDER_NAME,
            ShadowForwardWatchtowerConfig,
        )

        mapping = {
            "WATCHTOWER_OUTPUT_FOLDER_NAME": WATCHTOWER_OUTPUT_FOLDER_NAME,
            "ShadowForwardWatchtowerConfig": ShadowForwardWatchtowerConfig,
        }
        return mapping[name]
    raise AttributeError(name)
