import random
import time
from time import sleep
import multiprocessing
import recaptcha_manager
from recaptcha_manager import AutoManager, AntiCaptcha, TwoCaptcha, generate_queue, generate_flag
from ctypes import c_bool
from requests.packages.urllib3.util.retry import Retry

def exc_handler(exc):
    print(exc)


if __name__ == '__main__':
    request_queue = generate_queue()
    flag = generate_flag()

    inst1 = AutoManager.create(request_queue, 'https://exey.io/7TLemQ', '6Ldzj74UAAAAAAVQ7-WIlUUfNGJFaKdgRxA7qH94',
                               'v2', invisible=True, initial=2)

    retries = Retry(total=5, backoff_factor=1)
    proc = TwoCaptcha.spawn_process(flag, request_queue, key='71e99232581a96375b1d1fd13352db1e',
                                    exc_handler=exc_handler, retry=retries)
    last = time.time()
    num1 = 5
    num2 = 11
    for x in range(3):
        if x == 20:
            num1 = 15
            num2 = 22
        inst1.send_request()
        sleep(random.randint(num1, num2))
        t = time.time()
        print(inst1.get_request())
        print(time.time() - t)
        if time.time() - last > 30:
            inst1.write_status()
            last = time.time()
    inst1.stop()
    while True:
        r = inst1.get_request()
        print(r)
        if r == 'quit':
            break
    inst1.write_status()
    flag.value = False
    proc.join()
    inst1.flush()