from recaptcha_manager.api import multiprocessing
from ctypes import c_bool


def generate_queue(manager=None):
    """
    Generates a proxy object of class :class:`~multiprocessing.Queue`

    :rtype: multiprocessing.Queue
    """
    if manager is None:
        manager = multiprocessing.Manager()
    return manager.Queue()


def make_proxy(name, cls, base=None):
    exposed = multiprocessing.managers.public_methods(cls) + ['__getattribute__', '__setattr__', '__delattr__']
    return _MakeProxyType(name, exposed, base)


def _MakeProxyType(name, exposed, base=None):
    '''
    Return a proxy type whose methods are given by `exposed`
    '''

    if base is None:
        base = multiprocessing.managers.NamespaceProxy
    exposed = tuple(exposed)

    dic = {}

    for meth in exposed:
        if hasattr(base, meth):
            continue
        exec('''def %s(self, /, *args, **kwds):
        return self._callmethod(%r, args, kwds)''' % (meth, meth), dic)

    ProxyType = type(name, (base,), dic)
    ProxyType._exposed_ = exposed
    return ProxyType
