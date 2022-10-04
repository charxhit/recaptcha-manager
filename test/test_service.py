import unittest
import time
from recaptcha_manager.api import AntiCaptcha, generate_queue, AutoManager, multiprocessing
from recaptcha_manager.api.exceptions import BadDomainError, BadSiteKeyError, BadAPIKeyError, NoBalanceError, LowBidError, Errors
from recaptcha_manager.api.services import DummyService


def check_error(child_conn, service):
    child_conn.send('started')
    child_conn.recv()
    try:
        service.get_exception()
    except Errors:
        child_conn.send('success')
        return
    except:
        child_conn.send('fail')
        raise
    child_conn.send('no error')


class AntiCaptchaBadURL(AntiCaptcha):
    api_url = 'urlWithMissingSchema'


class MyClass:
    @staticmethod
    def exc_handler():
        pass


class TestService(unittest.TestCase):
    def test_spawn_process(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue)
        service_proc = service.spawn_process(exc_handler=MyClass.exc_handler)
        time.sleep(5)
        self.assertTrue(service.is_alive())

        with self.assertRaises(RuntimeError):
            service.spawn_process(exc_handler=MyClass.exc_handler)

        service.stop()
        service_proc.join()

    def test_stop(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue)
        proc = service.spawn_process()
        service.stop()
        proc.join(timeout=10)

        self.assertIsNotNone(proc.exitcode)
        self.assertEqual(service.is_stopped(), True)
        self.assertEqual(service.is_alive(), False)

    def test_safe_join(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='BadAPIKeyError')
        proc = service.spawn_process()
        self.assertIsNone(service.safe_join(proc, max_block=3))
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)
        time.sleep(5)
        self.assertIsNotNone(service.safe_join(proc, max_block=3))

    def test_stop_with_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='BadAPIKeyError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)
        time.sleep(5)
        with self.assertRaises(BadAPIKeyError):
            service.get_exception()

        self.assertEqual(service.is_stopped(), True)
        self.assertEqual(service.is_alive(), False)

        proc.join(timeout=10)

    def test_bad_domain_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='BadDomainError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)

        with self.assertRaises(BadDomainError):
            manager.get_request(max_block=15)

        service.stop()
        proc.join(timeout=10)

    def test_bad_sitekey_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='BadSiteKeyError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)

        with self.assertRaises(BadSiteKeyError):
            manager.get_request(max_block=15)

        proc.join(timeout=10)

    def test_bad_api_key_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='BadAPIKeyError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)
        time.sleep(5)

        with self.assertRaises(BadAPIKeyError):
            service.get_exception()

        proc.join(timeout=10)

    def test_no_balance_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='NoBalanceError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)
        time.sleep(5)

        with self.assertRaises(NoBalanceError):
            service.get_exception()

        proc.join(timeout=10)

    def test_low_bid_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='LowBidError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')
        manager.send_request(initial=1)
        time.sleep(5)

        with self.assertRaises(LowBidError):
            service.get_exception()

        proc.join(timeout=10)

    def test_multiple_proc_error(self):
        request_queue = generate_queue()
        service = DummyService.create_service('', request_queue, error='LowBidError')
        proc = service.spawn_process()
        manager = AutoManager.create(request_queue, 'http://test.com', '', 'v2')

        child, parent = multiprocessing.Pipe()
        p = multiprocessing.Process(target=check_error, args=(child, service))
        p.start()
        parent.recv()

        manager.send_request(initial=1)
        time.sleep(5)

        with self.assertRaises(LowBidError):
            service.get_exception()

        with self.assertRaises(LowBidError):
            service.get_exception()

        parent.send('go')
        self.assertEqual(parent.recv(), 'success')

        p.join(timeout=10)
        proc.join(timeout=10)


if __name__ == '__main__':
    unittest.main()
