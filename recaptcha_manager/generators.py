import multiprocessing
from ctypes import c_bool

def generate_queue():
    """
    Generates a proxy object of class :class:`~multiprocessing.Queue`

    :rtype: multiprocessing.Queue
    """
    m = multiprocessing.Manager()
    return m.Queue()


def generate_flag():
    """
    Generates a shared boolean value using class :class:`~multiprocessing.Value`

    :rtype: multiprocessing.sharedctypes.Synchronized
    """

    return multiprocessing.Value(c_bool, True)