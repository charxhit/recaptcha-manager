import queue
import time
import unittest
import multiprocess as multiprocessing
from recaptcha_manager.manager import ManualManager
from recaptcha_manager.services import DummyService
from recaptcha_manager import generate_queue
from recaptcha_manager.exceptions import InvalidBatchID, BadDomainError, TimeOutError, EmptyError, Exhausted


def worker_send(manager):
    return manager.send_request('https://test.com', 'key', 'v2', number=1)

def worker_get(manager, id):
    manager.get_request(batch_id=id, max_block=10)


class TestManualManager(unittest.TestCase):
    def test_create(self):
        request_queue = ''
        with self.assertRaises(multiprocessing.managers.RemoteError):
            ManualManager.create(request_queue)

    def test_send_request(self):
        request_queue = generate_queue()
        manager = ManualManager.create(request_queue)
        with self.assertRaises(BadDomainError):
            manager.send_request('', '', '')
        with self.assertRaises(AssertionError):
            manager.send_request('https://test.com', '', 'v3')
        with self.assertRaises(AssertionError):
            manager.send_request('https://test.com', '', 'v3', action='test')
        with self.assertRaises(AssertionError):
            manager.send_request('https://test.com', '', 'v3', action='test', min_score=1)
        with self.assertRaises(AssertionError):
            manager.send_request('https://test.com', '', 'v3', action='test', min_score='invalid_type')
        with self.assertRaises(AssertionError):
            manager.send_request('https://test.com', '', 'v2', number=0)

        first_id = manager.send_request('https://test.com', 'xxx', 'v2')
        second_id = manager.send_request('https://test.com', 'xxx', 'v2', number=2, action='test')
        self.assertEqual(first_id, second_id)

        first_id = manager.send_request('https://test.com', 'xxx', 'v2')
        second_id = manager.send_request('https://test.com', 'yyy', 'v2')
        self.assertNotEqual(first_id, second_id)

        first_id = manager.send_request('https://test.com', 'xxx', 'v3', action='test', min_score=0.5)
        second_id = manager.send_request('https://test.com', 'xxx', 'v3', number=2, action='test', min_score=0.5)
        self.assertEqual(first_id, second_id)

        first_id = manager.send_request('https://test.com', 'xxx', 'v3', action='test', min_score=0.5)
        second_id = manager.send_request('https://test.com/my_path', 'xxx', 'v3', number=2, action='test', min_score=0.5)
        self.assertEqual(first_id, second_id)

        first_id = manager.send_request('https://test.com', 'xxx', 'v3', action='test', min_score=0.1)
        second_id = manager.send_request('https://test.com', 'yyy', 'v2', action='test2', min_score=0.2)
        self.assertNotEqual(first_id, second_id)


    def test_get_request(self):
        request_queue = generate_queue()
        manager = ManualManager.create(request_queue)
        service = DummyService.create_service('xxx', request_queue)
        proc = service.spawn_process()

        with self.assertRaises(InvalidBatchID):
            manager.get_request(batch_id='invalid_id')

        id = manager.send_request('https://test.com', 'xxx', 'v2')
        manager.get_request(id)

        with self.assertRaises(TimeOutError):
            manager.get_request(id, max_block=1, force_return=False)

        with self.assertRaises(EmptyError):
            manager.get_request(id, force_return=True)

        service.stop()
        proc.join()

    def test_stop(self):
        request_queue = generate_queue()
        manager = ManualManager.create(request_queue)
        service = DummyService.create_service('xxx', request_queue)
        proc = service.spawn_process()

        id = manager.send_request('https://test.com', 'xxx', 'v2')
        while manager.available(id) != 1:
            time.sleep(1)

        manager.stop()
        manager.get_request(id, max_block=2)
        with self.assertRaises(Exhausted):
            manager.get_request(id, max_block=2)

        manager = ManualManager.create(request_queue)
        id = manager.send_request('https://test.com', 'xxx', 'v2')
        manager.force_stop()
        with self.assertRaises(Exhausted):
            manager.get_request(id, max_block=2)
        with self.assertRaises(RuntimeError):
            manager.stop()

        service.stop()
        proc.join()

    def test_upcoming(self):
        request_queue = generate_queue()
        service = DummyService.create_service('xxx', request_queue)
        manager = ManualManager.create(request_queue)
        proc = service.spawn_process()
        id = manager.send_request('https://test.com', 'key', 'v2', number=1)
        self.assertEqual(manager.being_solved(id) + manager.available(batch_id=id), 1)
        manager.get_request(id)
        self.assertEqual(manager.being_solved(id) + manager.available(batch_id=id), 0)

        manager.stop()
        service.stop()
        proc.join()

    def test_clear_requests(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='LowBidError')
        proc = service.spawn_process()
        manager = ManualManager.create(request_queue)
        manager.send_request(number=10, url='http://test.com', web_key='', captcha_type='v2')
        time.sleep(5)
        self.assertEqual(manager.available() + manager.being_solved(), 0)
        service.stop()
        proc.join()
    
    def test_statistics(self):
        request_queue = generate_queue()
        manager = ManualManager.create(request_queue)
        id = manager.send_request('https://test.com', 'key', 'v2', number=5)
        service = DummyService.create_service('key', request_queue)
        proc = service.spawn_process()
        for _ in range(5):
            manager.get_request(batch_id=id, max_block=10)

        self.assertEqual(manager.being_solved() + manager.available(), 0)
        self.assertEqual(manager.being_solved(id) + manager.available(id), 0)
        self.assertEqual(manager.get_solved(), 5)
        self.assertEqual(manager.get_used(), 5)

        service.stop()
        proc.join()

    def test_statistics_multiple_proc(self):
        request_queue = generate_queue()
        manager = ManualManager.create(request_queue)

        with multiprocessing.Pool(3) as pool:
            ids = pool.map(worker_send, [manager] * 3)

        service = DummyService.create_service('key', request_queue)
        proc = service.spawn_process()

        tasks = []
        for i in range(3):
            tasks.append(multiprocessing.Process(target=worker_get, args=(manager, ids[i])))
            tasks[-1].start()
        for task in tasks:
            task.join()

        self.assertEqual(manager.being_solved() + manager.available(), 0)
        self.assertEqual(manager.being_solved(ids[0]) + manager.available(ids[0]), 0)
        self.assertEqual(manager.get_solved(), 3)
        self.assertEqual(manager.get_used(), 3)
        service.stop()
        proc.join()

if __name__ == '__main__':
    unittest.main()

