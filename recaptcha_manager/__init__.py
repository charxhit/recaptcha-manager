"""If you're snooping around here, then know that the actual definitions for the below objects are present in
recaptcha_manager.api sub-package. These placeholders are here only to inform users of the changes, since version
0.0.7+ are not backwards compatible with the previous versions. They will be removed in a later version.

Likewise, the modules present in this directory mimic the names of the actual implementations inside the sub-package,
but will raise similar exceptions if use is attempted. """

error = NotImplementedError("\n\nIt seems like you are using version 0.0.7+, but not importing from the correct "
                                  "sub-package. Please import the relevant modules, functions and \nclasses from "
                                  "recaptcha_manager.api instead. For example, to "
                                  "correctly import AutoManager, do:\n\n    from recaptcha_manager.api import "
                                  "AutoManager\n\n"
                                  "For information about this change available here : https://recaptcha-manager.readthedocs.io/en/latest/#version-0-0-7-and-above")
class _Deprecated(type):
    def __getattr__(self, item):
        raise error

class AutoManager(metaclass=_Deprecated): pass


ManualManager = AntiCaptcha = TwoCaptcha = CapMonster = BaseService = Exhausted = AutoManager

def generate_queue(*args, **kwargs):
    raise error

