from recaptcha_manager.api import ManualManager, AntiCaptcha, TwoCaptcha
import recaptcha_manager.api
import random
import time


def exc_handler(exc):
    """
    This exc_handler ignores all exceptions and retries the HTTP requests that caused them till they succeed
    """

    print(f'Exception {exc} encountered: Request will be automatically retried!')

def main(total_run):

    # Create a queue and an Manualmanager instance
    request_queue = recaptcha_manager.api.generate_queue()
    manager = ManualManager.create(request_queue=request_queue)

    # Create a service, and spawn a service process. Uncomment to use 2Captcha instead
    # service = TwoCaptcha.create_service(key=api_key, request_queue=request_queue)
    service = AntiCaptcha.create_service(key=api_key, request_queue=request_queue)
    service_proc = service.spawn_process(exc_handler=exc_handler)

    # Pre-send one captcha request before we enter the loop
    batch_id = manager.send_request(number=1, url=url, web_key=site_key, captcha_type=captcha_type)
    count = 0
    while True:
        # Check if the service process is still working
        service.get_exception()

        # Get the captcha request using the id that we got
        try:
            captcha_answer = manager.get_request(batch_id=batch_id, max_block=30)
        except recaptcha_manager.api.exceptions.Exhausted:
            break  # Manager is no longer usable
        except (recaptcha_manager.api.exceptions.TimeOutError, recaptcha_manager.api.exceptions.EmptyError):
            # This may be the first few captcha requests (which take longer) or some issue is there with solving
            # service. So, we continue to top where it will check for errors in captcha solving service and send more
            # requests
            continue

        # captcha_answer is a dictionary containing useful information about the solved captcha, with the actual
        # token under key 'answer'
        print(captcha_answer)
        token = captcha_answer['answer']

        # Pre-send another captcha request before we do some other task to reduce future waiting time. Make sure to
        # check whether the batch_id returned is not None. This can happen if you attempt to send requests when the
        # manager has already stopped
        new_batch_id = manager.send_request(number=1, url=url, web_key=site_key, captcha_type=captcha_type)
        if new_batch_id is not None:
            batch_id = new_batch_id

        # You can now use the token to submit forms, etc. Sleep is used here instead to mock that
        time.sleep(random.randint(5, 10))

        # Stop manager if limit reached. Manager will completely stop only after all registered requests are solved
        # as well (Use force_stop() to stop manager immediately instead).
        count += 1
        if count == total_run:
            print('Manager stopped')
            manager.stop()

    # Stop the service process
    service.stop()
    service_proc.join()


site_key = '6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-'
captcha_type = 'v2'
url = 'https://www.google.com/recaptcha/api2/demo'

api_key = ''
total_runs = 5

# Remember to protect your main with this clause!
if __name__ == "__main__":
    if not api_key:
        raise ValueError('no value for "api_key" provided')
    main(total_runs)
