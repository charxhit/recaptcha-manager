from recaptcha_manager import configuration

assert isinstance(configuration.USE_DILL, bool), "config value must be a boolean"
if configuration.USE_DILL:
    import multiprocess as multiprocessing
    import multiprocess.managers
else:
    import multiprocessing
    import multiprocessing.managers

from .manager import AutoManager, ManualManager
from .services import AntiCaptcha, TwoCaptcha, CapMonster, BaseService
from .exceptions import Exhausted
from .generators import generate_queue


__all__ = ['generate_queue', 'AutoManager', 'ManualManager', 'AntiCaptcha', 'TwoCaptcha', 'CapMonster', 'BaseService',
           'Exhausted', 'multiprocessing']

