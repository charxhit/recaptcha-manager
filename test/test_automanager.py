import recaptcha_manager.configuration
from recaptcha_manager.api import AutoManager, generate_queue
import queue
import time
import unittest
from recaptcha_manager.api import multiprocessing
import recaptcha_manager.api.exceptions as exc
from recaptcha_manager.api.services import DummyService


def worker_send(manager):
    manager.send_request(initial=1)

def worker_get(manager):
    manager.get_request(max_block=10)

class TestAutoManager(unittest.TestCase):

    def test_create(self):
        request_queue = ''
        with self.assertRaises(multiprocessing.managers.RemoteError):
            AutoManager.create(request_queue, 'https://s', '', 'v2')
        request_queue = generate_queue()
        with self.assertRaises(multiprocessing.managers.RemoteError):
            AutoManager.create(request_queue, 'https://s', '', '')

    def test_stop(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, 'https://s', '', 'v2')
        service = DummyService.create_service('key', request_queue)
        service_proc = service.spawn_process()
        inst.send_request(initial=5)
        time.sleep(5)
        inst.stop()

        for _ in range(5):
            inst.get_request(max_block=3)

        inst.send_request(initial=5)

        with self.assertRaises(exc.Exhausted):
            inst.get_request(max_block=2)

        service.stop()
        service_proc.join()

    def test_force_stop(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, 'https://s', '', 'v2')
        inst.send_request(initial=5)
        service = DummyService.create_service('key', request_queue, solve_time=20)
        service_proc = service.spawn_process()
        time.sleep(5)
        inst.force_stop()
        with self.assertRaises(exc.Exhausted):
            inst.get_request(max_block=2)

        service.stop()
        service_proc.join()

    def test_flush(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, 'https://s', '84874', 'v2')
        for _ in range(10):
            inst.response_queue.put('')
        inst.flush()
        with self.assertRaises(queue.Empty):
            inst.response_queue.get(block=None)

    def test_send_request(self):
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, 'https://s', '', 'v2')
        inst.send_request(initial=5)
        self.assertEqual(inst.ReqsInQueue, 5)
        l = []
        while True:
            try:
                l.append(request_queue.get(block=None))
            except queue.Empty:
                break
        self.assertEqual(5, len(l))

    def test_create_restore_point(self):
        import copy
        request_queue = generate_queue()
        inst = AutoManager.create(request_queue, 'https://s', '', 'v2')
        with self.assertRaises(exc.RestoreError):
            inst.restore()
        inst.create_restore_point()
        with self.assertRaises(exc.RestoreError):
            inst.create_restore_point()
        inst.create_restore_point(overwrite=True)
        original = copy.deepcopy(inst.UseRate)
        inst.UseRate = {}
        inst.restore()
        self.assertEqual(inst.UseRate, original)

    def test_statistics(self):
        request_queue = generate_queue()
        manager = AutoManager.create(request_queue, 'https://s', '', 'v2')
        manager.send_request(initial=5)
        service = DummyService.create_service('key', request_queue, solve_time=20)
        proc = service.spawn_process()
        for _ in range(5):
            manager.get_request(max_block=10)

        self.assertEqual(manager.get_solving_time(), 20)
        self.assertEqual(manager.being_solved() + manager.available(), 0)
        self.assertEqual(manager.get_solved(), 5)
        self.assertEqual(manager.get_used(), 5)

        service.stop()
        proc.join()

    def test_statistics_multiple_proc(self):
        request_queue = generate_queue()
        manager = AutoManager.create(request_queue, 'https://s', '', 'v2')

        with multiprocessing.Pool(3) as pool:
            pool.map(worker_send, [manager] * 3)

        service = DummyService.create_service('key', request_queue, solve_time=20)
        proc = service.spawn_process()

        tasks = []
        for _ in range(3):
            tasks.append(multiprocessing.Process(target=worker_get, args=(manager, )))
            tasks[-1].start()
        for task in tasks:
            task.join()

        self.assertEqual(manager.get_solving_time(), 20)
        self.assertEqual(manager.being_solved() + manager.available(), 0)
        self.assertEqual(manager.get_solved(), 3)
        self.assertEqual(manager.get_used(), 3)

        service.stop()
        proc.join()

    def test_clear_requests(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='LowBidError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=10)
        time.sleep(5)
        self.assertEqual(manager.available() + manager.being_solved(), 0)
        service.stop()
        proc.join()

if __name__ == "__main__":
    unittest.main()