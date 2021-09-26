from pickle import PicklingError
from abc import abstractmethod, ABC
from requests_futures.sessions import FuturesSession
from concurrent.futures._base import Future
import multiprocess
import recaptcha_manager
from recaptcha_manager.exceptions import LowBidError, NoBalanceError, BadDomainError, BadAPIKeyError, BadSitekeyError
import urllib3
import multiprocessing
import queue
from time import sleep
import time
from requests.adapters import HTTPAdapter




class BaseService(ABC):
    """Base class for all Services. Acts as an interface between your program and captcha service"""

    unsolved = []
    ci_list = []
    request_queue = None
    session = None
    key = None
    name = None
    api_url = None
    cost = None

    @classmethod
    def spawn_process(cls, flag, request_queue, key, retry=None, exc_handler=None, state=None,
                      disable_insecure_warning=False):
        """
        Wrapper for starting :meth:`~BaseService.requests_manager` in another process.

        :param multiprocessing.sharedctypes.Synchronized flag: A shared object which stores a boolean value. To signal
                                                               this function to quit, set ``flag.value`` to ``False``
        :param multiprocessing.Queue request_queue: Queue used for communication with instances of :class:`AutoManager`
        :param str key: API key for the captcha service
        :param urllib3.util.Retry retry: Retry object to be added to each request
        :param callable exc_handler: An optional user-defined function which runs whenever an exception occurs. Defaults
                                     to None
        :param tuple state: If a state is provided, requests_manager uses that instead of creating a new one
        :param boolean disable_insecure_warning: Whether or not to disable
                                                :exc:`~urllib3.exceptions.InsecureRequestWarning`

        :returns: Started :meth:`~BaseService.requests_manager` process
        :rtype: multiprocessing.Process

        The optional ``exc_handler`` parameter takes a callable which is called everytime an exception occurs. The
        exception is passed as a parameter to the callable.By default, after the exception occurs and ``exc_handler``
        has been called, the exception is raised to outer scope. If you have handled the exception in ``exc_handler``
        and do not want it to be raised, then return a Truthy object in ``exc_handler`` and the exception will be
        ignored.
        """
        try:
            process = multiprocessing.Process(target=cls.requests_manager, args=(flag, request_queue, key, ),
                                              kwargs={'exc_handler': exc_handler, 'state': state,
                                                      'disable_insecure_warning': disable_insecure_warning,
                                                      'retry': retry})
        except PicklingError:
            process = multiprocess.Process(target=cls.requests_manager, args=(flag, request_queue, key,),
                                           kwargs={'exc_handler': exc_handler, 'state': state,
                                                   'disable_insecure_warning': disable_insecure_warning,
                                                   'retry': retry})
        process.start()
        return process

    @classmethod
    def get_state(cls):
        """
        Return state of class

        :rtype: tuple
        """
        return cls.unsolved, cls.ci_list, cls.name

    @classmethod
    def requests_manager(cls, flag, request_queue, key, exc_handler=None, state=None, retry=None,
                         disable_insecure_warning=False):
        """
        Main function which produces captcha tokens based on requests in ``request_queue`` through a captcha solving
        service. Exits when ``flag.value`` is set to ``False``

        :param multiprocessing.sharedctypes.Synchronized flag: A shared object which stores a boolean value. To signal this function to quit, set
                                                              ``flag.value`` to ``False``
        :param multiprocessing.Queue request_queue: Queue used for communication with instances of AutoManager Class
        :param callable exc_handler: An optional user-defined function which runs whenever an exception occurs. Defaults
                                   to None
        :param str key: API key for the captcha service
        :param requests.packages.urllib3.util.retry.Retry retry: Retry object to be added to each request
        :param callable exc_handler: An optional user-defined function which runs whenever an exception occurs. Defaults
                                     to None
        :param tuple state: If a state is provided, this function uses that instead of creating a new one
        :param boolean disable_insecure_warning: Whether or not to disable
                                                :exc:`~urllib3.exceptions.InsecureRequestWarning`


        Keep in mind that this function blocks until ``flag.value`` is set to False (or an uncaught exception is
        raised). Therefore, if you are calling this method directly, it must be started in a different process than
        the main program.
        """
        # Clear any previous state that might be present
        cls.unsolved, cls.ci_list = [], []

        # Create a shallow copy of state if it was provided to prevent loss of data if switching/restarting
        # requests_manager function of a sub-class. State can be requested through cls.get_state() method
        if state:
            unsolved, ci_list, name = state
            cls.ci_list = list(ci_list)

            # If the provided state was from the same service, only then we keep the already registered tasks
            if name == cls.name:
                cls.unsolved = list(unsolved)
            else:
                # We remove all tasks registered with a different service, and add them back to the queue
                for request in unsolved:
                    if not request:
                        continue
                    inst: recaptcha_manager.AutoManager = request['instance']
                    inst.request_failed()

                cls.unsolved = []

            # Remove any requests that were already taken care of.
            cls.unsolved = [v for v in cls.unsolved if v]
            cls.ci_list = [v for v in cls.ci_list if v]
        else:
            # Otherwise we simply refresh the state
            cls.unsolved, cls.ci_list = [], []

        cls.request_queue = request_queue
        cls.key = key
        cls.session = FuturesSession(max_workers=8)

        if retry:
            cls.session.mount('http://', HTTPAdapter(max_retries=retry))
            cls.session.mount('https://', HTTPAdapter(max_retries=retry))

        if disable_insecure_warning:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # This flag's value can be modified through parent process from outer scope to end this process here
        while flag.value:

            # Get all requests submitted to requestsQueue and append them to the list cls.ci_list
            while True:
                try:
                    # cap_info is a dictionary containing an instance of AutoManager and time when it was
                    # added to request_queue. Example: {'instance':..., 'timeToQ':...}
                    cap_info = cls.request_queue.get(block=False)
                except queue.Empty:
                    break
                else:
                    cls.ci_list.append(cap_info)

            # If there are no requests then sleep
            if len(cls.ci_list) + len(cls.unsolved) == 0:
                sleep(3)

            # This variable will store the futures received from requests-futures when sending captcha request to
            # service
            temp = []

            # In here we create and send a list of futures from cls.ci_list
            for index, request in enumerate(cls.ci_list):

                # This contains the instance of a subclass of BaseRequest
                inst = request['instance']

                # If the instance is not taking any more requests then mark the request as completed in cls.ci_list
                if inst.stop_new_requests:
                    cls.ci_list[index] = None
                    continue

                # Create a future using requests-futures to send captcha tasks concurrently and append it to temp list
                future_request = cls._api_register_request(request)
                temp.append(future_request)

            # Remove any requests in cls.ci_list if they were marked completed (None)
            cls.ci_list = [v for v in cls.ci_list if v]

            # Then we wait for all futures to complete by iterating over temp
            for i, future in enumerate(temp):
                try:
                    response = future.result()

                except Exception as e:
                    # If an exc_handler function is present and an exception occurs, we run that function first
                    if exc_handler:
                        status = exc_handler(e)
                        if not status:
                            raise e from None
                        continue
                    else:
                        raise e from None

                try:
                    # remove_request is an attribute added to response after a task has been successfully registered
                    # with the service. If this is not there then the request was not registered and we cannot mark
                    # it as completed in cls.ci_list
                    response.remove_request

                except AttributeError:
                    continue

                else:
                    # We mark the request as completed
                    cls.ci_list[i] = None
                    continue

            # Remove all completed requests from ci_list
            cls.ci_list = [v for v in cls.ci_list if v]

            # Get answers for captcha tasks produced. Wait here to prevent too many requests
            if len(cls.unsolved) > 0:
                sleep(6)
                cls._captcha_get_answer(exc_handler=exc_handler)
            else:
                sleep(2)

    @classmethod
    def _captcha_get_answer(cls, exc_handler):
        """Requests answer from captcha service for produced captcha tasks"""

        # This will store the futures received from request-futures when asking for answers of produced captcha tasks
        # from service
        temp = []

        # Unsolved stores the captcha tasks and their details registered with the service. We iterate over this and
        # create list of futures that fetch the answers for the captcha tasks
        for i, taskDict in enumerate(cls.unsolved):
            future_request = cls._api_fetch_answer(taskDict)
            temp.append(future_request)

        # We then wait for the futures to resolve
        for i, future in enumerate(temp):
            try:
                response = future.result()
            except Exception as e:
                # If an exc_handler function is present and an exception occurs, we run that function first
                if exc_handler:
                    status = exc_handler(e)
                    if not status:
                        raise e from None
                    continue
                else:
                    raise e from None

            try:
                # remove_request is an attribute added to response after a task has been successfully solved with the
                # service. If this is not there then the request was not solved and we cannot mark it as completed in
                # cls.unsolved
                response.remove_request

            except AttributeError:
                continue

            else:
                # We got the answer or the task was unsolvable. Hence we mark the request as solved in cls.unsolved
                cls.unsolved[i] = None

        # We remove completed tasks from cls.unsolved list
        cls.unsolved = [i for i in cls.unsolved if i]

    @classmethod
    @abstractmethod
    def _api_parse_request(cls, d):
        pass

    @classmethod
    @abstractmethod
    def _api_parse_answer(cls, request):
        pass

    @classmethod
    @abstractmethod
    def _api_register_request(cls, request):
        pass

    @classmethod
    @abstractmethod
    def _api_fetch_answer(cls, request):
        pass


class AntiCaptcha(BaseService):
    """Uses Anticaptcha captcha service to solve recaptchas

       | URL: https://anti-captcha.com
       | Documentation: https://anti-captcha.com/apidoc"""

    name = 'anticaptcha'
    api_url = 'http://api.anti-captcha.com/'
    cost = 0.002

    @classmethod
    def _api_parse_request(cls, request):
        """This factory function handles the response from the captcha service regarding task creation. It returns a
           response hook which uses the API provided by the service.

           :param dict request: Contains an instance of AutoManager class and the time when the request was
                                added to the request_queue. Example: {'instance':..., 'timeToQ': ...}

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

        def response_hook(r, *args, **kwargs):

            # This is an instance of AutoManager.
            inst: recaptcha_manager.manager.AutoManager = request['instance']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            r_data = r.json()
            error_code = r_data.get('errorCode', None)

            # Now we check the status of the captcha request based on what the server responded with
            if r_data['errorId'] == 0 or r_data['errorId'] == '0':

                # Request successful, server registered the task and we append it to unsolved list after
                # in/decrementing counters since we are removing the request from queue and adding it to unsolved list
                with inst.instance_lock:
                    inst.ReqsInUnsolvedList += 1
                    inst.ReqsInQueue -= 1
                cls.unsolved.append({'task_id': r_data['taskId'], 'startTime': time.time(), 'instance': inst,
                                     'timeToQ': request['timeToQ']})

                # We set the attribute to mark the request as completed and can be safely removed
                r.remove_request = True

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
                raise BadSitekeyError('Provided sitekey is incorrect')

            elif error_code == 'ERROR_RECAPTCHA_INVALID_DOMAIN':
                raise BadDomainError('Provided domain is incorrect')

            else:
                raise RuntimeError('Unidentified errorCode provided by server: {}'.format(r_data))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return r

        return response_hook

    @classmethod
    def _api_parse_answer(cls, request):
        """This factory function handles the response from the captcha service when requesting status of a task.
           It returns a response hook which uses the API provided by the service.

           :param dict request: Contains an instance of AutoManager class, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'instance':..., 'timeToQ': ..., 'task_id': ..., 'startTime': ...}
           :return: Response hook to be used with requests-futures
           :rtype: method
           :raises:
                RuntimeError: When the server responds with an unidentified error code
        """

        def response_hook(r, *r_args, **r_kwargs):

            # This is an instance of a subclass of BaseService.
            instance: recaptcha_manager.manager.AutoManager = request['instance']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            r_data = r.json()
            error_code = r_data.get('errorCode', None)

            # Now we check the status of the captcha request based on what the server responded with
            if error_code == 'ERROR_RECAPTCHA_TIMEOUT':

                # For some reason, our captcha wasn't solved. So we mark the request as completed but add it back to
                # the request_queue so it can be registered again after we edit the relevant counters
                cls.request_queue.put({'instance': instance, 'timeToQ': time.time()})
                with instance.instance_lock:
                    instance.ReqsInUnsolvedList -= 1
                    instance.ReqsInQueue += 1

                r.remove_request = True

            elif r_data['status'] == 'processing':
                # Still not solved
                pass

            elif r_data['status'] == 'ready':
                # We successfully got the g-recaptcha response. We add this to the response_queue along with the time
                # it was solved, the time it was added to response_queue, id of the task and the cost for the captcha
                instance.response_queue.put({'id': request['task_id'], 'answer': r_data['solution']['gRecaptchaResponse'],
                                             'timeSolved': int(r_data.get('endTime', time.time() - 5)),
                                             'cost': float(r_data.get('cost', cls.cost)), 'timeReceived': time.time()})

                # We call requestsSolved to edit relevant counters.
                instance.request_solved(request['timeToQ'])

                # Mark the request as completed and safe to remove from cls.unsolved list
                r.remove_request = True

            else:
                raise RuntimeError('Unidentified errorCode provided by server: {}'.format(r_data))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return r

        return response_hook

    @classmethod
    def _api_register_request(cls, request):
        """Uses the captcha service API to create and send a request for task creation to server. The request is sent
           asynchronously and is attached with a response hook from cls._api_parse_request() function

           :param dict request: Contains an instance of AutoManager class and the time when the request was
                                added to the request_queue. Example: {'instance':..., 'timeToQ': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # This is an instance of a subclass of BaseRequest.
        inst: recaptcha_manager.AutoManager = request['instance']

        # Based on captcha_type, we create a request with relevant post-data
        if inst.captcha_type == 'v2':
            data = {'clientKey': cls.key,
                    'task': {"type": "NoCaptchaTaskProxyless", "websiteURL": inst.url, 'websiteKey': inst.web_key,
                             'isInvisible': inst.invisible}}
        elif inst.captcha_type == 'v3':
            data = {'clientKey': cls.key, 'task': {'type': 'RecaptchaV3TaskProxyless', 'websiteURL': inst.url,
                                                   'websiteKey': inst.web_key, 'minScore': inst.min_score,
                                                   'pageAction': inst.action}}

        # We now send the request asynchronously and add a response hook to parse the server response in the background
        r = cls.session.post(cls.api_url + 'createTask', json=data, verify=False, timeout=7,
                             hooks={'response': cls._api_parse_request(request)})

        # We return this future
        return r

    @classmethod
    def _api_fetch_answer(cls, request):
        """Uses the captcha service API to for creating and sending a request to fetch task status from server. The
           request is sent asynchronously and is attached with a response hook from cls._api_parse_answer() function

           :param dict request: Contains an instance of AutoManager class, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'instance':..., 'timeToQ': ..., 'task_id': ..., 'startTime': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # Create relevant fields to add to request
        data = {'clientKey': cls.key, 'taskId': request['task_id']}

        # Send request asynchronously
        r = cls.session.post(cls.api_url + 'getTaskResult', json=data, verify=False, timeout=7,
                             hooks={'response': cls._api_parse_answer(request)})
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
    def _api_parse_request(cls, request):
        """This factory function handles the response from the captcha service regarding task creation. It returns a
           response hook which uses the API provided by the service.

           :param dict request: Contains an instance of AutoManager class and the time when the request was
                                added to the request_queue. Example: {'instance':..., 'timeToQ': ...}

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

        def response_hook(r, *args, **kwargs):

            # This is an instance of AutoManager.
            inst: recaptcha_manager.manager.AutoManager = request['instance']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            r_data = r.json()
            error_code = r_data['request']

            # Now we check the status of the captcha request based on what the server responded with
            if r_data['status'] == 1:

                # Request successful, server registered the task and we append it to unsolved list after
                # in/decrementing counters since we are removing the request from queue and adding it to unsolved list
                with inst.instance_lock:
                    inst.ReqsInUnsolvedList += 1
                    inst.ReqsInQueue -= 1
                cls.unsolved.append({'task_id': r_data['request'], 'startTime': time.time(), 'instance': inst,
                                     'timeToQ': request['timeToQ']})

                # We set the attribute to mark the request as completed and can be safely removed
                r.remove_request = True

            elif error_code == 'ERROR_NO_SLOT_AVAILABLE':

                # This happens when the there are too many captchas already being solved.
                pass

            elif error_code == 'ERROR_ZERO_BALANCE':
                raise NoBalanceError('Balance insufficient')

            elif error_code in ['ERROR_KEY_DOES_NOT_EXIST', 'ERROR_WRONG_USER_KEY']:
                raise BadAPIKeyError('API Key provided is incorrect')

            elif error_code == 'ERROR_GOOGLEKEY':
                raise BadSitekeyError('Provided sitekey is incorrect')

            elif error_code == 'ERROR_BAD_TOKEN_OR_PAGEURL':
                raise BadDomainError('Provided page url and sitekey combination is incorrect')

            else:
                raise RuntimeError('Unidentified errorCode provided by server: {}'.format(r_data))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return r

        return response_hook

    @classmethod
    def _api_parse_answer(cls, request):
        """This factory function handles the response from the captcha service when requesting status of a task.
           It returns a response hook which uses the API provided by the service.

           :param dict request: Contains an instance of AutoManager class, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'instance':..., 'timeToQ': ..., 'task_id': ..., 'startTime': ...}
           :return: Response hook to be used with requests-futures
           :rtype: method
           :raises:
                RuntimeError: When the server responds with an unidentified error code
        """

        def response_hook(r, *r_args, **r_kwargs):

            # This is an instance of a subclass of BaseService.
            instance: recaptcha_manager.manager.AutoManager = request['instance']

            # This converts the response from the service's server to json. If request is successful, errorCode
            # doesn't exist and we give the default value of None
            r_data = r.json()
            error_code = r_data['request']

            # Now we check the status of the captcha request based on what the server responded with
            if r_data['status'] == 1:
                # We successfully got the g-recaptcha response. We add this to the response_queue along with the time
                # it was solved, the time it was added to response_queue, id of the task and the cost for the captcha
                instance.response_queue.put(
                    {'id': request['task_id'], 'answer': r_data['request'],
                     'timeSolved': time.time() - 3, 'cost': cls.cost,
                     'timeRecieved': time.time()})

                # We call requestsSolved to edit relevant counters.
                instance.request_solved(request['timeToQ'])

                # Mark the request as completed and safe to remove from cls.unsolved list
                r.remove_request = True

            elif error_code == 'ERROR_CAPTCHA_UNSOLVABLE':

                # For some reason, our captcha wasn't solved. So we mark the request as completed but add it back to
                # the request_queue so it can be registered again after we edit the relevant counters
                cls.request_queue.put({'instance': instance, 'timeToQ': time.time()})
                with instance.instance_lock:
                    instance.ReqsInUnsolvedList -= 1
                    instance.ReqsInQueue += 1

                r.remove_request = True

            elif error_code == 'CAPCHA_NOT_READY':
                # Still not solved
                pass

            else:
                raise RuntimeError('Unidentified status provided by server: {}'.format(r_data))

            # We have to return this new response because we are adding an attribute (remove_request) if the request
            # was successfully registered
            return r

        return response_hook

    @classmethod
    def _api_register_request(cls, request):
        """Uses the captcha service API to create and send a request for task creation to server. The request is sent
           asynchronously and is attached with a response hook from cls._api_parse_request() function

           :param dict request: Contains an instance of AutoManager class and the time when the request was
                                added to the request_queue. Example: {'instance':..., 'timeToQ': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # This is an instance of a subclass of BaseRequest.
        inst: recaptcha_manager.AutoManager = request['instance']

        if inst.invisible:
            invisible = 1
        else:
            invisible = 0

        # Based on captcha_type, we create a request with relevant post-data
        if inst.captcha_type == 'v2':
            data = cls.api_url + "in.php?key={}&method=userrecaptcha&googlekey={}&pageurl={}&invisible={}&" \
                   "json=1".format(cls.key, inst.web_key, inst.url, invisible)
        elif inst.captcha_type == 'v3':
            data = cls.api_url + "in.php?key={}&method=userrecaptcha&version=v3&action={}&min_score={}&" \
                   "googlekey={}&pageurl={}&json=1".format(cls.key, inst.action, inst.min_score, inst.web_key,
                                                           inst.url)

        # We now send the request asynchronously and add a response hook to parse the server response in the background
        r = cls.session.post(data, verify=False, timeout=7, hooks={'response': cls._api_parse_request(request)})

        # We return this future
        return r

    @classmethod
    def _api_fetch_answer(cls, request):
        """Uses the captcha service API to for creating and sending a request to fetch task status from server. The
           request is sent asynchronously and is attached with a response hook from cls._api_parse_answer() function

           :param dict request: Contains an instance of AutoManager class, time when the request was
                                added to the request_queue, time when the server started solving the request, and the
                                task id. Example: {'instance':..., 'timeToQ': ..., 'task_id': ..., 'startTime': ...}
           :returns: A Future request whose response can be received through request.result()
           :rtype: Future"""

        # Create relevant fields to add to request
        data = cls.api_url + "res.php?key={}&action=get&id={}&json=1".format(cls.key, request['task_id'])

        # Send request asynchronously
        r = cls.session.post(data, verify=False, timeout=7, hooks={'response': cls._api_parse_answer(request)})
        return r


class CapMonster(AntiCaptcha):
    """
    Uses Capmonster service to solve captcha. The service offers many similar APIs to other popular services

    URL: https://capmonster.cloud
    """

    name = 'capmonster'
    api_url = 'https://api.capmonster.cloud/'
    cost = 0.0006
