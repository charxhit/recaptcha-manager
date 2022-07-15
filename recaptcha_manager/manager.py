import traceback
from abc import ABC, abstractmethod
import types
import time
import queue
from multiprocess import Manager, Lock
from multiprocess.managers import BaseManager, BaseProxy, NamespaceProxy
import hashlib
import recaptcha_manager
from recaptcha_manager.exceptions import InvalidBatchID, RestoreError, BadDomainError
import copy
import re

# manager = None

def ensure_lock(func):
    def wrapper(*args, **kwargs):
        try:
            if args[0].instance_lock.acquire(blocking=False) is True:
                args[0].instance_lock.release()
                raise RuntimeError("Protected function was called without ensuring lock was acquired. This is likely a bug")

            return func(*args, **kwargs)
        # See https://stackoverflow.com/questions/29277150/python-3-4-multiprocessing-bug-on-lock-acquire-typeerror-integer-required
        except TypeError:
            if args[0].instance_lock.acquire(blocking=False) is True:
                args[0].instance_lock.release()
                raise RuntimeError(
                    "Protected function was called without ensuring lock was acquired. This is likely a bug")

            return func(*args, **kwargs)

    return wrapper


class CaptchaJob:
    """Stores the details of each captcha task sent to the solving services"""

    def __init__(self, url, web_key, captcha_type, action, min_score, invisible, batch_id=None):
        self.url = url
        self.web_key = web_key
        self.captcha_type = captcha_type
        self.action = action
        self.min_score = min_score
        self.invisible = invisible
        self.batch_id = batch_id


class ObjProxy(NamespaceProxy):
    """Returns a proxy instance for any user defined data-type. The proxy instance will have the namespace and
    functions of the data-type (except private/protected callables/attributes)"""

    def __getattr__(self, name):
        result = super().__getattr__(name)
        if isinstance(result, types.MethodType):
            def wrapper(*args, **kwargs):
                return self._callmethod(name, args, kwargs)
            return wrapper
        return result


class BaseRequest(ABC):
    """Base class for managers"""
    scheme_check = r'https?:\/\/'

    def __init__(self, request_queue, maximum=0, initial=1, limit=0):

        assert isinstance(request_queue, BaseProxy), "Queues Passed to constructor should be proxy objects"
        assert initial > 0, " initial parameter cannot be 0 or less than 0"
        m = Manager()
        self.maximum = maximum
        self.initial = initial
        self.limit = limit
        self.response_queue = m.Queue()
        self.request_queue = request_queue
        self.instance_lock = m.Lock()
        self.ReqsUsed = 0
        self.ReqsSolved = 0
        self.ReqsInUnsolvedList = 0
        self.ReqsInQueue = 0
        self.expired = 0
        self.proxy = None
        self.stop_new_requests = False
        self.finished = False

    @classmethod
    def create(cls, *args, **kwargs):
        """
        Properly initializes a class instance.

        :return: A proxy instance of class. Has same functionality as a regular instance and can share state between
                 processes.
        :rtype: ObjProxy
        """

        # if manager is None:
        #     prepare_module()

        # Register class
        class_str = cls.__name__

        BaseManager.register(class_str, cls, ObjProxy, exposed=tuple(dir(cls)))

        # Start a manager process
        manager = BaseManager()
        manager.start()

        # Create and store instance. We must store this proxy instance since its passed in request_queue to another
        # process whenever a captcha request is required. This allows sharing of state between processes.
        inst = eval("manager.{}(*args, **kwargs)".format(class_str))
        inst.set_proxy(inst)

        return inst

    def set_proxy(self, proxy):
        """
        Set proxy for current instance which shares its state with other processes. We use this proxy to interact
        with other processes

        :meta private:
        """

        self.proxy = proxy

    def create_request(self, job):
        """
        Create correctly formatted request to be put into request_queue

        :param CaptchaJob job: The CaptchaJob object containing the details of the captcha task needed to be created
        :return: Request ready to be put into request_queue
        :rtype: dict
        :meta private:
        """
        return {'manager': self.proxy, 'job': job}

    def request_cancelled(self, job, unsolved):
        """
        Called when an already registered captcha task is forfeited. This usually happens when a service process quits
        due to a service-specific error, or when a request is received when the manager has already stopped.

        :param CaptchaJob job: Only present here to maintain consistency between subclasses
        :meta private:
        """
        with self.instance_lock:
            if unsolved is True:
                self.ReqsInUnsolvedList -= 1
            elif unsolved is False:
                self.ReqsInQueue -= 1

    def request_failed(self, job):
        """
        Called when a captcha request was unable to be solved.

        :param CaptchaJob job: The CaptchaJob object containing the details of the captcha task which failed
        :meta private:
        """

        # Put another captcha request with the same details and in/decrement relevant counters
        self.request_queue.put(self.create_request(job=job))
        with self.instance_lock:
            self.ReqsInUnsolvedList -= 1
            self.ReqsInQueue += 1

    def request_created(self):
        """
        Called when a captcha request has been successfully registered by the solving service.

        :meta private:
        """
        with self.instance_lock:
            self.ReqsInUnsolvedList += 1
            self.ReqsInQueue -= 1

    def being_solved(self):
        """
        Get how many captchas are being currently solved

       :rtype: int
       """
        return self.ReqsInQueue + self.ReqsInUnsolvedList

    def available(self):
        """
        Get how many captchas are available to be used

       :rtype: int
       """
        return self.response_queue.qsize()

    def request_solved(self, time_for_solve=None, error=False):
        """
        Called when a captcha request was successfully solved

        :param time_for_solve: The time when the captcha request was registered with the solving service. Present here for
                             consistency between subclasses.
        :param error: Whether the solving service returned an error for this particular captcha task

        :meta private:
        """

        with self.instance_lock:
            self.ReqsInUnsolvedList -= 1

            if error is False:
                self.ReqsSolved += 1

    def stop(self):
        """
        Stops production of new captcha requests. Requests already being solved won't be affected and captcha tokens
        for those requests will be produced normally. Should be called when you no longer intend to send new
        requests. Any new captcha requests sent after this method call will be rejected.
        """

        with self.instance_lock:
            if self.finished is True:
                raise RuntimeError("Manager is no longer usable or has already been force stopped")
            self.stop_new_requests = True

    def force_stop(self):
        """
        Stops production of new captcha requests and immediately stops the manager. Requests already solved,
        or currently being solved, will be discarded. Any new captcha requests sent after this method call will be
        rejected.
        """
        with self.instance_lock:
            self.stop_new_requests = True
            self.finished = True

    def flush(self):
        """
        Remove all stored solved captchas (if any). Good for cleaning up after you are done with the manager
        """

        with self.instance_lock:
            while True:
                try:
                    self.response_queue.get(block=False)
                except queue.Empty:
                    break

    @abstractmethod
    def get_request(self, send_custom_reqs=True, max_block=0):
        pass

    @abstractmethod
    def send_request(self, maximum=None, initial=None):
        pass

    def get_solved(self):
        """
        Returns how many total captchas have been solved by the manager

        :rtype: int
        """
        return self.ReqsSolved

    def get_used(self):
        """
        Returns how many total captchas have been used by your program

        :rtype: int
        """
        return self.ReqsUsed

    def get_expired(self):
        """
        Returns How many total captchas, which were solved, expired before being used

        :rtype: int
        """
        return self.expired


class ManualManager(BaseRequest):

    def __init__(self, request_queue):
        super().__init__(request_queue)
        self.current_jobs = {}
        self.job_results = {}

    @classmethod
    def create(cls, request_queue):
        """
        Properly initializes instance.

        :return: A proxy instance of class. Has same functionality as a regular instance and can share state between
                  processes.
        :rtype: ManualManager
        """

        return super().create(request_queue)

    @staticmethod
    def _extract_domain(url):
        return '/'.join(url.split('/')[0:3])

    def send_request(self, url, web_key, captcha_type, number=1, action=None, min_score=None, invisible=False,
                     force_path=False):
        """
        Creates an id for the captcha requests and sends them to the service process. These requests will be solved by
        the captcha solving service in the background without interrupting your main program. Captcha requests with
        similar parameters will share the same id. Returns immediately.

        :param str url: Full URL of the website where captcha is present.
        :param str web_key: Google sitekey of the captcha
        :param str captcha_type: Version of recaptcha. Can be 'v2' or 'v3' only.
        :param int number: Number of captcha requests to send for the specified parameters
        :param str action: The action string in case of solving recaptcha v3
        :param float min_score: The minimum recaptcha v3 score desired in case solving recaptcha v3. Should be between
                                0-1.
        :param bool force_path: Whether to take the entire URL (domain + path) in consideration when creating batch_id.
                                If set to False, only uses domain.
        :param bool invisible: Whether the captcha is invisible recaptcha v2 or not.
        :return: Returns the id of the created captcha requests.
        :rtype: str

        The returned id can then be used when calling the :meth:`~ManualManager.get_request` method to retrieve the
        answer for the captcha tasks created here, or for any other captcha tasks created with similar parameters in
        general.
        """

        # If no new requests are being accepted, then return.
        if self.stop_new_requests:
            return

        if re.match(self.scheme_check, url) is None:
            raise BadDomainError(f"Provided url is missing scheme. Did you mean {'http://' + url}?")

        assert number >= 1, 'Argument "number" cannot be less than 1'
        assert captcha_type in ['v2', 'v3'], "Captcha type {} not recognized. Only 'v2' and 'v3' google recaptchas " \
                                             "are supported".format(captcha_type)

        if captcha_type == 'v3':
            assert action, "Action parameter cannot be left blank if captcha type is 'v3'"
            assert min_score, "min_score cannot be left blank if captcha type is 'v3'"
            assert isinstance(min_score, (int, float)) and 0 < min_score < 1, "Invalid min_score value provided"

        if force_path is False:
            url = self._extract_domain(url)

        # Create a hash of the parameters to get a batch_id unique to that set of parameters
        if captcha_type == 'v3':
            parameters = self._stringify(url, web_key, captcha_type, action, min_score)
        elif captcha_type == 'v2':
            parameters = self._stringify(url, web_key, captcha_type)

        batch_id = hashlib.sha1(parameters.encode()).hexdigest()

        # Create a job object which would be used by service process to create the captcha task
        job = CaptchaJob(url, web_key, captcha_type, action, min_score, invisible, batch_id=batch_id)

        # Increment counter since we are going to be adding requests in request_queue
        with self.instance_lock:
            self.ReqsInQueue += number

            if self.current_jobs.get(batch_id):
                self.current_jobs[batch_id] += number
            else:
                self.current_jobs[batch_id] = number

        # Finally, add the calculated number of requests in queue
        for _ in range(number):
            self.request_queue.put(self.create_request(job))

        return batch_id

    @ensure_lock
    def _check_answer(self, batch_id):
        """
        Checks if there are any stored captcha answers for the batch_id provided. If so, returns

        :meta private:
        """

        if len(self.job_results.get(batch_id, [])) > 0:
            answer = self.job_results[batch_id][0]
            del self.job_results[batch_id][0]

            self.current_jobs[batch_id] -= 1
            self.ReqsUsed += 1
            return answer

        return False

    def request_cancelled(self, job: CaptchaJob, unsolved):
        """
        Called when a captcha task, registered or unregistered, is forfeited. This usually happens due to a problem on the
        captcha solving service's end.

        :param CaptchaJob job: The details of the captcha task which was cancelled.
        :meta private:
        """

        with self.instance_lock:
            assert self.current_jobs.get(job.batch_id, 0) != 0, "Unexpected data modification. No requests were being " \
                                                                "solved for the batch id. "

            self.current_jobs[job.batch_id] -= 1

            if unsolved is True:
                self.ReqsInUnsolvedList -= 1
            elif unsolved is False:
                self.ReqsInQueue -= 1

    def _update_results(self):
        """
        Adds all results available from queue

        :meta private:
        """

        while True:
            try:
                c = self.response_queue.get(block=False)

            except queue.Empty:
                break

            else:
                with self.instance_lock:
                    self._add_result(c)

    @ensure_lock
    def _add_result(self, answer):
        """
        Adds all captcha answers passed to their respective batch_ids

        :param answer: The details of the captcha job that was completed
        """

        if self.job_results.get(answer['batch_id'], None) is None:
            self.job_results[answer['batch_id']] = []

        self.job_results[answer['batch_id']].append(answer)

    def get_request(self, batch_id, max_block=0, force_return=True):
        """
        Returns a solved captcha for the provided id. Blocks until one is ready or another condition reached.

        :param str batch_id: The id of the type of captcha tasks you wish to retrieve
        :param int max_block: Maximum time the function blocks in seconds. Set as 0 to block until a request is received
        :param bool force_return: Whether to return None as soon as the number of captcha tasks being solved for the
                                  provided batch_id becomes zero. Takes precedence over max_block.
        :return: A dictionary containing the token under key 'answer'
        :rtype: dict


        Example ::

            try:
                c = manager.get_request(batch_id)  # Blocks until one is ready
            except recaptcha_manager.exceptions.Exhausted:
                print('no more requests available')
            else:
                token = c['answer']

        .. note::
            Make sure to either pass parameter `force_return` as True, or `max_block` as a non-zero value (or
            both) to avoid a possibility for an indefinite block time

        """

        try:
            assert max_block >= 0, f"{max_block} is not a valid value for parameter max_block"

            # Check validity of the batch_id
            with self.instance_lock:
                if self.current_jobs.get(batch_id, None) is None:
                    raise InvalidBatchID("Bad id provided, no such tasks have been registered")

            # Take note of time of entry in case max_block was provided to a non-zero value
            enter_time = time.time()

            while True:

                # Check if we are over the time limit
                if max_block != 0 and time.time() - enter_time > max_block:
                    raise recaptcha_manager.exceptions.TimeOutError

                with self.instance_lock:

                    # Check if manager will no longer receive solved captcha requests for the provided batch_id
                    if self.current_jobs[batch_id] == 0 and self.stop_new_requests:
                        self.finished = True

                    if self.finished:
                        raise recaptcha_manager.exceptions.Exhausted("All tasks for this batch id have been exhausted")

                    if self.current_jobs[batch_id] == 0 and force_return:
                        raise recaptcha_manager.exceptions.EmptyError("No requests are being currently solved for this id")

                self._update_results()

                # Check if, during the time we waited for response from queue, another process received and stored a
                # captcha answer for this batch_id
                with self.instance_lock:
                    ans = self._check_answer(batch_id)

                    if ans:
                        # Check if there was an error in solving the captcha, and raise it.
                        if ans.get('error') is not None:
                            raise ans['error']

                        return ans

        except Exception as e:
            msg = "{}\n\nOriginal {}".format(e, traceback.format_exc())
            raise type(e)(msg)

    @staticmethod
    def _stringify(*args):
        """
        Converts given arguments into a hash
        :rtype: str
        """

        s = ''
        for arg in args:
            s += str(arg) + '-'
        return s

    def available(self, batch_id=None):
        """
        Returns the number of captcha requests solved and available for use. If batch_id is provided, returns information
        for that particular batch_id only.

        :param str batch_id: Optional parameter to restrict the lookup to a particular batch_id
        """

        answer = 0
        self._update_results()

        with self.instance_lock:
            if batch_id is None:
                for key, value in self.job_results.items():
                    answer += len(value)

                answer += super().available()
                return answer

            if self.current_jobs.get(batch_id, None) is None:
                raise InvalidBatchID("Incorrect id provided, no such tasks have been registered")

            return len(self.job_results.get(batch_id, []))

    def being_solved(self, batch_id=None):
        """
        Returns the number of captcha requests being solved. If batch_id is provided, returns information
        for that particular batch_id only.

        :param str batch_id: Optional parameter to restrict the lookup to a particular batch_id
        """

        self._update_results()

        with self.instance_lock:
            if batch_id is None:
                return super().being_solved()

            if self.current_jobs.get(batch_id, None) is None:
                raise InvalidBatchID("Incorrect id provided, no such tasks have been registered")

            return self.current_jobs[batch_id]


class AutoManager(BaseRequest):
    """
    Manages creation and sending of captcha requests to service process. Predicts the optimal number of captchas to
    send based on usage statistics.

    .. note::
        Do not call the constructor directly, managers should be created through :meth:`~AutoManager.create()` function

    Example instantiation::

       url = 'https://some.domain.com'
       sitekey = 'xxxxxxx'
       captcha_type = 'v2'  # or 'v3'

       if __name__ == '__main__':
           request_queue = recaptcha_manager.generate_queue()
           manager = AutoManager.create(request_queue, url, sitekey, captcha_type)

    """
    MAX_RECORDS = 10
    IDEAL_RECORDS = 5

    def __init__(self, request_queue, url, web_key, captcha_type, action=None, min_score=None, invisible=False,
                 initial=1, maximum=0, limit=0):
        assert captcha_type in ['v2', 'v3'], "Captcha type {} not recognized. Only 'v2' and 'v3' google recaptchas " \
                                                 "are supported".format(captcha_type)
        if captcha_type == 'v3':
            assert action, "Action parameter cannot be left blank if captcha type is 'v3'"
            assert min_score, "min_score cannot be left blank if captcha type is 'v3'"
            assert 0 < min_score < 1, "Invalid min_score value provided"

        if re.match(self.scheme_check, url) is None:
            raise BadDomainError(f"Provided url is missing scheme. Did you mean {'http://' + url}?")

        super().__init__(request_queue, maximum=maximum, initial=initial, limit=limit)
        self.WaitingTime = {'num': 0, 'total_time': 0, 'rate': 0.0}
        self.UseRate = {'num': 0, 'total_time': 0, 'last_time': time.time(), 'rate': 0.0}
        self.SolveTime = {'num': 0, 'total_time': 0, 'rate': 0.0}
        self.restoreTime = None
        self.invisible = invisible
        self.web_key = web_key
        self.url = url
        self.captcha_type = captcha_type
        self.action = action
        self.min_score = min_score
        self.job = CaptchaJob(url, web_key, captcha_type, action, min_score, invisible)


    @classmethod
    def create(cls, request_queue, url, web_key, captcha_type, action=None, min_score=None, invisible=False,
               initial=1, maximum=0, limit=0):
        """
        Properly initializes the constructor for AutoManager.

        :param multiprocessing.Queue request_queue: A queue for communication between service process and managers.
                                                    Can be generated by :func:`recaptcha_manager.generate_queue()`
        :param str url: URL of target website
        :param str web_key: sitekey of target website
        :param str captcha_type: Version of recaptcha the target site uses. Can be 'v2' or 'v3'
        :param str action: Action parameter in case solving recaptcha v3
        :param float min_score: minimum score you want if solving recaptcha v3. Should be between 0 and 1
        :param bool invisible: Whether the target site uses invisible recaptcha v2
        :param int initial: Number of captcha requests to send when calling :meth:`~AutoManager.send_request` initially
                            when there isn't enough data. Defaults to 1
        :param int maximum: Maximum number of captcha requests to send on one call of :meth:`~AutoManager.send_request`
                            function. Set as 0 to specify no such limit.
        :param int limit: Maximum number of allowed captcha requests being solved at once. Set as 0 to disable this
                          limit

        :returns: A proxy instance of class AutoManager. Has same functionality as a regular manager
        :rtype: AutoManager

        The number of captchas requests to send are predicted on the basis of usage details only if sufficient number
        (3) of captchas have been solved and used. Until then, ``initial`` (default value 1) number of captchas will
        be sent on every call of :meth:`~AutoManager.send_request()` function.
        """

        return super().create(request_queue, url, web_key, captcha_type, action=action, min_score=min_score,
                              invisible=invisible, initial=initial, maximum=maximum, limit=limit)

    def create_restore_point(self, overwrite=False):
        """
        Create a copy of current statistics which can be used to restore the manager's state at a later point

        :param overwrite: Whether to overwrite any existing restore points
        """

        with self.instance_lock:
            if not overwrite and self.restoreTime is not None:
                raise RestoreError("Restore point already exists. Use param overwrite=True to overwrite previous "
                                   "restore points")

            self.restoreTime = copy.deepcopy(self.UseRate)

    def restore(self):
        """
        Revert the manager's statistics back using a created restore point
        """

        with self.instance_lock:
            if self.restoreTime is None:
                raise RestoreError("No restore point found, use create_restore_point() to create one")

            self.UseRate = copy.deepcopy(self.restoreTime)
            self.restoreTime = None

    def request_solved(self, time_for_solve=None, error=False):
        """
        Called when a captcha request was successfully solved

        :param time_for_solve: The time when the captcha request was sent to request_queue
        :param error: Whether the solving service returned an error for this particular captcha task
        :meta private:
        """

        with self.instance_lock:
            self.ReqsInUnsolvedList -= 1

            if error is False:
                # Add amount of time taken for captcha to move from request_queue to response_queue and increment solved
                # captchas counter
                self.SolveTime['num'] += 1

                if time_for_solve < 0:
                    time_for_solve = 0

                self.SolveTime['total_time'] += time_for_solve
                self.ReqsSolved += 1

    def get_waiting_time(self):
        """
        Returns recent average waiting time to receive a captcha token from server process. Will be zero if not enough
        statistics collected.

        :rtype: float
        """

        with self.instance_lock:
            self._update_stats()
            return self.WaitingTime['rate']

    def get_solving_time(self):
        """
        Returns recent average time taken by the solving service to solve a captcha. Will be zero if not enough
        statistics collected.

        :rtype: float
        """

        with self.instance_lock:
            self._update_stats()
        return self.SolveTime['rate']

    def get_use_rate(self):
        """
        Returns how frequently your program requires recaptcha tokens (in seconds). Will be zero if not enough
        statistics collected.

        :rtype: float
        """

        with self.instance_lock:
            self._update_stats()
        return self.UseRate['rate']

    def get_request(self, send_custom_reqs=True, max_block=0):
        """
        Returns a solved captcha. Blocks until one is ready

        :param bool send_custom_reqs: By default function will send additional captcha requests if there are none
                                      being solved. Set as False to prevent this
        :param int max_block: Maximum time the function blocks in seconds. Set as 0 to block until a request is recieved
        :return: A dictionary containing the token under key 'answer'
        :rtype: dict


        Example ::

            try:
                c = manager.get_request()  # Blocks until one is ready
            except recaptcha_manager.exceptions.Exhausted:
                print('no more requests available')
            else:
                token = c['answer']

        .. note::
            If ``send_custom_reqs`` is ``False``, then code may block indefinitely if there aren't any captcha requests
            being solved. In case it is set to ``False``, set ``max_block`` to a non-zero value

        """

        assert max_block >= 0, f"{max_block} is not a valid value for parameter max_block"

        with self.instance_lock:

            # Check if no new captcha requests are going to be solved. If so, return None
            if self.stop_new_requests and self.ReqsInUnsolvedList + self.response_queue.qsize() == 0:
                self.finished = True
            if self.finished:
                raise recaptcha_manager.exceptions.Exhausted

            # Record the time elapsed since last time get_request() was called to know how frequently does program
            # require captchas
            self.UseRate['num'] += 1
            self.UseRate['total_time'] += (time.time() - self.UseRate['last_time'])
            self.UseRate['last_time'] = time.time()

        enter_time = time.time()

        while True:

            if max_block and time.time() - enter_time >= max_block:

                # Update stats
                with self.instance_lock:

                    # We refresh the last call since we don't want to record the time spent within the function but
                    # the time between consecutive calls to get_request().
                    self.UseRate['last_time'] = time.time()

                raise recaptcha_manager.exceptions.TimeOutError

            try:
                c = self.response_queue.get(timeout=2)
            except queue.Empty:

                # If there were no captcha tokens available within 5 seconds, we check if stop_new_requests is False
                # and whether there are captcha requests being solved. If not, we raise queue.Empty error
                if self.stop_new_requests and self.response_queue.qsize() + self.ReqsInUnsolvedList == 0:
                    self.finished = True
                    raise recaptcha_manager.exceptions.Exhausted

                # Otherwise, if stop_new_requests is False, then we manually send one request
                if not self.stop_new_requests and send_custom_reqs and self.ReqsInQueue + self.response_queue.qsize() + \
                        self.ReqsInUnsolvedList == 0:

                    # Increment counter since we are adding a request in request queue
                    with self.instance_lock:
                        self.ReqsInQueue += 1

                    # Add a request in request_queue
                    self.request_queue.put(self.create_request(job=self.job))

            else:  # We got a captcha

                if c.get('error') is not None:
                    with self.instance_lock:
                        self.UseRate['last_time'] = time.time()

                    raise c['error']

                with self.instance_lock:
                    self.ReqsUsed += 1

                # Captcha is assumed to have NOT expired
                if time.time() - c['timeSolved'] < 120:

                    # Update stats
                    with self.instance_lock:

                        # Record the amount of time waited to receive captcha
                        time_waited = time.time() - enter_time
                        self.WaitingTime['num'] += 1
                        self.WaitingTime['total_time'] += time_waited

                        # We refresh the last call since we don't want to record the time spent within the function but
                        # the time between consecutive calls to get_request().
                        self.UseRate['last_time'] = time.time()

                    return c
                else:
                    # Captcha expired
                    self.expired += 1

    @ensure_lock
    def _update_stats(self):
        """
        Update the usage statistics when we need to use them
        """

        # First we update WaitingTime['rate']. If the number of times get_request() waited for captcha is 0, then set
        # the rate as 0 as well
        if self.WaitingTime['num'] == 0:
            self.WaitingTime['rate'] = 0.0
        else:
            self.WaitingTime['rate'] = self.WaitingTime['total_time'] / self.WaitingTime['num']

            # Keep only the most recent stats
            if self.WaitingTime['num'] > self.MAX_RECORDS:
                _num_old = self.WaitingTime['num'] - self.IDEAL_RECORDS
                self.WaitingTime['total_time'] -= _num_old * self.WaitingTime['rate']
                self.WaitingTime['num'] = self.IDEAL_RECORDS

        # Next we update UseRate['rate']. If the number of captchas used is 0, then set the rate as 0 as well
        if self.UseRate['num'] == 0:
            self.UseRate['rate'] = 0.0
        else:
            # We check if total_time has been more than 150 seconds. This is to ensure we only have the most recent info
            # from last 120 seconds. We do this check at 150 seconds so that after old stats of previous 120s are
            # removed, we still have enough info to make accurate predictions
            if self.UseRate['total_time'] >= 150:

                # We then check based on current stats, how many solves will be done in 120s
                recent_num_solved = round(self.UseRate['num'] / self.UseRate['total_time'] * 120)

                # Since we want enough info after we remove the old stats, we check if there will be info about atleast
                # 5 solves
                if self.UseRate['num'] - recent_num_solved >= 5:
                    self.UseRate['num'] -= recent_num_solved
                    self.UseRate['total_time'] -= 120

            self.UseRate['rate'] = self.UseRate['total_time'] / self.UseRate['num']

        # We then update SolveTime['rate']. If the number of captchas solved is 0, then set the rate as 0 as well
        if self.SolveTime['num'] == 0:
            self.SolveTime['rate'] = 0.0
        else:
            self.SolveTime['rate'] = self.SolveTime['total_time'] / self.SolveTime['num']

            # Keep only the most recent stats
            if self.SolveTime['num'] > self.MAX_RECORDS:
                _num_old = self.SolveTime['num'] - self.IDEAL_RECORDS
                self.SolveTime['total_time'] -= _num_old * self.SolveTime['rate']
                self.SolveTime['num'] = self.IDEAL_RECORDS

    def send_request(self, maximum=None, initial=None):
        """
        Predict and send optimal number of captcha requests to server process to minimize waiting time.

        :param int maximum: Maximum number of requests to send. Overrides value passed when creating manager
        :param int initial: Number of requests to send if there is not enough data to predict. Overrides value passed
                            when creating manager

        This function must be called periodically to ensure the least waiting time. A general rule is to call it
        every time before you call :meth:`~AutoManager.get_request()` function. If there are already enough requests
        sent, then the function will not send more to avoid captchas being expired.
        """

        if self.stop_new_requests:
            return

        try:

            if not maximum: maximum = self.maximum
            if not initial: initial = self.initial

            # If number of captchas being solved are more or equal to limit, given limit is greater than 0,
            # then we don't send anymore requests
            if 0 < self.limit <= self.ReqsInUnsolvedList + self.ReqsInQueue:
                return

            # There should atleast be three captchas used for there to be adequate data for us to make predictions
            if self.ReqsUsed >= 3:

                # We try to predict how many requests we should send to achieve the least amount of waiting time for
                # future responses. We do this by predicting how many tokens will be available by the time a request
                # sent now would be solved and comparing that with the current usage data.
                with self.instance_lock:

                    # This variable holds the amount of requests for captchas we will send. Initial value is 0.
                    to_send = 0

                    # Before doing any calculations, we update our collected data
                    self._update_stats()

                    # This is the amount of time a request sent now would take to be solved.
                    final_time = self.SolveTime['rate']

                    # Its a fair assumption that by the time this request will be added to the response queue,
                    # all requests currently there in the request queue + unsolved list will be added as well.
                    # Therefore, final_time seconds later, these all captchas will be added to the response queue
                    to_add = self.ReqsInQueue + self.ReqsInUnsolvedList

                    # Then we check how many caps will be used by then
                    to_subtract = final_time // self.UseRate['rate']

                    # We then find the amount of captchas in the response queue after final_time
                    final_caps = self.response_queue.qsize() + to_add - to_subtract

                    # Now we calculate the amount of time these captchas will require to be used up
                    total_time = final_caps * self.UseRate['rate']

                    # Now if the time to use them is below 30s, we can request more captchas to be added. To do this, we
                    # calculate the optimal amount of captchas there should be after final_time seconds and send the
                    # difference in the optimum and our calculated value.
                    if total_time < 25:
                        optimal_final_caps = 30 // self.UseRate['rate']
                        if maximum:
                            to_send = min(optimal_final_caps - final_caps, maximum)
                        else:
                            to_send = optimal_final_caps - final_caps

            else:
                # If we don't have enough data, we simply send initial number of requests
                to_send = initial

            # If sending current number of requests exceeds limit, and limit is greater than 0, then we adjust
            # to_send so that it stays below limit
            if 0 < self.limit < to_send + self.ReqsInQueue + self.ReqsInUnsolvedList:
                to_send = self.limit - self.ReqsInQueue - self.ReqsInUnsolvedList

            # If after adjusting we get a zero or negative value, we return without sending any requests
            if to_send <= 0:
                return

            # Increment counter since we are going to be adding requests in request_queue
            with self.instance_lock:
                self.ReqsInQueue += to_send

            # Finally, add the calculated number of requests in queue
            for _ in range(int(round(to_send))):
                self.request_queue.put(self.create_request(job=self.job))
        except Exception as e:
            msg = "{}\n\nOriginal {}".format(e, traceback.format_exc())
            raise type(e)(msg)


def prepare_module():
    global manager
    for cls in BaseRequest.__subclasses__():
        BaseManager.register(cls.__name__, cls, ObjProxy, exposed=tuple(dir(cls)))

    manager = BaseManager()
    manager.start()