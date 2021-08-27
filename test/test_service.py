import unittest
import time
import queue

import requests.exceptions
from recaptcha_manager import AntiCaptcha, TwoCaptcha, generate_queue, generate_flag, AutoManager
import multiprocessing


class MyAntiCaptcha(AntiCaptcha):
    pass

class MyTwoCaptcha(TwoCaptcha):
    pass

class AntiCaptchaBadURL(AntiCaptcha):
    api_url = 'urlWithMissingSchema'

class MyClass:
    @staticmethod
    def exc_handler():
        pass

def wrapper(flag, request_queue, key, status_flag):
    # proc = multiprocessing.Process(target=MyAntiCaptcha.requests_manager, args=(flag, request_queue, '', ))
    try:
        AntiCaptchaBadURL.requests_manager(flag, request_queue, key)
    except requests.exceptions.MissingSchema:
        status_flag.value = True

class TestService(unittest.TestCase):
    def test_spawn_process(self):
        request_queue = generate_queue()
        flag = generate_flag()
        flag.value = False
        proc = MyAntiCaptcha.spawn_process(flag, request_queue, '', exc_handler=MyClass.exc_handler)

    def test_stop(self):
        request_queue = generate_queue()
        flag = generate_flag()

        proc = MyAntiCaptcha.spawn_process(flag, request_queue, '')

        flag.value = False
        proc.join(timeout=10)
        self.assertIsNotNone(proc.exitcode)

    def test_own_wrapper(self):
        flag = generate_flag()
        status_flag = generate_flag()
        request_queue = generate_queue()
        status_flag.value = False

        inst = AutoManager.create(request_queue, '', '', 'v2')
        request_queue.put(inst.create_request())

        proc = multiprocessing.Process(target=wrapper, args=(flag, request_queue, '', status_flag, ))
        proc.start()
        proc.join()
        self.assertTrue(status_flag.value)

    def test_get_state(self):
        l1 = ['', '', '']
        l2 = ['', '', '']

        MyAntiCaptcha.unsolved = l1
        MyAntiCaptcha.ci_list = l2

        self.assertEqual((l1, l2, MyAntiCaptcha.name), MyAntiCaptcha.get_state())


    def test_requests_manager_with_state_from_same_service(self):
        request_queue = generate_queue()
        flag = generate_flag()
        unsolved = []
        ci_list = []
        inst = AutoManager.create(request_queue, '', '', 'v2')

        for _ in range(5):
            ci_list.append(inst.create_request())

        for _ in range(5):
            d = inst.create_request()
            d['task_id'] = '123'
            d['statTime'] = time.time()
            unsolved.append(d)

        flag.value = False
        MyAntiCaptcha.requests_manager(flag, request_queue, '', state=(unsolved, ci_list, MyAntiCaptcha.name))

        class_unsolved, class_ci_list, class_name = MyAntiCaptcha.get_state()

        self.assertEqual(len(unsolved), len(class_unsolved))
        self.assertEqual(len(ci_list), len(class_ci_list))

    def test_requests_manager_with_state_from_different_service(self):
        request_queue = generate_queue()
        flag = generate_flag()
        unsolved = []
        ci_list = []
        inst = AutoManager.create(request_queue, '', '', 'v2')

        for _ in range(5):
            ci_list.append(inst.create_request())

        for _ in range(5):
            d = inst.create_request()
            d['task_id'] = '123'
            d['statTime'] = time.time()
            unsolved.append(d)

        flag.value = False
        MyAntiCaptcha.requests_manager(flag, request_queue, '', state=(unsolved, ci_list, MyTwoCaptcha.name))

        class_unsolved, class_ci_list, class_name = MyAntiCaptcha.get_state()

        self.assertEqual(len(class_unsolved), 0)

        count = 0
        while True:
            try:
                request_queue.get(block=None)
                count +=1
            except queue.Empty:
                break

        self.assertEqual(len(class_ci_list), len(ci_list))
        self.assertEqual(len(unsolved), count)



if __name__ == '__main__':
    unittest.main()
