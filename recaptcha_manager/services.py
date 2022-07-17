import traceback
import warnings
from abc import abstractmethod, ABC
from requests_futures.sessions import FuturesSession
from concurrent.futures._base import Future
import multiprocess as multiprocessing
import recaptcha_manager
from recaptcha_manager.manager import ObjProxy, BaseRequest
from recaptcha_manager.exceptions import LowBidError, NoBalanceError, BadDomainError, BadAPIKeyError, BadSiteKeyError, UnexpectedResponse
import urllib3
import queue
from time import sleep
import time
from requests.adapters import HTTPAdapter


def exception_catch_decorator(func):
    def decorator(self, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.exc = e
    return decorator


class CustomBaseManager(multiprocessing.managers.BaseManager):
    pass


class BaseService(ABC):
    """Base class for all Services. Acts as an interface between your program and captcha service"""

    session = None
    name = None
    api_url = None

    def __init__(self, key, request_queue, proxy_ini=False):

        if not proxy_ini: raise RuntimeError("Services should be created using the create() method")

        self.stopped = False
        self.request_queue = request_queue
        self.proxy = None
        self.process = None
        self.exc = None
        self.unsolved = []
        self.ci_list = []
        self.key = key
        self.running = False

    def set_proxy(self, proxy):
        """
        Sets proxy to communicate with other processes

        :meta private:
        """
        self.proxy = proxy

    def get_proxy(self):
        """
        Returns proxy to communicate with other processes

        :meta private:
        """
        return self.proxy

    def stop(self):
        """
        Stops the service
        """

        if self.stopped is True:
            raise RuntimeError("Service has already been stopped")

        self.stopped = True

    def is_alive(self):
        """
        Check whether the service process is alive

        :return: Whether the service process is still running or not
        :rtype: bool
        """

        return self.running

    def is_stopped(self):
        """
        Check whether the service has been stopped.

        :return: Whether the service has been asked to stop or not
        :rtype: bool
        """

        return self.stopped

    def get_exception(self):
        """
        If an exception has been raised in the service process, this re-raises the exception in the process that
        calls this function. Otherwise, returns None
        """

        if self.exc is None:
            return None

        raise type(self.exc[0])(self.exc[1])

    @classmethod
    def create_service(cls, *args, **kwargs):
        """
        Properly initializes a class instance.

        :return: A proxy instance of class. Has same functionality as a regular instance and can share state between
                 processes.
        :rtype: ServiceObjProxy
        """

        class_str = cls.__name__
        CustomBaseManager.register(class_str, cls, ServiceObjProxy, exposed=tuple(dir(cls)))

        # Start a manager process
        manager = CustomBaseManager()
        manager.start()

        # Create and store instance. We must store this proxy instance since its passed in request_queue to another
        # process whenever a captcha request is required. This allows sharing of state between processes.
        inst = eval("manager.{}(args, kwargs, proxy_ini=True)".format(class_str))
        inst.set_proxy(inst)

        return inst

    def _append_data_for_failed(self, request, response_obj, error=False):
        """
        Called in case the solving service was not able to service our request. Can be due to server side issue,
        or faulty information provided through managers

        :param request: The details of the captcha task
        :param requests.Response response_obj: The response object where we are going to append data for this case
        :param error: Whether there was an error in information provided by manager
        """

        assert error in ['BadDomainError', 'BadSiteKeyError', False]
        response_obj.request = request

        # Setting the attribute to False signifies that although the request needs to be removed from the current
        # list, it will be re-added to the starting queue
        response_obj.remove_request = False
        if error == 'BadDomainError':
            response_obj.error = BadDomainError(f"{self.name} reported that the domain \"{request['job'].url}\" is"
                                                f" incorrect")
        elif error == 'BadSiteKeyError':
            response_obj.error = BadSiteKeyError(f"{self.name} reported that the sitekey \"{request['job'].web_key}\" "
                                                 f"is incorrect for the url \"{request['job'].url}\"")

    @staticmethod
    def _append_data_for_unsolved(request, response_obj, captcha_id):
        """
        Called when solving service successfully registers our captcha task.

        :param requests.Response response_obj: The response object where we are going to append data for this case
        :param captcha_id: id of the captcha task returned by the service
        """
        response_obj.request = request
        response_obj.captcha_id = captcha_id

        # We set the attribute to mark the request as completed and can be safely removed
        response_obj.remove_request = True

    @staticmethod
    def _append_data_for_solved(request, response_obj, answer, time_solved, cost):
        """
        Called when solving service successfully solves our captcha task.

        :param request: Details about the captcha task
        :param requests.Response response_obj: Response object returned when requesting status of task
        :param answer: Answer returned by server
        :param time_solved: Time when captcha was solved
        :param cost: Cost of solving captcha
        """
        response_obj.request = request
        response_obj.answer = answer
        response_obj.time_solved = time_solved
        response_obj.cost = cost
        # We set the attribute to mark the request as completed and can be safely removed
        response_obj.remove_request = True

    def spawn_process(self, retry=None, exc_handler=None, disable_insecure_warning=True, **kwargs) -> multiprocessing.Process:
        """
        Wrapper for starting the background service process.


        :param urllib3.util.Retry retry: Retry object to be added to each request
        :param callable exc_handler: An optional user-defined function which runs whenever an exception occurs. Defaults
                                     to None
        :param boolean disable_insecure_warning: Whether to disable InsecureRequestWarning

        :returns: Started solving service process
        :rtype: multiprocessing.Process

        The optional ``exc_handler`` parameter takes a callable which is called everytime an exception occurs. The
        exception is passed as a parameter to the callable. By default, after the exception occurs and
        ``exc_handler`` has been called, the request that raised the exception is retried. However, you can raise the
        exception from within the handler in which case the service process will quit.

        Actual implementation inside class ServiceObjProxy
        """
        raise NotImplementedError("Creating a service process directly is no longer supported in version 0.0.3 and "
                                  "above. Check the updated documentation for a full list of changes")

    def _clear_requests(self):
        """
        In case of an error, we clear all requests responsibly, so that manager statistics do not get corrupted
        """

        # Remove any requests that were already taken care of.
        self.unsolved = [request for request in self.unsolved if request is not None]
        self.ci_list = [request for request in self.ci_list if request is not None]

        for request in self.ci_list:
            manager: recaptcha_manager.manager.BaseRequest = request['manager']
            manager.request_cancelled(request['job'], unsolved=False)

        for request in self.unsolved:
            manager: recaptcha_manager.manager.BaseRequest = request['manager']
            manager.request_cancelled(request['job'], unsolved=True)

    def requests_manager(self, exc_handler=None, retry=None, disable_insecure_warning=True):
        """
        Main function which produces captcha tokens based on requests in ``request_queue`` through a captcha solving
        service. Exits when ``stopped.value`` is set to ``False``

        :param callable exc_handler: An optional user-defined function which runs whenever an exception occurs.
        :param requests.packages.urllib3.util.retry.Retry retry: Retry object to be added to each request
        :param boolean disable_insecure_warning: Whether or not to disable
                                                :exc:`~urllib3.exceptions.InsecureRequestWarning`


        Keep in mind that this function blocks until the service is stopped. Therefore, if you are calling this
        method directly, it must be started in a different process than the main program.
        """
        try:
            self.exc = None
            self.running = True
            self.session = FuturesSession(max_workers=8)

            if retry:
                self.session.mount('http://', HTTPAdapter(max_retries=retry))
                self.session.mount('https://', HTTPAdapter(max_retries=retry))

            if disable_insecure_warning:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            # This stopped's value can be modified through parent process from outer scope to end this process here
            while not self.stopped:

                # Get all requests submitted to requestsQueue and append them to the list self.ci_list
                while True:
                    try:
                        # cap_info is a dictionary containing a manager and time when it was
                        # added to request_queue. Example: {'manager':..., 'timeRequested':...}
                        cap_info = self.request_queue.get(block=False)
                    except queue.Empty:
                        break
                    else:
                        self.ci_list.append(cap_info)

                # If there are no requests then sleep
                if len(self.ci_list) + len(self.unsolved) == 0:
                    sleep(3)

                # This variable will store the futures received from requests-futures when sending captcha request to
                # service
                temp = []

                # Remove any requests in self.ci_list if they were marked completed (None)
                self.ci_list = [request for request in self.ci_list if request is not None]

                # In here we create and send a list of futures from self.ci_list
                for index, request in enumerate(self.ci_list):

                    # This contains the manager which created the request
                    inst = request['manager']

                    # If the manager is not taking any more requests then mark the request as completed in self.ci_list
                    if inst.stop_new_requests:
                        self.ci_list[index] = None
                        inst.request_cancelled(request['job'], unsolved=False)
                        continue

                    # Create a future using requests-futures to send captcha tasks concurrently and append it to temp list
                    future_request = self._api_register_request(request)
                    temp.append(future_request)

                # Then we wait for all futures to complete by iterating over temp
                for i, future in enumerate(temp):
                    try:
                        response = future.result()

                    except (NoBalanceError, LowBidError, BadAPIKeyError, UnexpectedResponse):
                        raise

                    except Exception as e:
                        # If an exc_handler function is present and an exception occurs, we run that function first
                        if exc_handler:
                            exc_handler(e)
                            continue
                        else:
                            raise

                    try:
                        # remove_request is an attribute added to response after a captcha task has been signalled to
                        # be safe to remove from self.ci_list. It's worth noting that being safe to remove does not
                        # necessarily mean that the request has been successfully registered with the captcha solving
                        # service. For that, it's value (True/False) is also required (check below).
                        response.remove_request

                    except AttributeError:
                        continue

                    else:
                        # We mark the request as completed
                        self.ci_list[i] = None

                        # This means that the request was successfully registered and completed
                        if response.remove_request is True:
                            self._add_unsolved_task(response)

                        # This means that the request had faulty configuration. Therefore, we log it and raise whenever
                        # it is requested again through the manager
                        elif response.remove_request is False:
                            self._add_error(response)

                        continue

                # Remove all completed requests from ci_list
                self.ci_list = [request for request in self.ci_list if request is not None]

                # Get answers for captcha tasks produced. Wait here to prevent too many requests
                if len(self.unsolved) > 0:
                    sleep(6)
                    self._captcha_get_answer(exc_handler=exc_handler)
                else:
                    sleep(2)

            self.running = False

        except Exception as e:
            self._clear_requests()
            msg = "{}\n\nOriginal {}".format(e, traceback.format_exc())
            self.exc = (e, msg)
            self.running = False

    def _captcha_get_answer(self, exc_handler):
        """Requests answer from captcha service for produced captcha tasks"""

        # This will store the futures received from request-futures when asking for answers of produced captcha tasks
        # from service
        temp = []

        for index, request in enumerate(self.unsolved):
            manager: BaseRequest = request['manager']
            if manager.finished is True:
                self.unsolved[index] = None
                manager.request_cancelled(job=request['job'], unsolved=True)

        self.unsolved = [request for request in self.unsolved if request is not None]

        # Unsolved stores the captcha tasks and their details registered with the service. We iterate over this and
        # create list of futures that fetch the answers for the captcha tasks

        for index, request in enumerate(self.unsolved):
            future_request = self._api_fetch_answer(request)
            temp.append(future_request)

        # We then wait for the futures to resolve
        for index, future in enumerate(temp):
            try:
                response = future.result()

            except UnexpectedResponse:
                raise

            except Exception as e:
                # If an exc_handler function is present and an exception occurs, we run that function first
                if exc_handler:
                    exc_handler(e)
                    continue
                else:
                    raise e from None

            try:
                # remove_request is an attribute added to response after a task has been successfully solved with the
                # service. If this is not there then the request was not solved and we cannot mark it as completed in
                # self.unsolved
                response.remove_request

            except AttributeError:
                continue

            else:
                # We mark the request as completed
                self.unsolved[index] = None

                if response.remove_request is True:
                    # We got the answer so we add the details to the relevant manager
                    self._add_solved_task(response)

                elif response.remove_request is False:
                    # This means there was an error in solving this request, hence we remove it and add it back to be
                    # solved later
                    manager: recaptcha_manager.manager.BaseRequest = response.request
                    manager.request_failed(job=response.request['job'])

        # We remove completed tasks from self.unsolved list
        self.unsolved = [request for request in self.unsolved if request is not None]

    def _add_unsolved_task(self, response_obj):
        request = response_obj.request
        inst: recaptcha_manager.manager.BaseRequest = request['manager']
        inst.request_created()
        self.unsolved.append({'task_id': response_obj.captcha_id, 'startTime': time.time(), 'manager': inst,
                              'timeRequested': time.time()-5, 'job': request['job']})

    @staticmethod
    def _add_solved_task(response_obj):
        request = response_obj.request
        manager: recaptcha_manager.manager.BaseRequest = request['manager']
        manager.response_queue.put(
            {'captcha_id': request['task_id'], 'answer': response_obj.answer, 'error': None,
             'timeSolved': response_obj.time_solved, 'cost': response_obj.cost, 'timeDelivered': time.time(),
             'timeRequested': request['timeRequested'], 'batch_id': request['job'].batch_id})

        # We call requestsSolved to edit relevant counters.
        manager.request_solved(response_obj.time_solved - request['timeRequested'])

    @staticmethod
    def _add_error(response_obj):
        request = response_obj.request
        manager: recaptcha_manager.manager.BaseRequest = request['manager']
        manager.response_queue.put(
            {'timeDelivered': time.time(), 'error': response_obj.error,
             'timeRequested': time.time(), 'batch_id': request['job'].batch_id})

        # We call requestsSolved to edit relevant counters.
        manager.request_solved(error=True)

    @abstractmethod
    def _api_parse_request(self, d):
        pass

    @abstractmethod
    def _api_parse_answer(self, request):
        pass

    @abstractmethod
    def _api_register_request(self, request):
        pass

    @abstractmethod
    def _api_fetch_answer(self, request):
        pass


class DummyFuture:

    def __init__(self, exc=None):
        self.exc = exc

    def result(self):
        if self.exc is None:
            return self
        else:
            exec(f"raise {self.exc}")


class DummyService(BaseService):
    name = "DummyService"

    def __init__(self, key, request_queue, error=None, solve_time=0, proxy_ini=False):
        super().__init__(key, request_queue, proxy_ini)
        self.solve_time = solve_time
        if error in ['BadDomainError', 'BadSiteKeyError', None]:
            self.error = None
            self.local_error = error
        else:
            self.error = error
            self.local_error = None

    @classmethod
    def create_service(cls, key, request_queue, error=None, solve_time=0):
        """:rtype: DummyService"""
        class_str = cls.__name__
        CustomBaseManager.register(class_str, cls, ServiceObjProxy, exposed=tuple(dir(cls)))

        # Start a manager process
        manager = CustomBaseManager()
        manager.start()

        # Create and store instance. We must store this proxy instance since its passed in request_queue to another
        # process whenever a captcha request is required. This allows sharing of state between processes.
        inst = eval("manager.{}(key, request_queue, error=error, solve_time=solve_time, proxy_ini=True)".format(class_str))
        inst.set_proxy(inst)

        return inst

    def _api_register_request(self, request):
        response_obj = DummyFuture(exc=self.error)
        if self.local_error is not None:
            self._append_data_for_failed(request, response_obj, error=self.local_error)
        else:
            self._append_data_for_unsolved(request, response_obj, 'xxx')
        return response_obj

    def _api_fetch_answer(self, request):
        response_obj = DummyFuture(exc=self.error)
        if self.solve_time != 0:
            request['timeRequested'] = time.time() - self.solve_time
        self._append_data_for_solved(request, response_obj, 'answer', time.time(), 0.003)
        return response_obj

    def _api_parse_answer(self, request):
        pass

    def _api_parse_request(self, d):
        pass


class ServiceObjProxy(ObjProxy):

    def spawn_process(self, retry=None, exc_handler=None, disable_insecure_warning=True) -> multiprocessing.Process:
        """
        Wrapper for starting :meth:`~BaseService.requests_manager` in another process.


        :param urllib3.util.Retry retry: Retry object to be added to each request
        :param callable exc_handler: An optional user-defined function which runs whenever an exception occurs. Defaults
                                     to None
        :param boolean disable_insecure_warning: Whether or not to disable
                                                :exc:`~urllib3.exceptions.InsecureRequestWarning`

        :returns: Started :meth:`~BaseService.requests_manager` process
        :rtype: multiprocessing.Process

        The optional ``exc_handler`` parameter takes a callable which is called everytime an exception occurs. The
        exception is passed as a parameter to the callable. By default, after the exception occurs and
        ``exc_handler`` has been called, the request that raised the exception is retried. However, you can raise the
        exception from within the handler in which case the service process will quit
        """

        if self.is_alive():
            raise RuntimeError('Service has already been started')
        if self.is_stopped():
            raise RuntimeError('This service has already been stopped and can no longer be used')
        if exc_handler is None:
            warnings.warn("No exc_handler specified, any connection errors will result in the termination of service "
                          "process", RuntimeWarning)

        proc = multiprocessing.Process(target=self.get_proxy().requests_manager, kwargs={'retry': retry,
                                                                                'exc_handler': exc_handler,
                                                                                'disable_insecure_warning': disable_insecure_warning})
        proc.start()
        return proc


class AntiCaptcha(BaseService):
    """Uses Anticaptcha captcha service to solve recaptchas

       | URL: https://anti-captcha.com
       | Documentation: https://anti-captcha.com/apidoc"""

    name = 'Anticaptcha'
    api_url = 'http://api.anti-captcha.com/'
    cost = 0.002

    @classmethod
    def create_service(cls, key, request_queue):
        """
        Properly initializes a class instance.

        :param string key: API key of the solving service
        :param request_queue: Queue for communication with managers
        :return: A proxy instance of class. Has same functionality as a regular instance and can share state between
                 processes.
        :rtype: AntiCaptcha
        """
        return super().create_service(key, request_queue)

    def _api_parse_request(self, request):
        """This factory function handles the response from the captcha service regarding task creation. It returns a
           response hook which uses the API provided by the service.

           :param dict request: Contains the manager which created the request and the time when the request was
                                added to the request_queue. Example: {'manager':..., 'timeRequested': ...}

           :return: Response hook to be used with requests-futures
           :rtype: method

           :raises:
                LowBidError: When server reports bid is too low
                NoBalanceError: When server reports balance is insufficient for creating tasks
                BadAPIKeyError: When server reports API Key is invalid
                BadSiteKeyError: When server reports that the sitekey provided is incorrect
                BadDomainError: When the server reports that the domain name is invalid
                RuntimeError: When the server responds with an unidentified error code
        """

        def response_hook(response_obj, *args, **kwargs):

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist, and we give the default value of None
            response_json = response_obj.json()
            error_code = response_json.get('errorCode', None)

            # Now we check the status of the captcha request based on what the server responded with
            if response_json['errorId'] == 0 or response_json['errorId'] == '0':

                # Request successful, server registered the task and we append it to unsolved list after
                # in/decrementing counters since we are removing the request from queue and adding it to unsolved list
                self._append_data_for_unsolved(request, response_obj, response_json['taskId'])

            elif error_code == 'ERROR_NO_SLOT_AVAILABLE':

                # This happens when the bid is too low and not many workers are free. We raise this error so it can
                # be handled by outer scope
                raise LowBidError('Bid too low, raise bid from account settings to create more tasks or use a '
                                  'different service')

            elif error_code == 'ERROR_ZERO_BALANCE':
                raise NoBalanceError('Balance insufficient')

            elif error_code == 'ERROR_KEY_DOES_NOT_EXIST':
                raise BadAPIKeyError('API Key provided is incorrect')

            elif error_code == 'ERROR_RECAPTCHA_INVALID_SITEKEY':
                self._append_data_for_failed(request, response_obj, error='BadSitekeyError')

            elif error_code == 'ERROR_RECAPTCHA_INVALID_DOMAIN':
                self._append_data_for_failed(request, response_obj, error='BadDomainError')

            else:
                raise UnexpectedResponse('Unidentified errorCode provided by server: {}'.format(response_json))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return response_obj

        return response_hook

    def _api_parse_answer(self, request):
        """This factory function handles the response from the captcha service when requesting status of a task.
           It returns a response hook which uses the API provided by the service.

           :param dict request: Contains the manager whcih created the request, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'manager':..., 'timeRequested': ..., 'task_id': ..., 'startTime': ...}
           :return: Response hook to be used with requests-futures
           :rtype: method
           :raises:
                RuntimeError: When the server responds with an unidentified error code
        """

        def response_hook(response_obj, *r_args, **r_kwargs):

            # This is the manager which created the request
            manager: recaptcha_manager.manager.BaseRequest = request['manager']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            response_json = response_obj.json()
            error_code = response_json.get('errorCode', None)

            # Now we check the status of the captcha request based on what the server responded with
            if error_code == 'ERROR_RECAPTCHA_TIMEOUT':

                # For some reason, our captcha wasn't solved. So we mark the request as completed but add it back to
                # the request_queue so it can be registered again after we edit the relevant counters
                self._append_data_for_failed(request, response_obj)

            elif response_json.get('status') is None:
                raise UnexpectedResponse('Unidentified errorCode provided by server: {}'.format(response_json))

            elif response_json['status'] == 'processing':
                # Still not solved
                pass

            elif response_json['status'] == 'ready':
                # We successfully got the g-recaptcha response. We add this to the response_queue along with the time
                # it was solved, the time it was added to response_queue, id of the task and the cost for the captcha
                answer = response_json['solution']['gRecaptchaResponse']
                cost = float(response_json.get('cost', self.cost))
                time_solved = int(response_json.get('endTime', time.time() - 5))
                self._append_data_for_solved(request, response_obj, answer, time_solved, cost)

            else:
                raise UnexpectedResponse('Unidentified errorCode provided by server: {}'.format(response_json))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return response_obj

        return response_hook

    def _api_register_request(self, request):
        """Uses the captcha service API to create and send a request for task creation to server. The request is sent
           asynchronously and is attached with a response hook from self._api_parse_request() function

           :param dict request: Contains the manager which created the request and the time when the request was
                                added to the request_queue. Example: {'manager':..., 'timeRequested': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # This is an instance of a class CaptchaJob
        job: recaptcha_manager.manager.CaptchaJob = request['job']

        # Based on captcha_type, we create a request with relevant post-data
        if job.captcha_type == 'v2':
            data = {'clientKey': self.key,
                    'task': {"type": "NoCaptchaTaskProxyless", "websiteURL": job.url, 'websiteKey': job.web_key,
                             'isInvisible': job.invisible}}
        elif job.captcha_type == 'v3':
            data = {'clientKey': self.key, 'task': {'type': 'RecaptchaV3TaskProxyless', 'websiteURL': job.url,
                                                   'websiteKey': job.web_key, 'minScore': job.min_score,
                                                   'pageAction': job.action}}

        # We now send the request asynchronously and add a response hook to parse the server response in the background
        r = self.session.post(self.api_url + 'createTask', json=data, verify=False, timeout=7,
                              hooks={'response': self._api_parse_request(request)})

        # We return this future
        return r

    def _api_fetch_answer(self, request):
        """Uses the captcha service API to for creating and sending a request to fetch task status from server. The
           request is sent asynchronously and is attached with a response hook from self._api_parse_answer() function

           :param dict request: Contains the manager which created the request, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'manager':..., 'timeRequested': ..., 'task_id': ..., 'startTime': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # Create relevant fields to add to request
        data = {'clientKey': self.key, 'taskId': request['task_id']}

        # Send request asynchronously
        r = self.session.post(self.api_url + 'getTaskResult', json=data, verify=False, timeout=7,
                              hooks={'response': self._api_parse_answer(request)})
        return r


class TwoCaptcha(BaseService):
    """
    Uses 2Captcha captcha service to solve recaptchas

    | URL: https://2captcha.com
    | Documentation: https://2captcha.com/2captcha-api
    """

    name = '2captcha'
    api_url = 'http://2captcha.com/'
    cost = 0.003

    @classmethod
    def create_service(cls, key, request_queue):
        """
        Properly initializes a class instance.

        :param string key: API key of the solving service
        :param request_queue: Queue for communication with managers
        :return: A proxy instance of class. Has same functionality as a regular instance and can share state between
                 processes.
        :rtype: TwoCaptcha
        """
        return super().create_service(key, request_queue)

    def _api_parse_request(self, request):
        """This factory function handles the response from the captcha service regarding task creation. It returns a
           response hook which uses the API provided by the service.

           :param dict request: Contains the manager which created the request and the time when the request was
                                added to the request_queue. Example: {'manager':..., 'timeRequested': ...}

           :return: Response hook to be used with requests-futures
           :rtype: method

           :raises:
                LowBidError: When server reports bid is too low
                NoBalanceError: When server reports balance is insufficient for creating tasks
                BadAPIKeyError: When server reports API Key is invalid
                BadSiteKeyError: When server reports that the sitekey provided is incorrect
                BadDomainError: When the server reports that the domain name is invalid
                RuntimeError: When the server responds with an unidentified error code
        """

        def response_hook(response_obj, *args, **kwargs):

            # This is the manager which created the request.
            inst: recaptcha_manager.manager.BaseRequest = request['manager']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            response_json = response_obj.json()
            error_code = response_json['request']

            # Now we check the status of the captcha request based on what the server responded with
            if response_json['status'] == 1:

                # Request successful, server registered the task and we append it to unsolved list after
                # in/decrementing counters since we are removing the request from queue and adding it to unsolved list
                self._append_data_for_unsolved(request, response_obj, response_json['request'])

            elif error_code == 'ERROR_NO_SLOT_AVAILABLE':

                # This happens when the there are too many captchas already being solved.
                pass

            elif error_code == 'ERROR_ZERO_BALANCE':
                raise NoBalanceError('Balance insufficient')

            elif error_code in ['ERROR_KEY_DOES_NOT_EXIST', 'ERROR_WRONG_USER_KEY']:
                raise BadAPIKeyError('API Key provided is incorrect')

            elif error_code == 'ERROR_GOOGLEKEY':
                self._append_data_for_failed(request, response_obj, error='BadSitekeyError')

            elif error_code == 'ERROR_BAD_TOKEN_OR_PAGEURL':
                self._append_data_for_failed(request, response_obj, error='BadDomainError')

            else:
                raise UnexpectedResponse('Unidentified errorCode provided by server: {}'.format(response_json))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return response_obj

        return response_hook

    def _api_parse_answer(self, request):
        """This factory function handles the response from the captcha service when requesting status of a task.
           It returns a response hook which uses the API provided by the service.

           :param dict request: Contains the manager which created the request, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'manager':..., 'timeRequested': ..., 'task_id': ..., 'startTime': ...}
           :return: Response hook to be used with requests-futures
           :rtype: method
           :raises:
                RuntimeError: When the server responds with an unidentified error code
        """

        def response_hook(response_obj, *args, **kwargs):

            # This is the manager which created the request.
            manager: recaptcha_manager.manager.BaseRequest = request['manager']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            response_json = response_obj.json()
            error_code = response_json['request']

            # Now we check the status of the captcha request based on what the server responded with
            if response_json['status'] == 1:
                # We successfully got the g-recaptcha response. We add this to the response_queue along with the time
                # it was solved, the time it was added to response_queue, id of the task and the cost for the captcha
                answer = response_json['request']
                cost = self.cost
                time_solved = time.time() - 3

                self._append_data_for_solved(request, response_obj, answer, time_solved, cost)

            elif error_code == 'ERROR_CAPTCHA_UNSOLVABLE':

                # For some reason, our captcha wasn't solved. So we mark the request as completed but add it back to
                # the request_queue so that it can be registered again after we edit the relevant counters
                self._append_data_for_failed(request, response_obj)

            elif error_code == 'CAPCHA_NOT_READY':
                # Still not solved
                pass

            else:
                raise UnexpectedResponse('Unidentified status provided by server: {}'.format(response_json))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return response_obj

        return response_hook

    def _api_register_request(self, request):
        """Uses the captcha service API to create and send a request for task creation to server. The request is sent
           asynchronously and is attached with a response hook from self._api_parse_request() function

           :param dict request: Contains the manager which created the request and the time when the request was
                                added to the request_queue. Example: {'manager':..., 'timeRequested': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # This is an instance of class CaptchaJob
        job: recaptcha_manager.manager.CaptchaJob = request['job']

        if job.invisible:
            invisible = 1
        else:
            invisible = 0

        # Based on captcha_type, we create a request with relevant post-data
        if job.captcha_type == 'v2':
            data = self.api_url + "in.php?key={}&method=userrecaptcha&googlekey={}&pageurl={}&invisible={}&" \
                   "json=1".format(self.key, job.web_key, job.url, invisible)
        elif job.captcha_type == 'v3':
            data = self.api_url + "in.php?key={}&method=userrecaptcha&version=v3&action={}&min_score={}&" \
                   "googlekey={}&pageurl={}&json=1".format(self.key, job.action, job.min_score, job.web_key,
                                                           job.url)

        # We now send the request asynchronously and add a response hook to parse the server response in the background
        r = self.session.post(data, verify=False, timeout=7, hooks={'response': self._api_parse_request(request)})

        # We return this future
        return r

    def _api_fetch_answer(self, request):
        """Uses the captcha service API to for creating and sending a request to fetch task status from server. The
           request is sent asynchronously and is attached with a response hook from self._api_parse_answer() function

           :param dict request: Contains the manager which created the request, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'manager':..., 'timeRequested': ..., 'task_id': ..., 'startTime': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # Create relevant fields to add to request
        data = self.api_url + "res.php?key={}&action=get&id={}&json=1".format(self.key, request['task_id'])

        # Send request asynchronously
        r = self.session.post(data, verify=False, timeout=7, hooks={'response': self._api_parse_answer(request)})
        return r


class CapMonster(AntiCaptcha):
    """
    Uses Capmonster service to solve captcha. The service offers many similar APIs to other popular services

    URL: https://capmonster.cloud
    """

    name = 'Capmonster'
    api_url = 'https://api.capmonster.cloud/'
    cost = 0.0006

    @classmethod
    def create_service(cls, key, request_queue):
        """
        Properly initializes a class instance.

        :param string key: API key of the solving service
        :param request_queue: Queue for communication with managers
        :return: A proxy instance of class. Has same functionality as a regular instance and can share state between
                 processes.
        :rtype: CapMonster
        """
        return super().create_service(key, request_queue)

