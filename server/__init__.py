from ayon_server.addons import BaseServerAddon

from .settings import HarmonySettings, DEFAULT_HARMONY_SETTING

# region agent log
from .debug_d7cc94 import install_instrumentation as _dbg_d7cc94_install
# endregion


class Harmony(BaseServerAddon):
    settings_model = HarmonySettings

    # region agent log
    def initialize(self):
        try:
            _dbg_d7cc94_install()
        except Exception:
            pass
    # endregion

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_HARMONY_SETTING)
