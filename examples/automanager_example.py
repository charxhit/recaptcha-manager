from recaptcha_manager.api import AutoManager, AntiCaptcha, TwoCaptcha
import recaptcha_manager.api
import random
import time


def exc_handler(exc):
    """
    This exc_handler ignores all exceptions and retries the HTTP requests that caused them till they succeed
    """

    print(f'Exception {exc} encountered: Request will be automatically retried!')
    # raise

def main(total_run):

    # Create a queue and an Automanager instance
    request_queue = recaptcha_manager.api.generate_queue()
    manager = AutoManager.create(request_queue=request_queue, url=url, web_key=site_key, captcha_type=captcha_type)

    # Create a service, and spawn a service process. Uncomment to use 2Captcha instead
    service = TwoCaptcha.create_service(key=api_key, request_queue=request_queue)
    # service = AntiCaptcha.create_service(key=api_key, request_queue=request_queue)
    service_proc = service.spawn_process(exc_handler=exc_handler)

    count = 0
    while True:
        # Check if the service process is still working
        service.get_exception()

        # Signal Automanager to send optimal number of requests, and then wait till one is solved
        manager.send_request(initial=2)
        try:
            captcha_answer = manager.get_request(max_block=60)
        except recaptcha_manager.api.exceptions.Exhausted:
            break  # Manager is no longer usable
        except recaptcha_manager.api.exceptions.TimeOutError:
            # This may be the first few captcha requests (which take longer) or some issue is there with solving
            # service. So, we continue to top where it will check for errors in captcha solving service and send more
            # requests
            continue

        # captcha_answer is a dictionary containing useful information about the solved captcha, with the actual
        # token under key 'answer'
        print(captcha_answer)
        token = captcha_answer['answer']

        # You can now use this token to submit forms, etc. Sleep is used here instead to mock that
        time.sleep(random.randint(5, 10))

        # Print out the avg time your function waits to receive a captcha answer. This will reduce over time
        print(f"Average time spent waiting for a captcha answer : {manager.get_waiting_time()}")

        # Print out some other statistics regarding captcha solving as well
        print(f"Average time solving service takes to solve the captcha : {manager.get_solving_time()}")
        print(f"One captcha is requested every {manager.get_use_rate()}s from the manager by your program\n")

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
api_key = ''
captcha_type = 'v2'
url = 'https://www.google.com/recaptcha/api2/demo'
total_runs = 20

# Remember to protect your main with this clause incase you are running on Windows!
if __name__ == "__main__":
    if not api_key:
        raise ValueError('no value for "api_key" provided')

    main(total_runs)
