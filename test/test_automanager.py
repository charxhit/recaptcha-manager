from recaptcha_manager import AntiCaptcha, TwoCaptcha, AutoManager, generate_queue
import queue
import unittest
import multiprocessing


class MyAntiCaptcha(AntiCaptcha):
    pass


class MyTwoCaptcha(TwoCaptcha):
    pass


# def worker():
#
#
#
# def test_service_state():

class TestAutoManager(unittest.TestCase):

    def test_create(self):
        request_queue = ''
        with self.assertRaises(multiprocessing.managers.RemoteError):
            AutoManager.create(request_queue, '', '', 'v2')
        request_queue = generate_queue()
        with self.assertRaises(multiprocessing.managers.RemoteError):
            AutoManager.create(request_queue, '', '', '')

    def test_stop(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, '', '', 'v2')
        inst.stop()
        with self.assertRaises(queue.Empty):
            inst.get_request(max_block=2)

    def test_flush(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, '', '', 'v2')
        for _ in range(10):
            inst.response_queue.put('')
        inst.flush()
        with self.assertRaises(queue.Empty):
            inst.response_queue.get(block=None)

    def test_send_request(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, '', '', 'v2')
        inst.send_request(initial=5)
        print(request_queue.qsize())
        l = []
        while True:
            try:
                l.append(request_queue.get(block=None))
            except queue.Empty:
                break
        self.assertEqual(5, len(l))






if __name__ == "__main__":
    unittest.main()